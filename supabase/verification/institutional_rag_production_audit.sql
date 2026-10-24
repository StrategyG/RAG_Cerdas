-- Read-only Institutional RAG production audit queries.
-- Safe to run in Supabase SQL Editor; every statement is SELECT-only.
-- Do not paste secrets or source document content into the audit report.

-- 1) Corpus status counts.
SELECT 'rag.documents' AS object_name, ingest_status AS status, count(*)::bigint AS row_count
FROM rag.documents GROUP BY ingest_status
UNION ALL
SELECT 'institutional_rag.source_documents', status, count(*)::bigint
FROM institutional_rag.source_documents GROUP BY status
ORDER BY 1, 2;

-- 2) Chunk provenance and embedding integrity.
SELECT 'rag.chunks' AS object_name,
       count(*)::bigint AS total_chunks,
       count(*) FILTER (WHERE embedding IS NULL)::bigint AS embedding_null,
       count(*) FILTER (WHERE page_start IS NULL OR page_start < 1 OR page_end <> page_start)::bigint AS invalid_single_page_provenance,
       count(*) FILTER (WHERE coalesce(trim(text_content), '') = '')::bigint AS empty_text
FROM rag.chunks
UNION ALL
SELECT 'institutional_rag.document_chunks',
       count(*)::bigint,
       count(*) FILTER (WHERE embedding IS NULL)::bigint,
       count(*) FILTER (WHERE page_start IS NULL OR page_start < 1 OR page_end <> page_start)::bigint,
       count(*) FILTER (WHERE coalesce(trim(content), '') = '')::bigint
FROM institutional_rag.document_chunks;

-- 3) Active-generation metadata summary; this does not assume a generation exists.
SELECT id, source_name, mime_type, ingest_status,
       metadata->'page_aware_ingest'->>'active_generation' AS active_pdf_generation,
       metadata->'video_rag'->>'active_generation' AS active_video_generation,
       metadata->>'embedding_model' AS document_embedding_model
FROM rag.documents
WHERE metadata ? 'page_aware_ingest' OR metadata ? 'video_rag'
ORDER BY source_name;

-- 4) Retrieval functions, signatures, security mode, and search_path.
SELECT n.nspname AS schema_name,
       p.proname AS function_name,
       pg_get_function_identity_arguments(p.oid) AS arguments,
       pg_get_function_result(p.oid) AS return_type,
       p.prosecdef AS security_definer,
       p.proconfig AS function_settings
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname IN ('rag', 'public', 'institutional_rag')
  AND (p.proname ILIKE '%keyword%' OR p.proname ILIKE '%semantic%' OR p.proname ILIKE '%search_chunks%')
ORDER BY 1, 2;

-- 5) RLS and policies. RLS enabled with no policy is default-deny for API roles,
-- but may still indicate an incomplete intended access path.
SELECT n.nspname AS schema_name, c.relname AS table_name,
       c.relrowsecurity AS rls_enabled,
       c.relforcerowsecurity AS force_rls,
       coalesce(p.policy_count, 0) AS policy_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN (
  SELECT schemaname, tablename, count(*)::integer AS policy_count
  FROM pg_policies GROUP BY schemaname, tablename
) p ON p.schemaname = n.nspname AND p.tablename = c.relname
WHERE n.nspname IN ('rag', 'institutional_rag') AND c.relkind = 'r'
ORDER BY 1, 2;

-- 6) Explicit policies (inspect roles and predicates, not only policy names).
SELECT schemaname, tablename, policyname, roles, cmd, qual, with_check
FROM pg_policies
WHERE schemaname IN ('rag', 'institutional_rag')
ORDER BY schemaname, tablename, policyname;

-- 7) Vector extension and vector column type.
SELECT e.extname, e.extversion
FROM pg_extension e
WHERE e.extname = 'vector';

SELECT table_schema, table_name, column_name, data_type, udt_schema, udt_name
FROM information_schema.columns
WHERE table_schema IN ('rag', 'institutional_rag')
  AND column_name = 'embedding'
ORDER BY table_schema, table_name;

-- 8) Function execution access for the service RPC. Re-check if signature changes.
SELECT has_function_privilege('anon', 'public.rag_worker_match_keyword(text,integer,double precision)', 'EXECUTE') AS anon_can_execute,
       has_function_privilege('authenticated', 'public.rag_worker_match_keyword(text,integer,double precision)', 'EXECUTE') AS authenticated_can_execute,
       has_function_privilege('service_role', 'public.rag_worker_match_keyword(text,integer,double precision)', 'EXECUTE') AS service_role_can_execute;
