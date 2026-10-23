-- Read-only verification for the Dropbox MP4 -> Whisper transcript -> pgvector pipeline.
-- Run after a one-video pilot. No source rows or chunks are modified by this script.

SELECT
  count(*)::bigint AS catalogued_videos,
  count(*) FILTER (WHERE ingest_status = 'indexed')::bigint AS indexed_videos,
  count(*) FILTER (WHERE ingest_status = 'failed')::bigint AS failed_videos,
  count(*) FILTER (WHERE ingest_status IN ('discovered', 'processing'))::bigint AS pending_or_processing_videos,
  count(*) FILTER (
    WHERE NULLIF(metadata->'video_rag'->>'active_generation', '') IS NOT NULL
  )::bigint AS videos_with_active_generation
FROM rag.documents
WHERE source_provider = 'dropbox'
  AND mime_type = 'video/mp4';

SELECT
  d.id,
  d.source_name,
  d.ingest_status,
  d.metadata->'video_rag'->>'active_generation' AS active_generation,
  count(c.id)::bigint AS active_chunks,
  count(c.id) FILTER (WHERE c.embedding IS NOT NULL)::bigint AS embedded_chunks,
  count(c.id) FILTER (
    WHERE NULLIF(c.metadata->>'start_timestamp', '') IS NULL
       OR NULLIF(c.metadata->>'end_timestamp', '') IS NULL
       OR NULLIF(c.metadata->>'start_seconds', '') IS NULL
       OR NULLIF(c.metadata->>'end_seconds', '') IS NULL
       OR (c.metadata->>'end_seconds')::double precision < (c.metadata->>'start_seconds')::double precision
  )::bigint AS invalid_timestamp_chunks,
  count(c.id) FILTER (
    WHERE c.embedding IS NOT NULL
      AND c.embedding_model = 'intfloat/multilingual-e5-small'
  )::bigint AS correctly_modelled_embeddings
FROM rag.documents AS d
LEFT JOIN rag.chunks AS c
  ON c.document_id = d.id
 AND c.metadata->>'source_type' = 'video'
 AND c.metadata->>'video_generation' = d.metadata->'video_rag'->>'active_generation'
WHERE d.source_provider = 'dropbox'
  AND d.mime_type = 'video/mp4'
  AND NULLIF(d.metadata->'video_rag'->>'active_generation', '') IS NOT NULL
GROUP BY d.id, d.source_name, d.ingest_status, d.metadata->'video_rag'->>'active_generation'
ORDER BY d.source_name;

-- Smoke-test lexical retrieval against the words most likely to occur in the Indonesian video catalog.
-- The returned text excerpt should include a [Video HH:MM:SS - HH:MM:SS] citation prefix.
SELECT
  chunk_id, document_name, source_path, page_start, page_end, text_content, rank
FROM rag.match_chunks_keyword('investasi saham', 10, 0)
ORDER BY rank DESC;
