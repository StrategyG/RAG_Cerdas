# Video RAG pilot (Dropbox -> Supabase)

## Current verified state

- 17 Dropbox MP4 files were registered in `rag.documents` on 2026-10-19.
- All 17 are `discovered`; no transcript chunks or embeddings have been generated yet.
- `rag.chunks.embedding` is `vector(384)`.
- The worker is deliberately pilot-first: its default limit is one video. It does not start a 17-video batch unless explicitly requested.

## Prerequisites in Codespaces

Add these as **Codespaces repository secrets**; never commit them or paste values into chat:

- `DROPBOX_ACCESS_TOKEN`: Dropbox API token with permission to read the registered videos.
- `SUPABASE_DB_URL`: PostgreSQL connection string for the existing Supabase project. Use the project's recommended connection method and keep the credential private.

The worker uses local CPU transcription with faster-whisper and a 384-dimensional Sentence Transformers model. The first run downloads model weights and therefore requires network access and disk/RAM. The video itself is downloaded temporarily and removed after processing.

## Pilot commands

From the repository root in the Codespace terminal:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-video-rag.txt
python -m py_compile scripts/video_rag_worker.py
```

Ensure the two secrets are available as environment variables in the current terminal session without printing their values. Then run **one video only**:

```bash
python scripts/video_rag_worker.py --limit 1 --language id
```

Do not run `--limit 17` until the pilot has passed the checks below. On a Codespace with limited CPU/RAM, choose a smaller Whisper model if necessary, e.g. `WHISPER_MODEL=base`; the embedding model must remain 384-dimensional unless the database schema and all retrieval code are migrated together.

## Acceptance checks after the pilot

Run this read-only SQL in the Supabase SQL editor:

```sql
SELECT d.source_name,
       d.ingest_status,
       d.ingest_error,
       count(c.id) AS chunk_count,
       count(c.id) FILTER (WHERE c.embedding IS NOT NULL) AS embedded_chunks,
       min((c.metadata->>'start_seconds')::numeric) AS first_second,
       max((c.metadata->>'end_seconds')::numeric) AS last_second
FROM rag.documents d
LEFT JOIN rag.chunks c ON c.document_id = d.id
WHERE d.mime_type = 'video/mp4'
GROUP BY d.id, d.source_name, d.ingest_status, d.ingest_error
ORDER BY d.source_name;
```

Pilot passes only when the processed video is `indexed`, has nonzero chunks, all its chunks have embeddings, timestamp metadata is present and increasing, and the transcript snippets are manually checked against the video. Then test retrieval with a question whose answer is clearly spoken in the pilot and confirm the answer cites the video title and timestamp.

## Limitations / safety

- This worker indexes **spoken audio/transcript**. It does not yet OCR slides or describe visual scenes.
- It writes transcript chunks into the existing `rag.chunks` table and uses the existing 384-dimension vector column. It does not write to Qdrant.
- It marks the document `failed` and records an error when processing fails. It does not delete original Dropbox videos.
- Verify the pilot's database connection, secret permissions, runtime, and citation quality before processing the remaining 16 videos.
