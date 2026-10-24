-- ADDITIVE, private IM19 schema. No legacy rag.* changes or source data deletion.
-- Review on a backup-restored staging database first. Never applied by worker startup.
-- Requires pgvector already installed into extensions (normal Supabase configuration).
BEGIN;
CREATE SCHEMA IF NOT EXISTS im19;
REVOKE ALL ON SCHEMA im19 FROM PUBLIC;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
                 WHERE e.extname='vector' AND n.nspname='extensions') THEN
    RAISE EXCEPTION 'Install/review pgvector in extensions before this migration';
  END IF;
END $$;

CREATE TABLE im19.source_connections (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), root_path text NOT NULL DEFAULT '',
 access_scope text NOT NULL CHECK (access_scope IN ('app_folder','approved_folder')),
 cursor text, status text NOT NULL DEFAULT 'ACTIVE', last_error_code text,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE im19.source_files (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), connection_id uuid NOT NULL REFERENCES im19.source_connections(id),
 source_file_id text NOT NULL, path text NOT NULL, filename text NOT NULL, extension text NOT NULL,
 size bigint NOT NULL CHECK(size>=0), content_hash text NOT NULL CHECK(content_hash ~ '^[a-f0-9]{64}$'),
 revision text NOT NULL, modified_time timestamptz NOT NULL, discovered_at timestamptz NOT NULL,
 source_uri text NOT NULL, access_scope text NOT NULL, metadata jsonb NOT NULL,
 access_authorized boolean NOT NULL DEFAULT false, deleted boolean NOT NULL DEFAULT false,
 UNIQUE(connection_id,source_file_id)
);
CREATE INDEX ON im19.source_files(connection_id,path text_pattern_ops);
CREATE INDEX ON im19.source_files(content_hash);
CREATE TABLE im19.document_versions (
 id uuid PRIMARY KEY, source_file_id uuid NOT NULL REFERENCES im19.source_files(id),
 revision text NOT NULL, source_content_hash text NOT NULL, content_sha256 text,
 pipeline_version text NOT NULL, state text NOT NULL DEFAULT 'DISCOVERED',
 checkpoint jsonb NOT NULL DEFAULT '{}', classification jsonb, review jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), published_at timestamptz,
 UNIQUE(source_file_id,revision,pipeline_version),
 CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[a-f0-9]{64}$'),
 CHECK (state IN ('DISCOVERED','VALIDATED','DOWNLOADED','PARSED','MINED','REVIEWED','EMBEDDED','INDEXED','PUBLISHED',
 'RETRY_PENDING','AUTH_BLOCKED','OCR_REQUIRED','NEEDS_HUMAN_REVIEW','QUARANTINED','FAILED','SUPERSEDED'))
);
CREATE INDEX ON im19.document_versions(source_file_id,created_at DESC);
CREATE TABLE im19.extraction_runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), document_id uuid NOT NULL REFERENCES im19.document_versions(id),
 parser_version text NOT NULL, stats jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON im19.extraction_runs(document_id);
