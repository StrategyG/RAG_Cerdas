#!/usr/bin/env python3
"""Pilot-first, append-only Dropbox video -> transcript -> Supabase pgvector worker.

This worker must use the same embedding model as the PDF pipeline and query encoder.
It stages a new generation without deleting prior chunks; retrieval switches only after
all chunks and embeddings have been committed together.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DROPBOX_DOWNLOAD_URL = "https://content.dropboxapi.com/2/files/download"
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
VECTOR_DIMS = 384
DEFAULT_CHUNK_WORDS = 120
DEFAULT_OVERLAP_WORDS = 20


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def download_video(dropbox_token: str, dropbox_id: str, destination: Path) -> None:
    """Stream one source video to a temporary file without logging the token."""
    import requests

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
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("Dropbox download returned an empty video file")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def split_segments(
    segments: list[Any],
    max_words: int = DEFAULT_CHUNK_WORDS,
    overlap_words: int = DEFAULT_OVERLAP_WORDS,
) -> list[dict[str, Any]]:
    """Group Whisper word timestamps into overlapping, timestamp-grounded chunks."""
    if max_words < 20 or overlap_words < 0 or overlap_words >= max_words:
        raise ValueError("Require max_words >= 20 and 0 <= overlap_words < max_words")

    units: list[tuple[str, float, float, str]] = []
    for segment in segments:
        segment_start = float(getattr(segment, "start", 0.0) or 0.0)
        segment_end = float(getattr(segment, "end", segment_start) or segment_start)
        word_items = getattr(segment, "words", None)
        if word_items:
            for word in word_items:
                token = str(getattr(word, "word", "") or "").strip()
                if not token:
                    continue
                start = getattr(word, "start", None)
                end = getattr(word, "end", None)
                word_start = segment_start if start is None else float(start)
                word_end = segment_end if end is None else float(end)
                precision = "word" if start is not None and end is not None else "segment"
                units.append((token, max(0.0, word_start), max(word_start, word_end), precision))
        else:
            # Safe fallback for ASR engines that return segment timestamps only.
            for token in str(getattr(segment, "text", "") or "").split():
                units.append((token, max(0.0, segment_start), max(segment_start, segment_end), "segment"))

    chunks: list[dict[str, Any]] = []
    if not units:
        return chunks

    cursor = 0
    while cursor < len(units):
        window = units[cursor:cursor + max_words]
        text = " ".join(item[0] for item in window).strip()
        if text:
            start_seconds = window[0][1]
            end_seconds = max(item[2] for item in window)
            if end_seconds < start_seconds:
                raise ValueError("Non-monotonic transcript timestamps")
            chunks.append({
                "text": text,
                "start_seconds": round(start_seconds, 3),
                "end_seconds": round(end_seconds, 3),
                "word_count": len(window),
                "timestamp_precision": "word" if all(item[3] == "word" for item in window) else "segment",
            })
        if cursor + max_words >= len(units):
            break
        cursor += max_words - overlap_words
    return chunks


def prepare_passages(chunks: list[dict[str, Any]]) -> list[str]:
    """E5 passage prefix must match the PDF pipeline's multilingual-e5-small model."""
    return ["passage: " + str(chunk["text"]).strip() for chunk in chunks]


