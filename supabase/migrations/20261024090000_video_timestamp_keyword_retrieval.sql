-- Extend keyword retrieval to timestamp-cited Dropbox videos while retaining page-cited PDF rules.
-- Additive function-body update only; no source/chunk rows are deleted or rewritten.
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
    CASE WHEN d.mime_type LIKE 'video/%' THEN
      '[Video ' || COALESCE(c.metadata->>'start_timestamp', 'time unknown') || ' - ' ||
      COALESCE(c.metadata->>'end_timestamp', 'time unknown') || '] ' || c.text_content
    ELSE c.text_content END AS text_content,
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
        d.mime_type LIKE 'video/%'
        AND NULLIF(d.metadata->'video_rag'->>'active_generation', '') IS NOT NULL
        AND c.metadata->>'video_generation' = d.metadata->'video_rag'->>'active_generation'
        AND NULLIF(c.metadata->>'start_timestamp', '') IS NOT NULL
        AND NULLIF(c.metadata->>'end_timestamp', '') IS NOT NULL
      )
      OR
      (
        d.mime_type IS DISTINCT FROM 'video/mp4'
        AND d.mime_type NOT LIKE 'video/%'
        AND (
          (
            NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NOT NULL
            AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'active_generation'
            AND c.page_start IS NOT NULL
            AND c.page_end = c.page_start
          )
          OR
          (
            NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NULL
            AND c.metadata->>'ingest_generation' IS NULL
            AND c.page_start IS NOT NULL
            AND c.page_end = c.page_start
          )
        )
      )
    )
  ORDER BY pg_catalog.ts_rank_cd(c.search_vector, q.tsq) DESC, c.document_id, c.chunk_index
  LIMIT LEAST(GREATEST(COALESCE(match_count, 10), 1), 50);
$function$;

REVOKE ALL ON FUNCTION rag.match_chunks_keyword(text, integer, double precision)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION rag.match_chunks_keyword(text, integer, double precision)
  TO service_role;
