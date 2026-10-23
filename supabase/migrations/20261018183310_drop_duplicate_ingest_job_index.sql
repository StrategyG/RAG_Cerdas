-- The original page-aware worker migration already provides an equivalent partial unique index.
-- Remove the duplicate index introduced during worker-queue hardening; keep the original index.
DROP INDEX IF EXISTS rag.ingest_jobs_one_active_job_per_document_type;
