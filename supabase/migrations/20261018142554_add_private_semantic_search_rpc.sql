CREATE OR REPLACE FUNCTION rag.match_chunks_semantic(
  query_embedding extensions.vector(384),
  match_count integer DEFAULT 10,
  min_similarity double precision DEFAULT 0.0
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
  similarity double precision
)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = ''
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
    AND (1 - (c.embedding OPERATOR(extensions.<=>) query_embedding)) >= min_similarity
  ORDER BY c.embedding OPERATOR(extensions.<=>) query_embedding
  LIMIT LEAST(GREATEST(COALESCE(match_count, 10), 1), 50);
$function$;

REVOKE ALL ON FUNCTION rag.match_chunks_semantic(extensions.vector, integer, double precision) FROM PUBLIC;
REVOKE ALL ON FUNCTION rag.match_chunks_semantic(extensions.vector, integer, double precision) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION rag.match_chunks_semantic(extensions.vector, integer, double precision) TO service_role;
