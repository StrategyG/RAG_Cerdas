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

-- New versions must enter through the controlled DISCOVERED state. The base version_gate
-- is UPDATE-only, so this INSERT guard prevents a worker from inserting PUBLISHED directly.
CREATE FUNCTION im19.document_version_insert_gate()
RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $
BEGIN
  IF NEW.state <> 'DISCOVERED' THEN
    RAISE EXCEPTION 'new document versions must begin at DISCOVERED';
  END IF;
  RETURN NEW;
END $;

CREATE TRIGGER document_version_insert_gate
BEFORE INSERT ON im19.document_versions
FOR EACH ROW EXECUTE FUNCTION im19.document_version_insert_gate();

CREATE FUNCTION im19.source_rights_publication_gate()
RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $
DECLARE
  rights im19.source_rights_reviews%ROWTYPE;
BEGIN
  IF NEW.state='PUBLISHED' AND OLD.state<>'PUBLISHED' THEN
    SELECT * INTO rights
    FROM im19.source_rights_reviews
    WHERE source_file_id=NEW.source_file_id
      AND revision=NEW.revision
      AND content_hash=NEW.source_content_hash
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
END $;

CREATE TRIGGER source_rights_gate
BEFORE UPDATE ON im19.document_versions
FOR EACH ROW EXECUTE FUNCTION im19.source_rights_publication_gate();

-- A later hold/reject immediately removes an already-published exact version from retrieval.
-- This quarantines the version but does not erase stored text/embeddings; see the rights runbook.
CREATE FUNCTION im19.source_rights_revoke_publication()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $
BEGIN
  IF NEW.decision <> 'approve' OR NOT NEW.storage_allowed OR NOT NEW.embedding_allowed THEN
    WITH quarantined AS (
      UPDATE im19.document_versions
      SET state='QUARANTINED',
          checkpoint=checkpoint || jsonb_build_object('error_code','SOURCE_RIGHTS_REVIEW_REVOKED')
      WHERE source_file_id=NEW.source_file_id
        AND revision=NEW.revision
        AND source_content_hash=NEW.content_hash
        AND state='PUBLISHED'
      RETURNING id
    )
    INSERT INTO im19.audit_events(document_id,event_type,details)
    SELECT id,'source_rights_publication_quarantined',
           jsonb_build_object('rights_review_id',NEW.id,'decision',NEW.decision)
    FROM quarantined;
  END IF;
  RETURN NEW;
END $;

CREATE TRIGGER source_rights_revoke_published
AFTER INSERT ON im19.source_rights_reviews
FOR EACH ROW EXECUTE FUNCTION im19.source_rights_revoke_publication();

REVOKE ALL ON FUNCTION im19.source_rights_revoke_publication() FROM PUBLIC;

COMMIT;
