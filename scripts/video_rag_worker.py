#!/usr/bin/env python3
"""CPU-friendly, pilot-first Dropbox video -> transcript -> Supabase pgvector worker.

Required environment:
  SUPABASE_DB_URL       PostgreSQL connection string (keep secret)
  DROPBOX_ACCESS_TOKEN  Dropbox API token with files.content.read / metadata.read

Default behavior processes at most one video. Run from Codespaces terminal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import psycopg
import requests
from faster_whisper import WhisperModel
from sentence_transformers import SentenceTransformer

DROPBOX_DOWNLOAD_URL = "https://content.dropboxapi.com/2/files/download"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def download_video(dropbox_token: str, dropbox_id: str, destination: Path) -> None:
    # Dropbox file IDs are passed as "id:..." as documented by Dropbox API.
    arg = json.dumps({"path": dropbox_id}, separators=(",", ":"))
    with requests.post(
        DROPBOX_DOWNLOAD_URL,
        headers={
            "Authorization": f"Bearer {dropbox_token}",
            "Dropbox-API-Arg": arg,
        },
        stream=True,
        timeout=(20, 180),
    ) as response:
        response.raise_for_status()
        with destination.open("wb") as out:
            for block in response.iter_content(chunk_size=1024 * 1024):
                if block:
                    out.write(block)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def split_segments(segments: list[Any], max_words: int = 220) -> list[dict[str, Any]]:
    """Group timestamped Whisper segments; keep each chunk's real time boundaries."""
    chunks: list[dict[str, Any]] = []
    words: list[str] = []
    start: float | None = None
    end: float | None = None

    def flush() -> None:
        nonlocal words, start, end
        text = " ".join(words).strip()
        if text and start is not None and end is not None:
            chunks.append({"text": text, "start_seconds": round(start, 3), "end_seconds": round(end, 3)})
        words, start, end = [], None, None

    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        segment_words = text.split()
        if words and len(words) + len(segment_words) > max_words:
            flush()
        if start is None:
            start = float(segment.start)
        end = float(segment.end)
        words.extend(segment_words)
    flush()
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1, help="Maximum videos to process (default: 1 pilot)")
    parser.add_argument("--language", default="id", help="Whisper language code; use 'auto' for detection")
    parser.add_argument("--model", default=WHISPER_MODEL, help="faster-whisper model name; default: small")
    args = parser.parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be >= 1")

    db_url = require_env("SUPABASE_DB_URL")
    dropbox_token = require_env("DROPBOX_ACCESS_TOKEN")
    print(f"Loading speech model={args.model!r} device={WHISPER_DEVICE!r}; embedding model={EMBEDDING_MODEL!r}")
    speech_model = WhisperModel(args.model, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
    embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    if embedding_model.get_sentence_embedding_dimension() != 384:
        raise SystemExit("Embedding model must output 384 dimensions to match rag.chunks.embedding vector(384).")

    with psycopg.connect(db_url) as conn:
        rows = conn.execute(
            """
            SELECT id::text, source_name, source_path, metadata
            FROM rag.documents
            WHERE source_provider = 'dropbox'
              AND (mime_type LIKE 'video/%' OR lower(source_name) ~ '\.(mp4|mov|m4v|webm|mkv|avi)$')
              AND ingest_status IN ('discovered', 'failed')
            ORDER BY source_name
            LIMIT %s
            """,
            (args.limit,),
        ).fetchall()

        if not rows:
            print("No unprocessed Dropbox MP4 records found.")
            return

        for document_id, source_name, source_path, metadata in rows:
            metadata = metadata or {}
            dropbox_id = metadata.get("dropbox_id")
            if not dropbox_id:
                print(f"SKIP {source_name}: metadata.dropbox_id missing")
                continue

            print(f"Processing: {source_name}")
            conn.execute(
                "UPDATE rag.documents SET ingest_status='processing', ingest_error=NULL, updated_at=now() WHERE id=%s",
                (document_id,),
            )
            conn.commit()
            try:
                with tempfile.TemporaryDirectory(prefix="video-rag-") as tmp:
                    video_path = Path(tmp) / "source.mp4"
                    download_video(dropbox_token, dropbox_id, video_path)
                    digest = sha256_file(video_path)
                    segments_iter, info = speech_model.transcribe(
                        str(video_path),
                        language=None if args.language == "auto" else args.language,
                        vad_filter=True,
                        word_timestamps=False,
                    )
                    transcript_segments = list(segments_iter)
                    chunks = split_segments(transcript_segments)
                    if not chunks:
                        raise RuntimeError("Transcription produced no non-empty text chunks.")

                    vectors = embedding_model.encode(
                        ["passage: " + chunk["text"] for chunk in chunks],
                        normalize_embeddings=True,
                        show_progress_bar=False,
                        convert_to_numpy=True,
                    )
                    if vectors.ndim != 2 or vectors.shape != (len(chunks), 384):
                        raise RuntimeError("Embedding output must be a finite N x 384 matrix.")
                    import numpy as np
                    if not np.isfinite(vectors).all():
                        raise RuntimeError("Embedding output contains NaN or infinite values.")

                    generation_id = str(uuid.uuid4())
                    with conn.transaction():
                        # Append a new generation. Keep all previous chunks for rollback/audit.
                        chunk_base = conn.execute(
                            "SELECT COALESCE(MAX(chunk_index), -1) + 1 FROM rag.chunks WHERE document_id=%s",
                            (document_id,),
                        ).fetchone()[0]
                        for index, (chunk, vector) in enumerate(zip(chunks, vectors), start=int(chunk_base)):
                            vector_literal = "[" + ",".join(f"{float(v):.8f}" for v in vector) + "]"
                            chunk_hash = hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest()
                            conn.execute(
                                """
                                INSERT INTO rag.chunks
                                  (document_id, chunk_index, text_content, token_count,
                                   content_sha256, metadata, embedding, embedding_model, embedded_at)
                                VALUES
                                  (%s, %s, %s, %s, %s, %s::jsonb, %s::vector, %s, now())
                                """,
                                (
                                    document_id,
                                    index,
                                    chunk["text"],
                                    len(chunk["text"].split()),
                                    chunk_hash,
                                    json.dumps({
                                        "source_type": "video",
                                        "source_name": source_name,
                                        "ingest_generation": generation_id,
                                        "chunking_version": "timestamped-video-v1",
                                        "start_seconds": chunk["start_seconds"],
                                        "end_seconds": chunk["end_seconds"],
                                        "start_timestamp": _timestamp(chunk["start_seconds"]),
                                        "end_timestamp": _timestamp(chunk["end_seconds"]),
                                        "language": getattr(info, "language", args.language),
                                        "transcript_engine": f"faster-whisper:{args.model}",
                                    }),
                                    vector_literal,
                                    EMBEDDING_MODEL,
                                ),
                            )
                        new_metadata = {
                            **metadata,
                            "media_type": "video",
                            "pipeline_stage": "transcribed_embedded",
                            "transcript_status": "complete",
                            "transcript_engine": f"faster-whisper:{args.model}",
                            "embedding_model": EMBEDDING_MODEL,
                            "transcript_chunk_count": len(chunks),
                            "duration_seconds": getattr(info, "duration", None),
                            "source_sha256": digest,
                            "page_aware_ingest": {
                                **(metadata.get("page_aware_ingest") or {}),
                                "version": 1,
                                "active_generation": generation_id,
                                "page_mapping": "timestamped_video",
                                "chunk_count": len(chunks),
                                "content_sha256": digest,
                                "indexed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                            },
                        }
                        conn.execute(
                            """
                            UPDATE rag.documents
                            SET ingest_status='indexed', ingest_error=NULL, content_sha256=%s,
                                metadata=%s::jsonb, indexed_at=now(), updated_at=now()
                            WHERE id=%s
                            """,
                            (digest, json.dumps(new_metadata), document_id),
                        )
                print(f"INDEXED {source_name}: generation={generation_id}, {len(chunks)} chunks; SHA-256={digest}")
            except Exception as exc:
                conn.execute(
                    "UPDATE rag.documents SET ingest_status='failed', ingest_error=%s, updated_at=now() WHERE id=%s",
                    (f"{type(exc).__name__}: {str(exc)[:1500]}", document_id),
                )
                conn.commit()
                print(f"FAILED {source_name}: {type(exc).__name__}: {exc}")


def _timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


if __name__ == "__main__":
    main()
