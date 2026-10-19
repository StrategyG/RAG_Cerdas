# RAG Production Readiness Gate

Status: BLOCKED — do not label this deployment production-ready until every P0 gate passes.

## Current verified blockers (2026-10-19)

- `rag.chunks`: 25,343 rows; 0 rows with non-null embeddings.
- `rag.chunks`: 0 rows with a valid single-page mapping (`page_start = page_end`, both non-null).
- `rag.chunks`: 0 rows with a non-null `qdrant_point_id`.
- `rag.documents`: 226 discovered, 103 processing, 31 failed.
- `rag.ingest_jobs`: 0 rows.
- Existing GitHub CI success only establishes the checks it runs; it does not establish end-to-end ingestion, vector retrieval, or citation correctness.

## P0 — required before production

1. **Safe recovery and inventory**
   - Back up/export document, chunk, and job metadata before any repair.
   - Identify why 103 documents remain in `processing`; do not bulk-reset statuses until lease/worker semantics are inspected.
   - Preserve original source files and existing document IDs.
2. **Deterministic ingestion**
   - Download source bytes using the configured Dropbox integration; verify MIME type, size, and SHA-256.
   - Extract PDF text page-by-page. Detect empty/low-text pages and route them to OCR or an explicit `needs_ocr` failure state.
   - Chunk with deterministic IDs and store source path, document ID, chunk index, page start/end, content hash, parser version, and extraction status.
   - Make retries idempotent; a retry must replace/upsert the target document's chunks without duplicates.
3. **Embeddings and vector index**
   - Generate embeddings with one pinned model/version and enforce the expected vector dimension.
   - Validate finite numeric values and exact vector length before writes.
   - Persist embeddings to the configured vector store and verify row/point counts match the eligible chunks.
   - Do not mark a document indexed until all required chunks are embedded and retrievable.
4. **Retrieval and citations**
   - Run lexical retrieval and vector retrieval; fuse results with a documented ranking strategy.
   - Return source filename/path, stable document ID, page number(s), chunk ID, and a quoted supporting span.
   - If evidence is insufficient, abstain instead of inventing an answer.
5. **Quality and regression tests**
   - Build a versioned gold set of at least 30 questions across several PDFs, including unanswerable questions and page-specific questions.
   - Measure Recall@5, MRR@10, citation page accuracy, answer support rate, and abstention behavior.
   - Suggested pilot gates: Recall@5 >= 0.85, citation page accuracy >= 0.95, and 0 unsupported factual answers in the unanswerable test set. These are project acceptance targets, not measured results.
6. **Security and operations**
   - Keep Dropbox tokens and Supabase service-role secrets only in server-side secret storage.
   - Never log secrets or full private document contents.
   - Add structured job logs, bounded retries, dead-letter/error states, health checks, and alerts for stuck jobs.
   - Restrict database RPC execution to the intended service role; review RLS/grants and run Supabase security advisors.
   - Pin dependencies and test migrations against a disposable/staging database before production.

## Read-only verification SQL

Run in Supabase SQL Editor or through the approved database connector. These queries do not modify data.

```sql
select ingest_status, count(*) as documents
from rag.documents
group by ingest_status
order by ingest_status;

select
  count(*) as chunks,
  count(embedding) as embedded_chunks,
  count(*) filter (
    where page_start is not null
      and page_end is not null
      and page_start >= 1
      and page_end >= page_start
  ) as page_mapped_chunks,
  count(qdrant_point_id) as chunks_with_qdrant_point
from rag.chunks;

select status, count(*) as jobs
from rag.ingest_jobs
group by status
order by status;

select
  count(*) filter (where ingest_status = 'processing') as processing_documents,
  count(*) filter (where ingest_status = 'failed') as failed_documents,
  count(*) filter (where ingest_status = 'indexed') as indexed_documents
from rag.documents;
```

## Release rule

Do not run a full-corpus re-ingestion, execute migrations, delete chunks, or change document statuses until the pipeline code and worker/RPC contracts have been reviewed and a backup/rollback path exists. Promote only after a clean staging run, a passing end-to-end pilot, the quality gates above, and a rollback rehearsal.
