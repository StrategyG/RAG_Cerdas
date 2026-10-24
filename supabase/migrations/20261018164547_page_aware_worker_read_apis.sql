CREATE OR REPLACE FUNCTION public.rag_worker_list_documents_page(
  p_limit integer DEFAULT 100,
  p_offset integer DEFAULT 0,
  p_status text DEFAULT 'discovered'
)
RETURNS TABLE (
  document_id uuid,
  source_path text,
  source_name text,
  content_sha256 text,
  file_size_bytes bigint,
  page_count integer,
  ingest_status text,
  metadata jsonb
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF p_status NOT IN ('all', 'discovered', 'queued', 'processing', 'indexed', 'failed', 'skipped') THEN
    RAISE EXCEPTION 'Invalid ingest status: %', p_status USING ERRCODE = '22023';
  END IF;

  RETURN QUERY
  SELECT d.id, d.source_path, d.source_name, d.content_sha256,
         d.file_size_bytes, d.page_count, d.ingest_status, d.metadata
  FROM rag.documents AS d
  WHERE p_status = 'all' OR d.ingest_status = p_status
  ORDER BY d.updated_at ASC, d.created_at ASC, d.id ASC
  LIMIT LEAST(GREATEST(COALESCE(p_limit, 100), 1), 200)
  OFFSET GREATEST(COALESCE(p_offset, 0), 0);
END;
$function$;

CREATE OR REPLACE FUNCTION public.rag_worker_get_document(p_document_id uuid)
RETURNS TABLE (
  document_id uuid,
  source_path text,
  source_name text,
  content_sha256 text,
  file_size_bytes bigint,
  page_count integer,
  ingest_status text,
  metadata jsonb
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $function$
  SELECT d.id, d.source_path, d.source_name, d.content_sha256,
         d.file_size_bytes, d.page_count, d.ingest_status, d.metadata
  FROM rag.documents AS d
  WHERE d.id = p_document_id;
$function$;

CREATE OR REPLACE FUNCTION public.rag_worker_list_chunks(
  p_document_id uuid,
  p_only_unembedded boolean DEFAULT true,
  p_limit integer DEFAULT 2000
)
RETURNS TABLE (
  chunk_id uuid,
  document_id uuid,
  chunk_index integer,
  page_start integer,
  page_end integer,
  text_content text,
  token_count integer,
  content_sha256 text,
  embedding_model text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF p_document_id IS NULL THEN
    RAISE EXCEPTION 'p_document_id is required' USING ERRCODE = '22023';
  END IF;

  RETURN QUERY
  SELECT c.id, c.document_id, c.chunk_index, c.page_start, c.page_end,
         c.text_content, c.token_count, c.content_sha256, c.embedding_model
  FROM rag.chunks AS c
  WHERE c.document_id = p_document_id
    AND (NOT COALESCE(p_only_unembedded, true) OR c.embedding IS NULL)
  ORDER BY c.chunk_index
  LIMIT LEAST(GREATEST(COALESCE(p_limit, 2000), 1), 10000);
END;
$function$;

CREATE OR REPLACE FUNCTION public.rag_worker_set_document_error(
  p_document_id uuid,
  p_error text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  UPDATE rag.documents AS d
  SET ingest_status = 'failed',
      ingest_error = left(COALESCE(p_error, 'Unspecified ingestion error'), 4000),
      updated_at = now(),
      indexed_at = NULL
  WHERE d.id = p_document_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Unknown document_id: %', p_document_id USING ERRCODE = '23503';
  END IF;

  INSERT INTO rag.audit_events (event_type, document_id, details)
  VALUES ('page_aware_ingest_failed', p_document_id, jsonb_build_object('error', left(COALESCE(p_error, 'Unspecified ingestion error'), 4000)));

  RETURN jsonb_build_object('document_id', p_document_id, 'status', 'failed');
END;
$function$;

REVOKE ALL ON FUNCTION public.rag_worker_list_documents_page(integer, integer, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rag_worker_get_document(uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rag_worker_list_chunks(uuid, boolean, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rag_worker_set_document_error(uuid, text) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.rag_worker_list_documents_page(integer, integer, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.rag_worker_get_document(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.rag_worker_list_chunks(uuid, boolean, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.rag_worker_set_document_error(uuid, text) TO service_role;
