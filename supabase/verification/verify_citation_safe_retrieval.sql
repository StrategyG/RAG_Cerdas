-- Read-only verification for citation-safe RAG retrieval.
-- Execute through Supabase SQL Editor after applying migration
-- 20261023195626_citation_safe_retrieval_and_evaluation_index.sql.
-- PDF search results are withheld until they have valid per-page mappings. Active video results are allowed only when their transcript timestamp prefix is present.

WITH keyword_results AS (
  SELECT * FROM rag.match_chunks_keyword('ikigai', 20, 0)
),
institutional_results AS (
  SELECT * FROM institutional_rag.search_chunks('ikigai', 20)
),
semantic_results AS (
  SELECT * FROM rag.match_chunks_semantic(
    ('[' || array_to_string(array_fill(0::real, ARRAY[384]), ',') || ']')::extensions.vector,
    20,
    0
  )
)
SELECT 'rag_keyword' AS test,
       count(*)::bigint AS rows_returned,
       count(*) FILTER (
         WHERE NOT (
           (page_start IS NOT NULL AND page_start >= 1 AND page_end = page_start)
           OR text_content ~ '^\\[Video [0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)? - [0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?\\] '
         )
       )::bigint AS invalid_citations,
       count(*) > 0 AS has_searchable_evidence
FROM keyword_results
UNION ALL
SELECT 'institutional_keyword',
       count(*)::bigint,
       count(*) FILTER (
         WHERE page_start IS NULL OR page_start < 1 OR page_end <> page_start
       )::bigint,
       count(*) > 0
FROM institutional_results
UNION ALL
SELECT 'rag_semantic_zero_vector_smoke',
       count(*)::bigint,
       count(*) FILTER (
         WHERE page_start IS NULL OR page_start < 1 OR page_end <> page_start
       )::bigint,
       count(*) > 0
FROM semantic_results;

-- The index should exist; the Advisor may still call it unused until evaluation writes rows.
SELECT EXISTS (
  SELECT 1
  FROM pg_indexes
  WHERE schemaname = 'institutional_rag'
    AND tablename = 'evaluation_results'
    AND indexname = 'evaluation_results_case_id_idx'
) AS evaluation_case_fk_index_exists;

-- Current corpus repair backlog. This must decline after successful page-aware re-ingestion.
SELECT
  (SELECT count(*) FROM rag.documents) AS known_documents,
  (SELECT count(*) FROM rag.documents
   WHERE NULLIF(metadata->'page_aware_ingest'->>'active_generation', '') IS NOT NULL)
    AS page_aware_active_documents,
  (SELECT count(*)
   FROM rag.chunks AS c
   JOIN rag.documents AS d ON d.id = c.document_id
   WHERE d.mime_type IS DISTINCT FROM 'video/mp4'
     AND (c.page_start IS NULL OR c.page_start < 1 OR c.page_end <> c.page_start))
    AS legacy_or_invalid_pdf_page_chunks,
  (SELECT count(*) FROM rag.chunks WHERE embedding IS NOT NULL)
    AS chunks_with_embeddings,
  (SELECT count(*) FROM rag.ingest_jobs WHERE status IN ('queued', 'running'))
    AS queued_or_running_jobs;
