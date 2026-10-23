-- Citation-safe retrieval hardening.
-- Never return legacy chunks unless they map to exactly one original PDF page.
-- Existing rows are retained; page-aware ingestion will gradually restore results.

CREATE OR REPLACE FUNCTION rag.match_chunks_keyword(
  query_text text,
  match_count integer DEFAULT 10,
  min_rank double precision DEFAULT 0
)
RETURNS TABLE(
  chunk_id uuid, document_id uuid, document_name text, source_path text,
  chunk_index integer, page_start integer, page_end integer, text_content text,
  content_sha256 text, rank double precision
)
LANGUAGE sql STABLE
SET search_path TO ''
AS $function$
  WITH q AS (
    SELECT pg_catalog.plainto_tsquery('pg_catalog.simple'::pg_catalog.regconfig, query_text) AS tsq
  )
  SELECT c.id, c.document_id, d.source_name, d.source_path, c.chunk_index,
         c.page_start, c.page_end, c.text_content, c.content_sha256,
         pg_catalog.ts_rank_cd(c.search_vector, q.tsq)::double precision
  FROM rag.chunks AS c
  JOIN rag.documents AS d ON d.id = c.document_id
  CROSS JOIN q
  WHERE pg_catalog.numnode(q.tsq) > 0
    AND c.search_vector @@ q.tsq
    AND pg_catalog.ts_rank_cd(c.search_vector, q.tsq) >= min_rank
    AND c.page_start IS NOT NULL
    AND c.page_start >= 1
    AND c.page_end = c.page_start
    AND (
      (NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NOT NULL
       AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'active_generation')
      OR
      (NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NULL
       AND c.metadata->>'ingest_generation' IS NULL)
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
  chunk_id uuid, document_id uuid, document_name text, source_path text,
  chunk_index integer, page_start integer, page_end integer, text_content text,
  content_sha256 text, similarity double precision
)
LANGUAGE sql STABLE
SET search_path TO ''
AS $function$
  SELECT c.id, c.document_id, d.source_name, d.source_path, c.chunk_index,
         c.page_start, c.page_end, c.text_content, c.content_sha256,
         (1 - (c.embedding OPERATOR(extensions.<=>) query_embedding))::double precision
  FROM rag.chunks AS c
  JOIN rag.documents AS d ON d.id = c.document_id
  WHERE c.embedding IS NOT NULL
    AND (1 - (c.embedding OPERATOR(extensions.<=>) query_embedding)) >= min_similarity
    AND c.page_start IS NOT NULL
    AND c.page_start >= 1
    AND c.page_end = c.page_start
    AND (
      (NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NOT NULL
       AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'active_generation')
      OR
      (NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NULL
       AND c.metadata->>'ingest_generation' IS NULL)
    )
  ORDER BY c.embedding OPERATOR(extensions.<=>) query_embedding
  LIMIT LEAST(GREATEST(COALESCE(match_count, 10), 1), 50);
$function$;

CREATE OR REPLACE FUNCTION institutional_rag.search_chunks(
  query_text text, result_limit integer DEFAULT 10
)
RETURNS TABLE(
  chunk_id uuid, source_document_id uuid, title text, source_path text,
  content text, page_start integer, page_end integer, rank real
)
LANGUAGE sql STABLE
SET search_path TO 'institutional_rag', 'pg_temp'
AS $function$
  SELECT c.id, d.id, d.title, d.source_path, c.content, c.page_start, c.page_end,
         ts_rank(c.search_vector, websearch_to_tsquery('simple', query_text)) AS rank
  FROM institutional_rag.document_chunks AS c
  JOIN institutional_rag.source_documents AS d ON d.id = c.source_document_id
  WHERE NULLIF(trim(query_text), '') IS NOT NULL
    AND c.search_vector @@ websearch_to_tsquery('simple', query_text)
    AND c.page_start IS NOT NULL
    AND c.page_start >= 1
    AND c.page_end = c.page_start
  ORDER BY rank DESC
  LIMIT GREATEST(1, LEAST(COALESCE(result_limit, 10), 100));
$function$;

CREATE INDEX IF NOT EXISTS evaluation_results_case_id_idx
  ON institutional_rag.evaluation_results (case_id);
