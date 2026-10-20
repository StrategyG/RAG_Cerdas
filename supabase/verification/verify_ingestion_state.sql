-- Read-only post-deployment verification for versioned, append-only Institutional RAG.
-- Legacy rows are intentionally retained. For release readiness, inspect ACTIVE
-- generation counts separately from total retained/legacy rows.

SELECT
  (SELECT count(*) FROM rag.documents)::bigint AS total_documents,
  (SELECT count(*) FROM rag.documents WHERE ingest_status = 'indexed')::bigint AS indexed_documents,
  (SELECT count(*) FROM rag.documents
    WHERE content_sha256 IS NOT NULL)::bigint AS documents_with_source_hash,
  (SELECT count(*) FROM rag.documents
    WHERE page_count IS NOT NULL)::bigint AS documents_with_active_page_count,
  (SELECT count(*) FROM rag.documents
    WHERE NULLIF(metadata->'page_aware_ingest'->>'active_generation', '') IS NOT NULL)::bigint
    AS documents_with_active_generation,
  (SELECT count(*) FROM rag.documents
    WHERE NULLIF(metadata->'page_aware_ingest'->>'pending_generation', '') IS NOT NULL)::bigint
    AS documents_with_pending_generation,
  (SELECT count(*) FROM rag.chunks)::bigint AS total_retained_chunks,
  (SELECT count(*) FROM rag.chunks WHERE metadata->>'ingest_generation' IS NULL)::bigint
    AS legacy_chunks_retained,
  (SELECT count(*) FROM rag.chunks
    WHERE metadata->>'ingest_generation' IS NOT NULL)::bigint AS versioned_generation_chunks,
  (SELECT count(*) FROM rag.chunks
    WHERE embedding IS NOT NULL)::bigint AS total_chunks_with_embedding,
  (SELECT count(*) FROM rag.chunks c
    JOIN rag.documents d ON d.id = c.document_id
    WHERE NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NOT NULL
      AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'active_generation')::bigint
    AS active_generation_chunks,
  (SELECT count(*) FROM rag.chunks c
    JOIN rag.documents d ON d.id = c.document_id
    WHERE NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NOT NULL
      AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'active_generation'
      AND c.embedding IS NOT NULL
      AND c.embedding_model = 'intfloat/multilingual-e5-small'
      AND c.embedded_at IS NOT NULL
      AND c.page_start IS NOT NULL
      AND c.page_end = c.page_start)::bigint
    AS active_generation_chunks_fully_embedded_and_mapped,
  (SELECT count(*) FROM rag.chunks c
    JOIN rag.documents d ON d.id = c.document_id
    WHERE NULLIF(d.metadata->'page_aware_ingest'->>'pending_generation', '') IS NOT NULL
      AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'pending_generation')::bigint
    AS pending_generation_chunks,
  (SELECT count(*) FROM rag.chunks c
    JOIN rag.documents d ON d.id = c.document_id
    WHERE NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NOT NULL
      AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'active_generation'
      AND (c.page_start IS NULL OR c.page_end IS NULL OR c.page_end <> c.page_start))::bigint
    AS active_generation_unmapped_or_cross_page_chunks,
  (SELECT count(*) FROM rag.ingest_jobs)::bigint AS total_ingest_jobs,
  (SELECT count(*) FROM rag.ingest_jobs WHERE status IN ('queued', 'running'))::bigint AS active_ingest_jobs;

-- Worker RPC existence and service-only grants. A migration must not expose
-- privileged worker routines to anon/authenticated clients.
SELECT
  to_regprocedure('public.rag_worker_stage_document_generation(uuid,integer,jsonb,text)') IS NOT NULL
    AS append_only_stage_rpc_exists,
  to_regprocedure('public.rag_worker_replace_document_chunks(uuid,integer,jsonb)') IS NULL
    AS old_destructive_replace_rpc_retired,
  has_function_privilege('service_role', 'public.rag_worker_stage_document_generation(uuid,integer,jsonb,text)', 'EXECUTE')
    AS service_role_can_stage,
  has_function_privilege('anon', 'public.rag_worker_stage_document_generation(uuid,integer,jsonb,text)', 'EXECUTE')
    AS anon_cannot_stage,
  has_function_privilege('authenticated', 'public.rag_worker_stage_document_generation(uuid,integer,jsonb,text)', 'EXECUTE')
    AS authenticated_cannot_stage,
  has_function_privilege('service_role', 'public.rag_worker_claim_ingest_jobs(text,integer,uuid[])', 'EXECUTE')
    AS service_role_can_claim,
  has_function_privilege('anon', 'public.rag_worker_claim_ingest_jobs(text,integer,uuid[])', 'EXECUTE')
    AS anon_cannot_claim,
  has_function_privilege('authenticated', 'public.rag_worker_claim_ingest_jobs(text,integer,uuid[])', 'EXECUTE')
    AS authenticated_cannot_claim;

-- Active-generation retrieval smoke test (the result may be empty before ingestion).
-- After a pilot is indexed, this should return only page-mapped chunks from active generations.
SELECT
  d.source_name,
  d.page_count,
  d.metadata->'page_aware_ingest'->>'active_generation' AS active_generation,
  count(c.id)::bigint AS active_chunks,
  count(c.id) FILTER (WHERE c.embedding IS NOT NULL)::bigint AS embedded_chunks,
  count(c.id) FILTER (WHERE c.page_start IS NULL OR c.page_end <> c.page_start)::bigint AS invalid_page_mappings
FROM rag.documents d
LEFT JOIN rag.chunks c
  ON c.document_id = d.id
 AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'active_generation'
WHERE NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NOT NULL
GROUP BY d.id, d.source_name, d.page_count, d.metadata->'page_aware_ingest'->>'active_generation'
ORDER BY d.source_name;