CREATE TABLE im19.document_pages (
 document_id uuid NOT NULL REFERENCES im19.document_versions(id), locator text NOT NULL, page_number int,
 text_content text NOT NULL, content_hash text NOT NULL, structure jsonb NOT NULL,
 ocr_used boolean NOT NULL, ocr_confidence float8 CHECK (ocr_confidence BETWEEN 0 AND 100),
 warnings jsonb NOT NULL, PRIMARY KEY(document_id,locator), CHECK(page_number IS NULL OR page_number>0)
);
CREATE TABLE im19.chunks (
 id uuid PRIMARY KEY, document_id uuid NOT NULL, locator text NOT NULL, text_content text NOT NULL,
 page_start int, page_end int, content_hash text NOT NULL,
 FOREIGN KEY(document_id,locator) REFERENCES im19.document_pages(document_id,locator),
 CHECK ((page_start>0 AND page_end=page_start) OR (page_start IS NULL AND page_end IS NULL AND locator LIKE 'epub:%'))
);
CREATE INDEX ON im19.chunks(document_id);
CREATE INDEX ON im19.chunks(content_hash);
CREATE TABLE im19.knowledge_units (
 id uuid PRIMARY KEY, document_id uuid NOT NULL REFERENCES im19.document_versions(id),
 concept text NOT NULL, category text NOT NULL, subcategory text NOT NULL, knowledge_type text NOT NULL,
 claim text NOT NULL, evidence_text text NOT NULL, locator text NOT NULL, page_start int, page_end int,
 source_chunk_ids uuid[] NOT NULL CHECK(cardinality(source_chunk_ids)>0),
 confidence float8 CHECK(confidence IS NULL), verification_status text NOT NULL DEFAULT 'NOT_EXTERNALLY_VERIFIED'
 CHECK(verification_status IN ('NOT_EXTERNALLY_VERIFIED','EXTERNALLY_SUPPORTED','DISPUTED')),
 review_status text NOT NULL DEFAULT 'pending', model_version text NOT NULL, content_hash text NOT NULL,
 FOREIGN KEY(document_id,locator) REFERENCES im19.document_pages(document_id,locator)
);
CREATE INDEX ON im19.knowledge_units(document_id);
CREATE INDEX ON im19.knowledge_units(category,subcategory);
CREATE INDEX ON im19.knowledge_units(content_hash);
CREATE TABLE im19.knowledge_claims (
 id uuid PRIMARY KEY REFERENCES im19.knowledge_units(id), claim_kind text NOT NULL,
 risk_level text NOT NULL CHECK(risk_level IN ('low','high','unknown')), verification_status text NOT NULL
);
CREATE TABLE im19.claim_evidence (
 id uuid PRIMARY KEY, claim_id uuid NOT NULL REFERENCES im19.knowledge_claims(id),
 chunk_id uuid REFERENCES im19.chunks(id), source_uri text, excerpt text NOT NULL,
 external boolean NOT NULL DEFAULT false, verified_by text, verified_at timestamptz,
 CHECK (NOT external OR (source_uri IS NOT NULL AND verified_by IS NOT NULL AND verified_at IS NOT NULL))
);
CREATE INDEX ON im19.claim_evidence(claim_id);
CREATE INDEX ON im19.claim_evidence(chunk_id);
CREATE TABLE im19.review_runs (
 id uuid PRIMARY KEY, document_id uuid NOT NULL REFERENCES im19.document_versions(id),
 model_version text NOT NULL, rubric_version text NOT NULL, result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON im19.review_runs(document_id);
CREATE TABLE im19.review_findings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), review_run_id uuid NOT NULL REFERENCES im19.review_runs(id),
 knowledge_id uuid NOT NULL REFERENCES im19.knowledge_units(id), role text NOT NULL CHECK(role IN ('A','B','C','D','E')),
 finding jsonb NOT NULL
);
CREATE INDEX ON im19.review_findings(review_run_id);
CREATE INDEX ON im19.review_findings(knowledge_id);
CREATE TABLE im19.human_approvals (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), review_run_id uuid NOT NULL REFERENCES im19.review_runs(id),
 reviewer_id text NOT NULL CHECK(length(trim(reviewer_id))>0), decision text NOT NULL CHECK(decision IN ('approve','reject')),
 rationale text NOT NULL CHECK(length(trim(rationale))>0), created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(review_run_id)
);
CREATE TABLE im19.knowledge_nodes (
 id uuid PRIMARY KEY, node_type text NOT NULL CHECK(node_type IN ('Document','Author','Concept','Claim','Evidence','Methodology','Category')),
 label text NOT NULL, document_id uuid NOT NULL REFERENCES im19.document_versions(id), metadata jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ON im19.knowledge_nodes(document_id);
CREATE TABLE im19.knowledge_relations (
 id uuid PRIMARY KEY, source_id uuid NOT NULL REFERENCES im19.knowledge_nodes(id),
 target_id uuid NOT NULL REFERENCES im19.knowledge_nodes(id),
 relation_type text NOT NULL CHECK(relation_type IN ('DEFINES','SUPPORTS','CONTRADICTS','RELATED_TO','DERIVED_FROM','APPLIES_TO')),
 evidence_id uuid NOT NULL REFERENCES im19.claim_evidence(id), model_version text NOT NULL,
 review_status text NOT NULL CHECK(review_status IN ('pending','reviewed')), context jsonb NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON im19.knowledge_relations(source_id);
CREATE INDEX ON im19.knowledge_relations(target_id);
CREATE INDEX ON im19.knowledge_relations(evidence_id);
CREATE TABLE im19.embeddings (
 chunk_id uuid PRIMARY KEY REFERENCES im19.chunks(id), model_version text NOT NULL,
 content_hash text NOT NULL, embedding extensions.vector(384) NOT NULL
);
CREATE INDEX ON im19.embeddings USING hnsw(embedding extensions.vector_cosine_ops);
CREATE TABLE im19.ingestion_jobs (
 id uuid PRIMARY KEY, document_id uuid NOT NULL UNIQUE REFERENCES im19.document_versions(id),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','retry','blocked','done','dead')),
 attempts int NOT NULL DEFAULT 0, max_attempts int NOT NULL DEFAULT 4 CHECK(max_attempts BETWEEN 1 AND 10),
 available_at timestamptz NOT NULL DEFAULT now(), lease_owner text, lease_token uuid, lease_expires_at timestamptz,
 last_error_code text, updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(attempts>=0 AND attempts<=max_attempts)
);
CREATE INDEX ON im19.ingestion_jobs(status,available_at,lease_expires_at);
CREATE TABLE im19.audit_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, document_id uuid REFERENCES im19.document_versions(id),
 event_type text NOT NULL, details jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON im19.audit_events(document_id,created_at);
CREATE FUNCTION im19.immutable_record() RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $$
BEGIN RAISE EXCEPTION 'append-only record'; END $$;
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON im19.audit_events FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();
CREATE TRIGGER approvals_immutable BEFORE UPDATE OR DELETE ON im19.human_approvals FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();
CREATE TRIGGER reviews_immutable BEFORE UPDATE OR DELETE ON im19.review_runs FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();

-- Model/source provenance must hold even for direct SQL inserts.
CREATE FUNCTION im19.unit_provenance_gate() RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $$
BEGIN
 IF cardinality(NEW.source_chunk_ids)=0 OR EXISTS(
   SELECT 1 FROM unnest(NEW.source_chunk_ids) AS x(id)
   LEFT JOIN im19.chunks c ON c.id=x.id
   WHERE c.id IS NULL OR c.document_id<>NEW.document_id OR c.locator<>NEW.locator
     OR c.page_start IS DISTINCT FROM NEW.page_start OR c.page_end IS DISTINCT FROM NEW.page_end
     OR length(trim(NEW.evidence_text))=0 OR position(NEW.evidence_text in c.text_content)=0
 ) THEN RAISE EXCEPTION 'knowledge source provenance mismatch'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER unit_provenance BEFORE INSERT OR UPDATE ON im19.knowledge_units FOR EACH ROW EXECUTE FUNCTION im19.unit_provenance_gate();

-- Publication independently enforces provenance, current source, approval and complete embeddings.
CREATE FUNCTION im19.version_gate() RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $$
DECLARE rr im19.review_runs%ROWTYPE; source im19.source_files%ROWTYPE; total_chunks bigint;
BEGIN
 IF OLD.state='SUPERSEDED' AND NEW.state<>'SUPERSEDED' THEN RAISE EXCEPTION 'superseded version is terminal'; END IF;
 IF OLD.content_sha256 IS NOT NULL AND NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256 THEN
   RAISE EXCEPTION 'source digest is immutable after download';
 END IF;
 IF NEW.state='PUBLISHED' AND OLD.state<>'PUBLISHED' THEN
   IF OLD.state<>'INDEXED' THEN RAISE EXCEPTION 'publication requires INDEXED stage'; END IF;
   SELECT * INTO source FROM im19.source_files WHERE id=NEW.source_file_id FOR SHARE;
   SELECT * INTO rr FROM im19.review_runs WHERE id=(NEW.checkpoint->>'review_run_id')::uuid;
   IF rr.id IS NULL OR rr.document_id<>NEW.id OR NEW.review IS DISTINCT FROM rr.result
      OR source.deleted OR NOT source.access_authorized OR source.revision<>NEW.revision
      OR source.content_hash<>NEW.source_content_hash OR NEW.content_sha256 IS NULL
      OR NOT COALESCE((rr.result->>'integrity_ok')::boolean,false)
      OR NEW.classification->>'status' IS DISTINCT FROM 'CLASSIFIED'
      OR NOT EXISTS(SELECT 1 FROM im19.human_approvals WHERE review_run_id=rr.id AND decision='approve') THEN
     RAISE EXCEPTION 'publication integrity/approval/source gate failed';
   END IF;
   SELECT count(*) INTO total_chunks FROM im19.chunks WHERE document_id=NEW.id;
   IF total_chunks=0 OR (SELECT count(*) FROM im19.embeddings e JOIN im19.chunks c ON c.id=e.chunk_id
      WHERE c.document_id=NEW.id AND e.content_hash=c.content_hash AND e.model_version=NEW.checkpoint->>'embedding_model')<>total_chunks THEN
     RAISE EXCEPTION 'publication embedding readback incomplete';
   END IF;
   IF NOT EXISTS(SELECT 1 FROM im19.knowledge_units WHERE document_id=NEW.id)
      OR EXISTS(SELECT 1 FROM im19.knowledge_units u WHERE u.document_id=NEW.id AND
        NOT EXISTS(SELECT 1 FROM im19.chunks c WHERE c.id=ANY(u.source_chunk_ids) AND c.document_id=NEW.id
          AND c.locator=u.locator AND position(u.evidence_text in c.text_content)>0)) THEN
     RAISE EXCEPTION 'publication knowledge provenance incomplete';
   END IF;
   NEW.published_at=now();
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER version_gate BEFORE UPDATE ON im19.document_versions FOR EACH ROW EXECUTE FUNCTION im19.version_gate();

-- No API role receives schema usage, tables, sequences or function access.
-- A deployment admin creates separate LOGIN roles and grants the following NOLOGIN roles.
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='im19_worker') THEN CREATE ROLE im19_worker NOLOGIN; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='im19_approver') THEN CREATE ROLE im19_approver NOLOGIN; END IF;
END $$;
GRANT USAGE ON SCHEMA im19, extensions TO im19_worker, im19_approver;
GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA im19 TO im19_worker;
REVOKE UPDATE ON im19.audit_events,im19.review_runs,im19.human_approvals,
 im19.document_pages,im19.chunks,im19.knowledge_units,im19.knowledge_claims,im19.claim_evidence,
 im19.review_findings,im19.knowledge_nodes,im19.knowledge_relations,im19.embeddings,im19.extraction_runs FROM im19_worker;
