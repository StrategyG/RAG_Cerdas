-- Read-only diagnostic for ingestion stalls and the approved Ikigai pilot.
-- This file intentionally contains SELECT statements only. It does not enqueue jobs,
-- change document statuses, mutate RLS, overwrite chunks, or touch Dropbox originals.
--
-- Interpret "processing_without_active_job" as an orphaned state requiring investigation,
-- not permission to reset/requeue the document automatically.

-- 1) Compare document statuses with actual queue activity.
SELECT
  d.ingest_status,
  count(*)::bigint AS documents,
  count(*) FILTER (
    WHERE NOT EXISTS (
      SELECT 1
      FROM rag.ingest_jobs j
      WHERE j.document_id = d.id
        AND j.status IN ('queued', 'running')
    )
  )::bigint AS documents_without_active_job
FROM rag.documents d
GROUP BY d.ingest_status
ORDER BY d.ingest_status;

-- 2) Inspect processing documents without queued/running jobs, including generation state.
-- No document text, secret, token, or full error message is returned.
SELECT
  d.id AS document_id,
  d.source_name,
  d.updated_at,
  round(extract(epoch FROM (now() - d.updated_at)) / 60.0, 1) AS minutes_since_document_update,
  d.ingest_status,
  d.metadata->'page_aware_ingest'->>'active_generation' AS active_generation,
  d.metadata->'page_aware_ingest'->>'pending_generation' AS pending_generation,
  d.metadata->'page_aware_ingest'->>'pending_page_count' AS pending_page_count,
  d.metadata->'page_aware_ingest'->>'pending_chunk_count' AS pending_chunk_count,
  count(c.id)::bigint AS retained_chunks,
  count(c.id) FILTER (WHERE c.embedding IS NOT NULL)::bigint AS embedded_chunks,
  count(c.id) FILTER (
    WHERE c.page_start IS NOT NULL
      AND c.page_end = c.page_start
  )::bigint AS single_page_mapped_chunks,
  count(c.id) FILTER (
    WHERE d.metadata->'page_aware_ingest'->>'pending_generation' IS NOT NULL
      AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'pending_generation'
  )::bigint AS pending_generation_chunks,
  count(c.id) FILTER (
    WHERE d.metadata->'page_aware_ingest'->>'pending_generation' IS NOT NULL
      AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'pending_generation'
      AND c.embedding IS NOT NULL
      AND c.page_start IS NOT NULL
      AND c.page_end = c.page_start
  )::bigint AS embedded_and_page_mapped_pending_chunks
FROM rag.documents d
LEFT JOIN rag.chunks c ON c.document_id = d.id
WHERE d.ingest_status = 'processing'
  AND NOT EXISTS (
    SELECT 1
    FROM rag.ingest_jobs j
    WHERE j.document_id = d.id
      AND j.status IN ('queued', 'running')
  )
GROUP BY d.id
ORDER BY d.updated_at ASC;

-- 3) Readiness check for the intended pilot only. This is not an ingestion command.
SELECT
  d.id AS document_id,
  d.source_name,
  d.source_path,
  d.ingest_status,
  d.file_size_bytes,
  d.content_sha256 IS NOT NULL AS has_source_sha256,
  d.page_count,
  d.metadata->'page_aware_ingest'->>'active_generation' AS active_generation,
  count(c.id)::bigint AS retained_chunks,
  count(c.id) FILTER (WHERE c.embedding IS NOT NULL)::bigint AS embedded_chunks,
  count(c.id) FILTER (
    WHERE c.page_start IS NOT NULL
      AND c.page_end = c.page_start
  )::bigint AS single_page_mapped_chunks
FROM rag.documents d
LEFT JOIN rag.chunks c ON c.document_id = d.id
WHERE lower(trim(d.source_name)) = 'ikigai .pdf'
   OR lower(trim(d.source_path)) = '/ikigai .pdf'
GROUP BY d.id
ORDER BY d.source_name;

-- Safety: review these results first. Never mass-reset 'processing' rows or rerun
-- ingestion across the corpus. The pilot requires a separate dry-run and explicit
-- approval before any production write.
