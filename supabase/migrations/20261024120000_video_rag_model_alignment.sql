-- Align video retrieval with the same E5 embedding space as PDF retrieval.
-- Video chunks are append-only and carry metadata.video_generation. Only the
-- generation selected by rag.documents.metadata.video_rag.active_generation is visible.
-- This migration changes retrieval functions only; it does not mutate source data.

CREATE OR REPLACE FUNCTION rag.match_chunks_keyword(
  query_text text,
  match_count integer DEFAULT 10,
  min_rank double precision DEFAULT 0
)
RETURNS TABLE(
  chunk_id uuid,
  document_id uuid,
  document_name text,
  source_path text,
  chunk_index integer,
  page_start integer,
  page_end integer,
  text_content text,
  content_sha256 text,
  rank double precision
)
LANGUAGE sql
STABLE
SET search_path TO ''
AS $function$
  WITH q AS (
    SELECT pg_catalog.plainto_tsquery('pg_catalog.simple'::pg_catalog.regconfig, query_text) AS tsq
  )
  SELECT
    c.id AS chunk_id,
    c.document_id,
    d.source_name AS document_name,
    d.source_path,
    c.chunk_index,
    c.page_start,
    c.page_end,
    c.text_content,
    c.content_sha256,
    pg_catalog.ts_rank_cd(c.search_vector, q.tsq)::double precision AS rank
  FROM rag.chunks AS c
  JOIN rag.documents AS d ON d.id = c.document_id
  CROSS JOIN q
  WHERE pg_catalog.numnode(q.tsq) > 0
    AND c.search_vector @@ q.tsq
    AND pg_catalog.ts_rank_cd(c.search_vector, q.tsq) >= min_rank
    AND (
      (
        d.mime_type = 'video/mp4'
        AND NULLIF(d.metadata->'video_rag'->>'active_generation', '') IS NOT NULL
        AND c.metadata->>'video_generation' = d.metadata->'video_rag'->>'active_generation'
      )
      OR
      (
        d.mime_type IS DISTINCT FROM 'video/mp4'
        AND (
          (
            NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NOT NULL
            AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'active_generation'
          )
          OR
          (
            NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NULL
            AND c.metadata->>'ingest_generation' IS NULL
          )
        )
      )
    )
  ORDER BY pg_catalog.ts_rank_cd(c.search_vector, q.tsq) DESC, c.document_id, c.chunk_index
  LIMIT LEAST(GREATEST(COALESCE(match_count, 10), 1), 50);
$function$;

CREATE OR REPLACE FUNCTION rag.match_chunks_semantic(
  query_embedding extensions.vector,
  match_count integer DEFAULT 10,
  min_similarity double precision DEFAULT 0.0
)
RETURNS TABLE(
  chunk_id uuid,
  document_id uuid,
  document_name text,
  source_path text,
  chunk_index integer,
  page_start integer,
  page_end integer,
  text_content text,
  content_sha256 text,
  similarity double precision
)
LANGUAGE sql
STABLE
SET search_path TO ''
AS $function$
  SELECT
    c.id AS chunk_id,
    c.document_id,
    d.source_name AS document_name,
    d.source_path,
    c.chunk_index,
    c.page_start,
    c.page_end,
    c.text_content,
    c.content_sha256,
    (1 - (c.embedding OPERATOR(extensions.<=>) query_embedding))::double precision AS similarity
  FROM rag.chunks AS c
  JOIN rag.documents AS d ON d.id = c.document_id
  WHERE c.embedding IS NOT NULL
    -- Query embeddings use intfloat/multilingual-e5-small. Comparing vectors
    -- from a different model is mathematically possible but semantically invalid.
    AND c.embedding_model = 'intfloat/multilingual-e5-small'
    AND (1 - (c.embedding OPERATOR(extensions.<=>) query_embedding)) >= min_similarity
    AND (
      (
        d.mime_type = 'video/mp4'
        AND NULLIF(d.metadata->'video_rag'->>'active_generation', '') IS NOT NULL
        AND c.metadata->>'video_generation' = d.metadata->'video_rag'->>'active_generation'
      )
      OR
      (
        d.mime_type IS DISTINCT FROM 'video/mp4'
        AND (
          (
            NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NOT NULL
            AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'active_generation'
          )
          OR
          (
            NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NULL
            AND c.metadata->>'ingest_generation' IS NULL
          )
        )
      )
    )
  ORDER BY c.embedding OPERATOR(extensions.<=>) query_embedding
  LIMIT LEAST(GREATEST(COALESCE(match_count, 10), 1), 50);
$function$;

-- The existing public rag_worker_match_* wrappers keep their permissions and
-- signatures; they call these functions. Verify wrapper compatibility and grants
-- in staging before applying this migration to a live database.