REVOKE INSERT,UPDATE ON im19.source_connections FROM im19_worker;
GRANT UPDATE(cursor,status,last_error_code,updated_at) ON im19.source_connections TO im19_worker;
REVOKE INSERT ON im19.human_approvals FROM im19_worker;
REVOKE INSERT,UPDATE ON im19.source_files FROM im19_worker;
GRANT INSERT(id,connection_id,source_file_id,path,filename,extension,size,content_hash,revision,modified_time,discovered_at,source_uri,access_scope,metadata)
 ON im19.source_files TO im19_worker;
GRANT UPDATE(path,filename,extension,size,content_hash,revision,modified_time,discovered_at,metadata,deleted)
 ON im19.source_files TO im19_worker;
GRANT SELECT,UPDATE(access_authorized) ON im19.source_files TO im19_approver;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA im19 TO im19_worker;
GRANT SELECT ON im19.review_runs,im19.document_versions TO im19_approver;
GRANT SELECT,INSERT ON im19.human_approvals TO im19_approver;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA im19 FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA im19 REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA im19 REVOKE ALL ON FUNCTIONS FROM PUBLIC;
DO $$ DECLARE t record; BEGIN
 FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='im19' LOOP
  EXECUTE format('ALTER TABLE im19.%I ENABLE ROW LEVEL SECURITY',t.tablename);
  EXECUTE format('ALTER TABLE im19.%I FORCE ROW LEVEL SECURITY',t.tablename);
  EXECUTE format('CREATE POLICY worker_private ON im19.%I TO im19_worker USING (true) WITH CHECK (true)',t.tablename);
 END LOOP;
END $$;
CREATE POLICY approver_access ON im19.source_files TO im19_approver USING (true) WITH CHECK (true);
CREATE POLICY approver_read ON im19.review_runs FOR SELECT TO im19_approver USING (true);
CREATE POLICY approver_versions ON im19.document_versions FOR SELECT TO im19_approver USING (true);
CREATE POLICY approver_decisions ON im19.human_approvals TO im19_approver USING (true) WITH CHECK (true);
COMMIT;