def validate_embedding_vectors(vectors: Any, expected_count: int, dimensions: int = VECTOR_DIMS) -> list[list[float]]:
    """Fail closed on shape, non-finite values, or unnormalised vectors."""
    rows = vectors.tolist() if hasattr(vectors, "tolist") else vectors
    if not isinstance(rows, (list, tuple)) or len(rows) != expected_count:
        raise ValueError(f"Expected {expected_count} embedding vectors; got {len(rows) if isinstance(rows, (list, tuple)) else 'invalid'}")
    validated: list[list[float]] = []
    for index, row in enumerate(rows):
        values = row.tolist() if hasattr(row, "tolist") else row
        if not isinstance(values, (list, tuple)) or len(values) != dimensions:
            raise ValueError(f"Embedding {index} must have exactly {dimensions} dimensions")
        vector = [float(value) for value in values]
        if not all(math.isfinite(value) for value in vector):
            raise ValueError(f"Embedding {index} contains a non-finite value")
        norm = math.sqrt(sum(value * value for value in vector))
        if not 0.98 <= norm <= 1.02:
            raise ValueError(f"Embedding {index} is not normalized (L2 norm={norm:.5f})")
        validated.append(vector)
    return validated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1, help="Maximum videos to process (default: one pilot)")
    parser.add_argument("--language", default="id", help="Whisper language code; use 'auto' for detection")
    parser.add_argument("--model", default=WHISPER_MODEL, help="faster-whisper model name; default: small")
    args = parser.parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be >= 1")

    configured_embedding_model = os.getenv("EMBEDDING_MODEL")
    if configured_embedding_model and configured_embedding_model != EMBEDDING_MODEL:
        raise SystemExit(
            f"EMBEDDING_MODEL must be {EMBEDDING_MODEL!r} to match PDF ingestion and query embeddings; "
            "a different model needs a coordinated migration."
        )

    db_url = require_env("SUPABASE_DB_URL")
    dropbox_token = require_env("DROPBOX_ACCESS_TOKEN")

    import psycopg
    from faster_whisper import WhisperModel
    from sentence_transformers import SentenceTransformer
    print(
        f"Loading speech model={args.model!r} device={WHISPER_DEVICE!r}; "
        f"embedding model={EMBEDDING_MODEL!r}"
    )
    speech_model = WhisperModel(args.model, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
    embedding_model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    embedding_model.max_seq_length = 512
    if embedding_model.get_sentence_embedding_dimension() != VECTOR_DIMS:
        raise SystemExit(f"Embedding model must output {VECTOR_DIMS} dimensions for rag.chunks.embedding vector(384).")

    with psycopg.connect(db_url) as conn:
        rows = conn.execute(
            """
            SELECT id::text, source_name, source_path, metadata, file_size_bytes, content_sha256
            FROM rag.documents
            WHERE source_provider = 'dropbox'
              AND mime_type = 'video/mp4'
              AND ingest_status IN ('discovered', 'failed')
            ORDER BY source_name
            LIMIT %s
            """,
            (args.limit,),
        ).fetchall()

        if not rows:
            print("No unprocessed Dropbox MP4 records found.")
            return

        for document_id, source_name, source_path, metadata, expected_size, known_sha256 in rows:
            metadata = metadata or {}
            dropbox_id = str(metadata.get("dropbox_id") or "").strip()
            if not dropbox_id:
                print(f"SKIP {source_name}: metadata.dropbox_id missing; no source write performed")
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
                    actual_size = video_path.stat().st_size
                    if expected_size and actual_size != int(expected_size):
                        raise RuntimeError(
                            f"Downloaded source size mismatch: expected {int(expected_size)} bytes, got {actual_size}"
                        )
                    digest = sha256_file(video_path)
                    if known_sha256 and digest.lower() != str(known_sha256).lower():
                        raise RuntimeError(
                            "Downloaded source SHA-256 differs from the catalog; refusing to replace the active generation."
                        )

                    segments_iter, info = speech_model.transcribe(
                        str(video_path),
                        language=None if args.language == "auto" else args.language,
                        vad_filter=True,
                        word_timestamps=True,
                        condition_on_previous_text=False,
                        beam_size=5,
                    )
                    transcript_segments = list(segments_iter)
                    chunks = split_segments(transcript_segments)
                    if not chunks:
                        raise RuntimeError("Transcription produced no non-empty timestamped text chunks.")

                    passage_texts = prepare_passages(chunks)
                    token_counts = [
                        len(embedding_model.tokenizer.encode(chunk["text"], add_special_tokens=False))
                        for chunk in chunks
                    ]
                    encoded_lengths = [
                        len(embedding_model.tokenizer.encode(text, add_special_tokens=True))
                        for text in passage_texts
                    ]
                    if any(length > embedding_model.max_seq_length for length in encoded_lengths):
                        raise RuntimeError(
                            "Transcript chunk exceeds the embedding model token limit; refusing silent truncation."
                        )
                    encoded = embedding_model.encode(
                        passage_texts,
                        normalize_embeddings=True,
                        convert_to_numpy=True,
                        show_progress_bar=False,
                        batch_size=24,
                    )
                    vectors = validate_embedding_vectors(encoded, len(chunks))

                    # Append a new generation atomically. The old generation remains
                    # stored and active until every transcript chunk and vector is valid.
                    generation = str(uuid.uuid4())
                    with conn.transaction():
                        locked = conn.execute(
                            "SELECT metadata FROM rag.documents WHERE id=%s FOR UPDATE",
                            (document_id,),
                        ).fetchone()
                        if not locked:
                            raise RuntimeError("Document row disappeared before generation commit")
                        current_metadata = locked[0] or {}
                        next_chunk_index = int(conn.execute(
                            "SELECT COALESCE(MAX(chunk_index), -1) + 1 FROM rag.chunks WHERE document_id=%s",
                            (document_id,),
                        ).fetchone()[0])
                        if next_chunk_index + len(chunks) - 1 > 2147483647:
                            raise RuntimeError("Document chunk_index range exhausted")

                        for offset, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
                            vector_literal = "[" + ",".join(f"{value:.8f}" for value in vector) + "]"
                            chunk_hash = hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest()
                            chunk_metadata = {
                                "source_type": "video",
                                "media_type": "video",
                                "source_name": source_name,
                                "video_generation": generation,
                                "start_seconds": chunk["start_seconds"],
                                "end_seconds": chunk["end_seconds"],
                                "start_timestamp": _timestamp(chunk["start_seconds"]),
                                "end_timestamp": _timestamp(chunk["end_seconds"]),
                                "word_count": chunk["word_count"],
                                "timestamp_precision": chunk["timestamp_precision"],
                                "language": getattr(info, "language", args.language),
                                "language_probability": getattr(info, "language_probability", None),
                                "transcript_engine": f"faster-whisper:{args.model}",
                                "embedding_model": EMBEDDING_MODEL,
                                "source_sha256": digest,
                            }
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
                                    next_chunk_index + offset,
                                    chunk["text"],
                                    token_counts[offset],
                                    chunk_hash,
                                    json.dumps(chunk_metadata),
                                    vector_literal,
                                    EMBEDDING_MODEL,
                                ),
                            )

                        current_video_metadata = current_metadata.get("video_rag") or {}
                        new_video_metadata = {
                            **current_video_metadata,
                            "active_generation": generation,
                            "transcript_status": "complete",
                            "transcript_engine": f"faster-whisper:{args.model}",
                            "embedding_model": EMBEDDING_MODEL,
                            "language": getattr(info, "language", args.language),
                            "language_probability": getattr(info, "language_probability", None),
                            "duration_seconds": getattr(info, "duration", None),
                            "source_sha256": digest,
                            "source_bytes": actual_size,
                            "chunk_count": len(chunks),
                            "chunk_words": DEFAULT_CHUNK_WORDS,
                            "chunk_overlap_words": DEFAULT_OVERLAP_WORDS,
                            "previous_generations_retained": True,
                            "indexed_at": None,
                        }
                        new_video_metadata["indexed_at"] = datetime.now(timezone.utc).isoformat()
                        current_metadata["media_type"] = "video"
                        current_metadata["video_rag"] = new_video_metadata
                        updated = conn.execute(
                            """
                            UPDATE rag.documents
                            SET ingest_status='indexed', ingest_error=NULL, content_sha256=%s,
                                metadata=%s::jsonb, indexed_at=now(), updated_at=now()
                            WHERE id=%s
                            RETURNING id
                            """,
                            (digest, json.dumps(current_metadata), document_id),
                        ).fetchone()
                        if not updated:
                            raise RuntimeError("Document activation update affected zero rows")

                print(
                    f"INDEXED {source_name}: {len(chunks)} chunks; model={EMBEDDING_MODEL}; "
                    f"generation={generation}; source_sha256={digest}"
                )
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
