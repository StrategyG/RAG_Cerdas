CREATE INDEX IF NOT EXISTS audit_events_document_id_idx ON rag.audit_events (document_id);
CREATE INDEX IF NOT EXISTS audit_events_job_id_idx ON rag.audit_events (job_id);
CREATE INDEX IF NOT EXISTS ingest_jobs_document_id_idx ON rag.ingest_jobs (document_id);
