BEGIN;

-- Explicit deny policies protect these private tables if grants are accidentally broadened later.
CREATE POLICY deny_api_roles ON rag.documents
  FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY deny_api_roles ON rag.chunks
  FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY deny_api_roles ON rag.ingest_jobs
  FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY deny_api_roles ON rag.audit_events
  FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);

-- Enforce coherent page ranges when source-page extraction is implemented.
ALTER TABLE rag.chunks
  ADD CONSTRAINT chunks_page_range_valid
  CHECK (
    (page_start IS NULL AND page_end IS NULL)
    OR
    (page_start IS NOT NULL AND page_end IS NOT NULL
     AND page_start >= 1 AND page_end >= page_start)
  ) NOT VALID;
ALTER TABLE rag.chunks VALIDATE CONSTRAINT chunks_page_range_valid;

-- Prevent partial or mislabeled embeddings from being stored.
ALTER TABLE rag.chunks
  ADD CONSTRAINT chunks_embedding_metadata_consistent
  CHECK (
    (embedding IS NULL AND embedding_model IS NULL AND embedded_at IS NULL)
    OR
    (embedding IS NOT NULL AND NULLIF(pg_catalog.btrim(embedding_model), '') IS NOT NULL
     AND embedded_at IS NOT NULL)
  ) NOT VALID;
ALTER TABLE rag.chunks VALIDATE CONSTRAINT chunks_embedding_metadata_consistent;

COMMIT;
