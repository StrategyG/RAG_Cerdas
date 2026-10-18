-- Read-only post-deployment verification for Institutional RAG.
-- Run in Supabase SQL Editor after worker setup or after a pilot ingestion.

SELECT
  (SELECT count(*) FROM rag.documents)::bigint AS total_documents,
  (SELECT count(*) FROM rag.documents WHERE ingest_status = 'indexed')::bigint AS indexed_documents,
  (SELECT count(*) FROM rag.chunks)::bigint AS total_chunks,
  (SELECT count(*) FROM rag.chunks WHERE embedding IS NOT NULL)::bigint AS embedded_chunks,
  (SELECT count(*) FROM rag.chunks
    WHERE page_start IS NOT NULL AND page_end = page_start)::bigint AS one_page_mapped_chunks,
  (SELECT count(*) FROM rag.chunks
    WHERE page_start IS NULL OR page_end IS NULL OR page_end <> page_start)::bigint AS unmapped_or_cross_page_chunks,
  (SELECT count(*) FROM rag.documents WHERE page_count IS NOT NULL)::bigint AS documents_with_page_count,
  (SELECT count(*) FROM rag.ingest_jobs)::bigint AS total_ingest_jobs,
  (SELECT count(*) FROM rag.ingest_jobs WHERE status IN ('queued', 'running'))::bigint AS active_ingest_jobs;

SELECT
  to_regprocedure('public.rag_worker_claim_ingest_jobs(text,integer,uuid[])') IS NOT NULL AS ingest_claim_rpc_exists,
  has_function_privilege('service_role', 'public.rag_worker_claim_ingest_jobs(text,integer,uuid[])', 'EXECUTE') AS service_role_can_claim,
  has_function_privilege('anon', 'public.rag_worker_claim_ingest_jobs(text,integer,uuid[])', 'EXECUTE') AS anon_can_claim,
  has_function_privilege('authenticated', 'public.rag_worker_claim_ingest_jobs(text,integer,uuid[])', 'EXECUTE') AS authenticated_can_claim;

SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'rag'
  AND tablename = 'ingest_jobs'
  AND indexdef ILIKE '%UNIQUE%'
ORDER BY indexname;
