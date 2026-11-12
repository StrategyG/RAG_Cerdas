-- Source-level rights evidence is distinct from operational permission to read/process a file.
-- Bind each decision to the exact Dropbox revision and content hash. New revisions require new review.
-- Only the separate human approver role may append decisions; workers can read but never author them.
BEGIN;

CREATE TABLE im19.source_rights_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_file_id uuid NOT NULL REFERENCES im19.source_files(id),
  revision text NOT NULL CHECK(length(trim(revision)) BETWEEN 1 AND 256),
  content_hash text NOT NULL CHECK(content_hash ~ '^[a-f0-9]{64}$'),
  decision text NOT NULL CHECK(decision IN ('approve','hold','reject')),
  rights_basis text NOT NULL CHECK(rights_basis IN (
    'owner_attestation','license','public_domain','terms_permission','written_permission','other'
  )),
  license_identifier text CHECK(license_identifier IS NULL OR length(license_identifier)<=256),
  attribution text NOT NULL CHECK(length(trim(attribution)) BETWEEN 1 AND 1000),
  evidence_reference text NOT NULL CHECK(length(trim(evidence_reference)) BETWEEN 1 AND 2048),
  rationale text NOT NULL CHECK(length(trim(rationale)) BETWEEN 1 AND 2000),
  storage_allowed boolean NOT NULL DEFAULT false,
  embedding_allowed boolean NOT NULL DEFAULT false,
  derivative_notes_allowed boolean NOT NULL DEFAULT false,
  reviewer_id text NOT NULL CHECK(length(trim(reviewer_id)) BETWEEN 1 AND 128),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK(decision <> 'approve' OR (storage_allowed AND embedding_allowed))
);

CREATE INDEX source_rights_reviews_latest_idx
ON im19.source_rights_reviews(source_file_id,revision,content_hash,created_at DESC,id DESC);

COMMENT ON TABLE im19.source_rights_reviews IS
  'Append-only human decisions about storage/embedding rights, bound to a source revision and exact content hash.';
COMMENT ON COLUMN im19.source_rights_reviews.derivative_notes_allowed IS
  'Records permission for concise derivative notes; a notes-only pipeline is separate and not enabled by IM19 PDF/EPUB ingestion.';

CREATE TRIGGER source_rights_reviews_immutable
BEFORE UPDATE OR DELETE ON im19.source_rights_reviews
FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();

ALTER TABLE im19.source_rights_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE im19.source_rights_reviews FORCE ROW LEVEL SECURITY;
CREATE POLICY worker_private ON im19.source_rights_reviews
  TO im19_worker USING (true) WITH CHECK (true);
CREATE POLICY approver_rights_reviews ON im19.source_rights_reviews
  TO im19_approver USING (true) WITH CHECK (true);

GRANT SELECT ON im19.source_rights_reviews TO im19_worker;
REVOKE INSERT,UPDATE,DELETE ON im19.source_rights_reviews FROM im19_worker;
GRANT SELECT,INSERT ON im19.source_rights_reviews TO im19_approver;

CREATE FUNCTION im19.source_rights_publication_gate()
RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $$
DECLARE
  source im19.source_files%ROWTYPE;
  rights im19.source_rights_reviews%ROWTYPE;
BEGIN
  IF NEW.state='PUBLISHED' AND OLD.state<>'PUBLISHED' THEN
    SELECT * INTO source FROM im19.source_files WHERE id=NEW.source_file_id FOR SHARE;
    SELECT * INTO rights
    FROM im19.source_rights_reviews
    WHERE source_file_id=source.id
      AND revision=source.revision
      AND content_hash=source.content_hash
    ORDER BY created_at DESC,id DESC
    LIMIT 1;
    IF rights.id IS NULL
       OR rights.decision<>'approve'
       OR NOT rights.storage_allowed
       OR NOT rights.embedding_allowed THEN
      RAISE EXCEPTION 'publication source rights review gate failed';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER source_rights_gate
BEFORE UPDATE ON im19.document_versions
FOR EACH ROW EXECUTE FUNCTION im19.source_rights_publication_gate();

COMMIT;
