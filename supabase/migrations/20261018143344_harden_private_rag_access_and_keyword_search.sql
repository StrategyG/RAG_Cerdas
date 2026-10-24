BEGIN;

-- Internal database schema: deny API roles and enable defense-in-depth RLS.
ALTER TABLE rag.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.ingest_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.audit_events ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON SCHEMA rag FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA rag FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA rag FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION rag.match_chunks_semantic(extensions.vector, integer, double precision) FROM PUBLIC, anon, authenticated;

-- Trusted server-side role only; do not expose its key to browsers/mobile clients.
GRANT USAGE ON SCHEMA rag TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA rag TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA rag TO service_role;
GRANT EXECUTE ON FUNCTION rag.match_chunks_semantic(extensions.vector, integer, double precision) TO service_role;

-- Schema-scoped defaults only. Do not alter project-wide defaults in public.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA rag REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA rag GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA rag REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA rag GRANT USAGE, SELECT ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA rag REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;

-- Keyword retrieval is available as a real fallback while semantic embeddings are absent.
CREATE OR REPLACE FUNCTION rag.match_chunks_keyword(
  query_text text,
  match_count integer DEFAULT 10,
  min_rank double precision DEFAULT 0
)
RETURNS TABLE (
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
SECURITY INVOKER
SET search_path = ''
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
  ORDER BY pg_catalog.ts_rank_cd(c.search_vector, q.tsq) DESC, c.document_id, c.chunk_index
  LIMIT LEAST(GREATEST(COALESCE(match_count, 10), 1), 50);
$function$;

REVOKE ALL ON FUNCTION rag.match_chunks_keyword(text, integer, double precision) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION rag.match_chunks_keyword(text, integer, double precision) TO service_role;

COMMIT;
