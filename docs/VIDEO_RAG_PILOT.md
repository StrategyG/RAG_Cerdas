# Video RAG pilot (Dropbox -> Supabase)

## Current verified state

- Dropbox's full recursive inventory found 23 MP4 files. Six missing video catalog rows were added additively to Supabase on 2026-10-24. A subsequent ID-and-size reconciliation found an exact 23/23 match, with no missing, stale, size-mismatched, or duplicate video IDs; all 23 remain `discovered`, with 0 video chunks and 0 video embeddings.
- `rag.chunks.embedding` is `vector(384)`. The PDF ingestion worker and query evaluator use `intfloat/multilingual-e5-small`.
- The video worker must use that exact embedding model and the E5 `passage:` prefix. A different model is incompatible even if it also emits 384-dimensional vectors.
- The video worker now uses append-only generations. It writes a new set of chunks, then switches `metadata.video_rag.active_generation` only when the complete transcript and all embeddings are ready. It does not delete prior chunks.
- Migration `supabase/migrations/20261023200123_video_rag_model_alignment.sql` is applied to the configured live project (`uktauwysjkseqrnbjwzy`) and was verified in migration history. Read-only checks confirm active-generation filters, E5 semantic-model filtering, valid one-page PDF mapping checks, and service-role-only access to the public retrieval wrappers. For any other project, apply and verify this migration through the normal migration process before video ingestion; do not run the worker before that project's migration is applied.

## Prerequisites in Codespaces

Add these as **Codespaces repository secrets**; never commit them or paste values into chat:

- `DROPBOX_ACCESS_TOKEN`: Dropbox API token with permission to read the registered videos.
- `SUPABASE_DB_URL`: PostgreSQL connection string for the existing Supabase project. Use the project's recommended connection method and keep the credential private.

The worker uses local CPU transcription with faster-whisper and E5 embeddings. The first run downloads model weights and therefore requires network access, disk, and RAM. The video is downloaded temporarily and removed after processing.

## Pilot commands

From the repository root in the Codespace terminal:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-video-rag.txt
python -m py_compile scripts/video_rag_worker.py
python -m pytest -q tests/test_video_rag_worker.py tests/test_page_chunking.py
```

Ensure the two secrets are available as environment variables in the current terminal session without printing their values. Then run **one video only**:

```bash
python scripts/video_rag_worker.py --limit 1 --language id
```

Do not run `--limit 17` until the pilot has passed every check below. On a Codespace with limited CPU/RAM, a smaller Whisper model such as `base` may be used for a first functional test, but review its transcript quality manually before treating it as evidence. The embedding model must not be changed without a coordinated migration.

## Acceptance checks after the pilot

Run this read-only SQL in the Supabase SQL editor. It counts only the active video generation, not retained historical generations:

```sql
SELECT d.source_name,
       d.ingest_status,
       d.ingest_error,
       d.metadata->'video_rag'->>'active_generation' AS active_generation,
       count(c.id) AS active_chunk_count,
       count(c.id) FILTER (WHERE c.embedding IS NOT NULL) AS embedded_chunks,
       count(c.id) FILTER (
         WHERE c.embedding_model = 'intfloat/multilingual-e5-small'
       ) AS e5_chunks,
       count(c.id) FILTER (
         WHERE c.metadata->>'timestamp_precision' = 'word'
       ) AS word_timestamp_chunks,
       count(c.id) FILTER (
         WHERE c.metadata->>'timestamp_precision' = 'segment'
       ) AS segment_timestamp_chunks,
       min((c.metadata->>'start_seconds')::numeric) AS first_second,
       max((c.metadata->>'end_seconds')::numeric) AS last_second
FROM rag.documents d
LEFT JOIN rag.chunks c
  ON c.document_id = d.id
 AND c.metadata->>'video_generation' = d.metadata->'video_rag'->>'active_generation'
WHERE d.mime_type = 'video/mp4'
GROUP BY d.id
ORDER BY d.source_name;
```

The pilot passes only when:

1. The processed video is `indexed` and has a non-empty active generation.
2. Every active chunk has a non-null embedding made by `intfloat/multilingual-e5-small`.
3. Every active chunk has valid `start_seconds` and `end_seconds`, and the intervals are monotonic.
4. Word-level timestamp coverage is reviewed; segment-level fallback must be clearly understood as less precise.
5. The number of old chunks has not decreased.
6. A spoken answer is found by semantic retrieval, and its returned evidence shows the video title and timestamp label. Manually verify the transcript snippet against the original video.

Do not scale to the remaining videos merely because the database status says `indexed`. Verify retrieval and citation quality for the pilot first.

## Limitations / safety

- The worker indexes **spoken audio/transcript**. It does not OCR slides or describe visual scenes, so visual-only claims are out of scope.
- Chunks use overlapping groups of timestamped words. Metadata records the source SHA-256, embedding model, transcript engine, start/end seconds, and whether timestamps are word- or segment-level.
- A new generation is appended atomically. The prior generation remains stored and active if a run fails.
- The worker checks downloaded byte size and rejects a source SHA-256 mismatch rather than silently indexing content that differs from the catalog.
- The worker does not delete original Dropbox videos or old chunk rows.
- Supabase migration application, database connectivity, secrets, and full live retrieval are separate checks; committing this code does not prove those checks passed.
