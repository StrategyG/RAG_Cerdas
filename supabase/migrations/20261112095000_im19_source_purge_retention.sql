-- Revision-bound, separately approved IM19 purge.
-- Additive only: apply to disposable/staging after review. Does not delete Dropbox originals
-- and does not promise immediate erasure from retained backups.
BEGIN;

-- Revalidate reviewer role privileges at every human decision, not only at registration time.
CREATE OR REPLACE FUNCTION im19.assert_registered_reviewer()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=''
AS $
DECLARE
  principal_name name := session_user;
  principal_oid oid;
  expected_reviewer_id text;
BEGIN
  principal_oid := pg_catalog.to_regrole(session_user::text)::oid;

  SELECT i.reviewer_id
  INTO expected_reviewer_id
  FROM im19_security.reviewer_identities i
  JOIN pg_catalog.pg_roles r ON r.oid=i.database_role_oid
  WHERE i.database_role_oid=principal_oid
    AND i.database_login_role=principal_name
    AND r.rolcanlogin AND r.rolinherit
    AND NOT r.rolsuper AND NOT r.rolbypassrls
    AND NOT r.rolcreaterole AND NOT r.rolcreatedb AND NOT r.rolreplication
    AND pg_catalog.pg_has_role(session_user,'im19_approver','MEMBER')
    AND NOT pg_catalog.pg_has_role(session_user,'im19_worker','MEMBER')
    AND EXISTS (
      SELECT 1 FROM pg_catalog.pg_auth_members m
      WHERE m.member=principal_oid
        AND m.roleid=pg_catalog.to_regrole('im19_approver')::oid
        AND NOT m.admin_option
    )
    AND NOT EXISTS (
      SELECT 1 FROM im19_security.reviewer_identity_revocations x
      WHERE x.database_role_oid=i.database_role_oid
    );

  IF expected_reviewer_id IS NULL THEN
    RAISE EXCEPTION 'reviewer principal is not registered, active, or least-privileged'
      USING ERRCODE='42501';
  END IF;
  IF NEW.reviewer_id IS DISTINCT FROM expected_reviewer_id THEN
    RAISE EXCEPTION 'reviewer_id does not match authenticated database principal'
      USING ERRCODE='42501';
  END IF;
  NEW.created_at := pg_catalog.clock_timestamp();
  RETURN NEW;
END
$;

CREATE TABLE im19_security.worker_storage_nodes (
  database_role_oid oid PRIMARY KEY CHECK(database_role_oid > 0),
  database_login_role name NOT NULL UNIQUE,
  storage_node_id text NOT NULL UNIQUE CHECK(length(trim(storage_node_id)) BETWEEN 1 AND 128),
  registered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  registered_by name NOT NULL DEFAULT session_user
);
CREATE TABLE im19_security.worker_storage_node_revocations (
  database_role_oid oid PRIMARY KEY REFERENCES im19_security.worker_storage_nodes(database_role_oid),
  reason text NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 2000),
  revoked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  revoked_by name NOT NULL DEFAULT session_user
);

CREATE TABLE im19_security.purge_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_file_id uuid NOT NULL REFERENCES im19.source_files(id),
  document_version_id uuid NOT NULL UNIQUE REFERENCES im19.document_versions(id),
  revision text NOT NULL CHECK(length(trim(revision)) BETWEEN 1 AND 256),
  content_hash text NOT NULL CHECK(content_hash ~ '^[a-f0-9]{64}$'),
  reason_code text NOT NULL CHECK(reason_code IN (
    'rights_withdrawal','retention_expiry','owner_request','policy_violation','legal_requirement'
  )),
  retention_policy_ref text NOT NULL CHECK(length(trim(retention_policy_ref)) BETWEEN 1 AND 512),
  legal_hold_check_ref text NOT NULL CHECK(length(trim(legal_hold_check_ref)) BETWEEN 1 AND 512),
  legal_hold_cleared boolean NOT NULL CHECK(legal_hold_cleared),
  requester_reviewer_id text NOT NULL,
  requester_role_oid oid NOT NULL,
  requester_login name NOT NULL,
  requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  status text NOT NULL DEFAULT 'requested' CHECK(status IN (
    'requested','previewed','approved','database_purged','completed'
  )),
  database_purged_at timestamptz,
  completed_at timestamptz
);
CREATE TABLE im19_security.purge_request_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  request_id uuid NOT NULL REFERENCES im19_security.purge_requests(id),
  event_type text NOT NULL,
  status text NOT NULL,
  actor_login name NOT NULL DEFAULT session_user,
  actor_reviewer_id text,
  details jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE im19_security.purge_previews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id uuid NOT NULL REFERENCES im19_security.purge_requests(id),
  document_version_id uuid NOT NULL REFERENCES im19.document_versions(id),
  artifact_counts jsonb NOT NULL,
  previewer_reviewer_id text NOT NULL,
  previewer_role_oid oid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX purge_previews_latest_idx ON im19_security.purge_previews(request_id,created_at DESC,id DESC);
CREATE TABLE im19_security.purge_approvals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id uuid NOT NULL REFERENCES im19_security.purge_requests(id),
  preview_id uuid NOT NULL REFERENCES im19_security.purge_previews(id),
  approver_reviewer_id text NOT NULL,
  approver_role_oid oid NOT NULL,
  approver_login name NOT NULL,
  approval_ref text NOT NULL CHECK(length(trim(approval_ref)) BETWEEN 1 AND 512),
  approved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(request_id,preview_id)
);
CREATE TABLE im19_security.purge_storage_targets (
  request_id uuid NOT NULL REFERENCES im19_security.purge_requests(id),
  storage_node_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(request_id,storage_node_id)
);
CREATE TABLE im19_security.purge_storage_receipts (
  request_id uuid NOT NULL,
  storage_node_id text NOT NULL,
  document_version_id uuid NOT NULL REFERENCES im19.document_versions(id),
  blob_files_removed integer NOT NULL CHECK(blob_files_removed>=0),
  temp_files_removed integer NOT NULL CHECK(temp_files_removed>=0),
  files_verified_absent boolean NOT NULL CHECK(files_verified_absent),
  worker_login name NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(request_id,storage_node_id),
  FOREIGN KEY(request_id,storage_node_id)
    REFERENCES im19_security.purge_storage_targets(request_id,storage_node_id)
);
CREATE TABLE im19_security.purge_execution_authorizations (
  transaction_id bigint NOT NULL,
  document_version_id uuid NOT NULL,
  request_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(transaction_id,document_version_id,request_id)
);
CREATE TABLE im19_security.purge_tombstones (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id uuid NOT NULL UNIQUE REFERENCES im19_security.purge_requests(id),
  source_file_id uuid NOT NULL REFERENCES im19.source_files(id),
  document_version_id uuid NOT NULL UNIQUE REFERENCES im19.document_versions(id),
  revision text NOT NULL,
  content_hash text NOT NULL CHECK(content_hash ~ '^[a-f0-9]{64}$'),
  reason_code text NOT NULL,
  retention_policy_ref text NOT NULL,
  legal_hold_check_ref text NOT NULL,
  requester_reviewer_id text NOT NULL,
  approver_reviewer_id text NOT NULL,
  deleted_artifact_counts jsonb NOT NULL,
  database_purged_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

COMMENT ON TABLE im19_security.worker_storage_nodes IS
  'One dedicated worker LOGIN per distinct durable local blob storage root; register every active root before ingestion.';
COMMENT ON TABLE im19_security.purge_requests IS
  'Revision/hash-bound purge workflow. Requester and approver are distinct registered reviewer principals.';
COMMENT ON TABLE im19_security.purge_tombstones IS
  'Content-free deletion evidence. Source text, chunks, claims, embeddings, and graph payloads are not retained here.';

CREATE FUNCTION im19_security.worker_storage_node_insert_gate()
RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $$
DECLARE resolved_oid oid;
BEGIN
  IF EXISTS (SELECT 1 FROM im19_security.purge_requests p WHERE p.status<>'completed') THEN
    RAISE EXCEPTION 'worker storage inventory cannot change while a purge is active';
  END IF;
  resolved_oid := pg_catalog.to_regrole(NEW.database_login_role::text)::oid;
  IF resolved_oid IS NULL OR resolved_oid IS DISTINCT FROM NEW.database_role_oid THEN
    RAISE EXCEPTION 'worker storage role name/OID mismatch';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles r
    WHERE r.rolname=NEW.database_login_role AND r.rolcanlogin AND r.rolinherit
      AND NOT r.rolsuper AND NOT r.rolbypassrls AND NOT r.rolcreaterole
      AND NOT r.rolcreatedb AND NOT r.rolreplication
  ) THEN RAISE EXCEPTION 'storage node requires a least-privileged LOGIN role'; END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_auth_members m
    WHERE m.member=NEW.database_role_oid
      AND m.roleid=pg_catalog.to_regrole('im19_worker')::oid AND NOT m.admin_option
  ) THEN RAISE EXCEPTION 'storage node LOGIN must be a direct im19_worker member without admin option'; END IF;
  IF pg_catalog.pg_has_role(NEW.database_login_role,'im19_approver','MEMBER') THEN
    RAISE EXCEPTION 'storage node LOGIN must not inherit im19_approver';
  END IF;
  NEW.registered_at := pg_catalog.clock_timestamp();
  NEW.registered_by := session_user;
  RETURN NEW;
END $$;
CREATE TRIGGER worker_storage_node_insert_gate BEFORE INSERT ON im19_security.worker_storage_nodes
FOR EACH ROW EXECUTE FUNCTION im19_security.worker_storage_node_insert_gate();
CREATE TRIGGER worker_storage_nodes_immutable BEFORE UPDATE OR DELETE ON im19_security.worker_storage_nodes
FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();

CREATE FUNCTION im19_security.worker_storage_node_revocation_gate()
RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM im19_security.purge_storage_targets t
    JOIN im19_security.purge_requests p ON p.id=t.request_id
    WHERE t.storage_node_id=(
      SELECT n.storage_node_id FROM im19_security.worker_storage_nodes n
      WHERE n.database_role_oid=NEW.database_role_oid
    )
      AND p.status<>'completed'
      AND NOT EXISTS (
        SELECT 1 FROM im19_security.purge_storage_receipts r
        WHERE r.request_id=t.request_id AND r.storage_node_id=t.storage_node_id
      )
  ) THEN RAISE EXCEPTION 'storage node cannot be revoked while a purge receipt is outstanding'; END IF;
  NEW.revoked_at := pg_catalog.clock_timestamp();
  NEW.revoked_by := session_user;
  RETURN NEW;
END $$;
CREATE TRIGGER worker_storage_node_revocation_gate BEFORE INSERT ON im19_security.worker_storage_node_revocations
FOR EACH ROW EXECUTE FUNCTION im19_security.worker_storage_node_revocation_gate();
CREATE TRIGGER worker_storage_node_revocations_immutable BEFORE UPDATE OR DELETE ON im19_security.worker_storage_node_revocations
FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();

CREATE TRIGGER purge_request_events_immutable BEFORE UPDATE OR DELETE ON im19_security.purge_request_events
FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();
CREATE TRIGGER purge_previews_immutable BEFORE UPDATE OR DELETE ON im19_security.purge_previews
FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();
CREATE TRIGGER purge_approvals_immutable BEFORE UPDATE OR DELETE ON im19_security.purge_approvals
FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();
CREATE TRIGGER purge_storage_targets_immutable BEFORE UPDATE OR DELETE ON im19_security.purge_storage_targets
FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();
CREATE TRIGGER purge_storage_receipts_immutable BEFORE UPDATE OR DELETE ON im19_security.purge_storage_receipts
FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();
CREATE TRIGGER purge_tombstones_immutable BEFORE UPDATE OR DELETE ON im19_security.purge_tombstones
FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();

CREATE FUNCTION im19_security.current_reviewer()
RETURNS TABLE(database_role_oid oid,database_login_role name,reviewer_id text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE principal_oid oid;
BEGIN
  principal_oid := pg_catalog.to_regrole(session_user::text)::oid;
  RETURN QUERY
  SELECT i.database_role_oid,i.database_login_role,i.reviewer_id
  FROM im19_security.reviewer_identities i
  JOIN pg_catalog.pg_roles r ON r.oid=i.database_role_oid
  WHERE i.database_role_oid=principal_oid AND i.database_login_role=session_user
    AND r.rolcanlogin AND r.rolinherit AND NOT r.rolsuper AND NOT r.rolbypassrls
    AND NOT r.rolcreaterole AND NOT r.rolcreatedb AND NOT r.rolreplication
    AND pg_catalog.pg_has_role(session_user,'im19_approver','MEMBER')
    AND NOT pg_catalog.pg_has_role(session_user,'im19_worker','MEMBER')
    AND NOT EXISTS (
      SELECT 1 FROM im19_security.reviewer_identity_revocations x
      WHERE x.database_role_oid=i.database_role_oid
    );
  IF NOT FOUND THEN
    RAISE EXCEPTION 'authenticated reviewer is not registered, active, or least-privileged'
      USING ERRCODE='42501';
  END IF;
END $$;

CREATE FUNCTION im19_security.current_storage_node()
RETURNS TABLE(database_role_oid oid,database_login_role name,storage_node_id text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE principal_oid oid;
BEGIN
  principal_oid := pg_catalog.to_regrole(session_user::text)::oid;
  RETURN QUERY
  SELECT n.database_role_oid,n.database_login_role,n.storage_node_id
  FROM im19_security.worker_storage_nodes n
  JOIN pg_catalog.pg_roles r ON r.oid=n.database_role_oid
  WHERE n.database_role_oid=principal_oid AND n.database_login_role=session_user
    AND r.rolcanlogin AND r.rolinherit AND NOT r.rolsuper AND NOT r.rolbypassrls
    AND NOT r.rolcreaterole AND NOT r.rolcreatedb AND NOT r.rolreplication
    AND pg_catalog.pg_has_role(session_user,'im19_worker','MEMBER')
    AND NOT pg_catalog.pg_has_role(session_user,'im19_approver','MEMBER')
    AND NOT EXISTS (
      SELECT 1 FROM im19_security.worker_storage_node_revocations x
      WHERE x.database_role_oid=n.database_role_oid
    );
  IF NOT FOUND THEN
    RAISE EXCEPTION 'worker storage node is not registered, active, or least-privileged'
      USING ERRCODE='42501';
  END IF;
END $$;

CREATE FUNCTION im19_security.purge_inventory(p_document_version_id uuid)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$
  SELECT pg_catalog.jsonb_build_object(
    'extraction_runs',(SELECT count(*) FROM im19.extraction_runs WHERE document_id=p_document_version_id),
    'document_pages',(SELECT count(*) FROM im19.document_pages WHERE document_id=p_document_version_id),
    'chunks',(SELECT count(*) FROM im19.chunks WHERE document_id=p_document_version_id),
    'embeddings',(SELECT count(*) FROM im19.embeddings e JOIN im19.chunks c ON c.id=e.chunk_id WHERE c.document_id=p_document_version_id),
    'knowledge_units',(SELECT count(*) FROM im19.knowledge_units WHERE document_id=p_document_version_id),
    'knowledge_claims',(SELECT count(*) FROM im19.knowledge_claims k JOIN im19.knowledge_units u ON u.id=k.id WHERE u.document_id=p_document_version_id),
    'claim_evidence',(SELECT count(*) FROM im19.claim_evidence e WHERE e.claim_id IN (SELECT id FROM im19.knowledge_units WHERE document_id=p_document_version_id) OR e.chunk_id IN (SELECT id FROM im19.chunks WHERE document_id=p_document_version_id)),
    'review_runs',(SELECT count(*) FROM im19.review_runs WHERE document_id=p_document_version_id),
    'review_findings',(SELECT count(*) FROM im19.review_findings f WHERE f.review_run_id IN (SELECT id FROM im19.review_runs WHERE document_id=p_document_version_id) OR f.knowledge_id IN (SELECT id FROM im19.knowledge_units WHERE document_id=p_document_version_id)),
    'human_approvals',(SELECT count(*) FROM im19.human_approvals a JOIN im19.review_runs r ON r.id=a.review_run_id WHERE r.document_id=p_document_version_id),
    'knowledge_nodes',(SELECT count(*) FROM im19.knowledge_nodes WHERE document_id=p_document_version_id),
    'knowledge_relations',(
      SELECT count(*) FROM im19.knowledge_relations r
      WHERE r.source_id IN (SELECT id FROM im19.knowledge_nodes WHERE document_id=p_document_version_id)
         OR r.target_id IN (SELECT id FROM im19.knowledge_nodes WHERE document_id=p_document_version_id)
         OR r.evidence_id IN (
           SELECT e.id FROM im19.claim_evidence e
           WHERE e.claim_id IN (SELECT id FROM im19.knowledge_units WHERE document_id=p_document_version_id)
              OR e.chunk_id IN (SELECT id FROM im19.chunks WHERE document_id=p_document_version_id)
         )
    ),
    'ingestion_jobs',(SELECT count(*) FROM im19.ingestion_jobs WHERE document_id=p_document_version_id)
  )
$$;

CREATE FUNCTION im19.request_source_purge(
  p_document_version_id uuid,p_reason_code text,p_retention_policy_ref text,
  p_legal_hold_check_ref text,p_legal_hold_cleared boolean
)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE
  reviewer record;
  version_row record;
  request_id uuid := pg_catalog.gen_random_uuid();
  storage_node_count bigint;
BEGIN
  SELECT * INTO reviewer FROM im19_security.current_reviewer();
  IF p_legal_hold_cleared IS DISTINCT FROM true OR p_legal_hold_check_ref IS NULL
     OR length(pg_catalog.btrim(p_legal_hold_check_ref))=0 THEN
    RAISE EXCEPTION 'purge requires an affirmative, referenced legal-hold check';
  END IF;

  PERFORM 1 FROM im19.ingestion_jobs j WHERE j.document_id=p_document_version_id FOR UPDATE;
  SELECT v.id,v.source_file_id,v.revision,v.source_content_hash,v.state
  INTO version_row FROM im19.document_versions v
  WHERE v.id=p_document_version_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'document version not found'; END IF;

  PERFORM 1 FROM im19.source_files f WHERE f.id=version_row.source_file_id FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'source file not found'; END IF;
  IF EXISTS (SELECT 1 FROM im19_security.purge_requests p WHERE p.document_version_id=p_document_version_id) THEN
    RAISE EXCEPTION 'a purge request already exists for this exact document version';
  END IF;

  SELECT count(*) INTO storage_node_count
  FROM im19_security.worker_storage_nodes n
  WHERE NOT EXISTS (
    SELECT 1 FROM im19_security.worker_storage_node_revocations x WHERE x.database_role_oid=n.database_role_oid
  );
  IF storage_node_count=0 THEN
    RAISE EXCEPTION 'purge blocked: register every durable worker storage node first';
  END IF;

  INSERT INTO im19_security.purge_requests(
    id,source_file_id,document_version_id,revision,content_hash,reason_code,
    retention_policy_ref,legal_hold_check_ref,legal_hold_cleared,
    requester_reviewer_id,requester_role_oid,requester_login
  ) VALUES (
    request_id,version_row.source_file_id,version_row.id,version_row.revision,
    version_row.source_content_hash,p_reason_code,p_retention_policy_ref,
    p_legal_hold_check_ref,true,reviewer.reviewer_id,reviewer.database_role_oid,
    reviewer.database_login_role
  );

  INSERT INTO im19_security.purge_storage_targets(request_id,storage_node_id)
  SELECT request_id,n.storage_node_id FROM im19_security.worker_storage_nodes n
  WHERE NOT EXISTS (
    SELECT 1 FROM im19_security.worker_storage_node_revocations x WHERE x.database_role_oid=n.database_role_oid
  );

  IF version_row.state NOT IN ('SUPERSEDED','QUARANTINED') THEN
    UPDATE im19.document_versions
    SET state='QUARANTINED',
        checkpoint=checkpoint || pg_catalog.jsonb_build_object(
          'error_code','PURGE_PENDING','purge_request_id',request_id::text
        )
    WHERE id=p_document_version_id;
  END IF;

  UPDATE im19.ingestion_jobs
  SET status='blocked',last_error_code='PURGE_PENDING',
      lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,updated_at=pg_catalog.clock_timestamp()
  WHERE document_id=p_document_version_id;

  INSERT INTO im19_security.purge_request_events(
    request_id,event_type,status,actor_login,actor_reviewer_id,details
  ) VALUES (
    request_id,'purge_requested','requested',reviewer.database_login_role,
    reviewer.reviewer_id,pg_catalog.jsonb_build_object('reason_code',p_reason_code)
  );
  INSERT INTO im19.audit_events(document_id,event_type,details)
  VALUES (p_document_version_id,'source_version_purge_requested',
    pg_catalog.jsonb_build_object('purge_request_id',request_id,'reason_code',p_reason_code));
  RETURN request_id;
END $$;

CREATE FUNCTION im19.preview_source_purge(p_request_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE
  reviewer record;
  purge_row record;
  counts jsonb;
  preview_id uuid := pg_catalog.gen_random_uuid();
BEGIN
  SELECT * INTO reviewer FROM im19_security.current_reviewer();
  SELECT * INTO purge_row FROM im19_security.purge_requests WHERE id=p_request_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'purge request not found'; END IF;
  IF purge_row.status NOT IN ('requested','previewed') THEN
    RAISE EXCEPTION 'purge request is not available for a fresh preview';
  END IF;
  counts := im19_security.purge_inventory(purge_row.document_version_id);
  INSERT INTO im19_security.purge_previews(
    id,request_id,document_version_id,artifact_counts,previewer_reviewer_id,previewer_role_oid
  ) VALUES (preview_id,p_request_id,purge_row.document_version_id,counts,reviewer.reviewer_id,reviewer.database_role_oid);
  UPDATE im19_security.purge_requests SET status='previewed' WHERE id=p_request_id;
  INSERT INTO im19_security.purge_request_events(
    request_id,event_type,status,actor_login,actor_reviewer_id,details
  ) VALUES (
    p_request_id,'purge_dry_run_completed','previewed',reviewer.database_login_role,
    reviewer.reviewer_id,pg_catalog.jsonb_build_object('preview_id',preview_id,'artifact_counts',counts)
  );
  RETURN pg_catalog.jsonb_build_object(
    'status','previewed','request_id',p_request_id,'preview_id',preview_id,
    'document_version_id',purge_row.document_version_id,'artifact_counts',counts
  );
END $$;

CREATE FUNCTION im19.approve_source_purge(p_request_id uuid,p_approval_ref text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE
  reviewer record;
  purge_row record;
  preview_row record;
  approval_id uuid := pg_catalog.gen_random_uuid();
BEGIN
  SELECT * INTO reviewer FROM im19_security.current_reviewer();
  SELECT * INTO purge_row FROM im19_security.purge_requests WHERE id=p_request_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'purge request not found'; END IF;
  IF purge_row.status<>'previewed' THEN
    RAISE EXCEPTION 'purge request must have a current dry-run preview before approval';
  END IF;
  SELECT * INTO preview_row FROM im19_security.purge_previews
  WHERE request_id=p_request_id ORDER BY created_at DESC,id DESC LIMIT 1;
  IF NOT FOUND THEN RAISE EXCEPTION 'purge preview missing'; END IF;
  IF reviewer.database_role_oid=purge_row.requester_role_oid
     OR reviewer.reviewer_id=purge_row.requester_reviewer_id THEN
    RAISE EXCEPTION 'purge requester cannot approve their own request';
  END IF;
  INSERT INTO im19_security.purge_approvals(
    id,request_id,preview_id,approver_reviewer_id,approver_role_oid,approver_login,approval_ref
  ) VALUES (
    approval_id,p_request_id,preview_row.id,reviewer.reviewer_id,
    reviewer.database_role_oid,reviewer.database_login_role,p_approval_ref
  );
  UPDATE im19_security.purge_requests SET status='approved' WHERE id=p_request_id;
  INSERT INTO im19_security.purge_request_events(
    request_id,event_type,status,actor_login,actor_reviewer_id,details
  ) VALUES (
    p_request_id,'purge_approved','approved',reviewer.database_login_role,
    reviewer.reviewer_id,pg_catalog.jsonb_build_object('preview_id',preview_row.id,'approval_ref',p_approval_ref)
  );
  RETURN approval_id;
END $$;

CREATE FUNCTION im19_security.purgeable_immutable_record()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE v_document_version_id uuid;
BEGIN
  IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'append-only record'; END IF;
  IF TG_TABLE_NAME='review_runs' THEN
    v_document_version_id := OLD.document_id;
  ELSIF TG_TABLE_NAME='human_approvals' THEN
    SELECT r.document_id INTO v_document_version_id FROM im19.review_runs r WHERE r.id=OLD.review_run_id;
  ELSIF TG_TABLE_NAME='review_findings' THEN
    SELECT r.document_id INTO v_document_version_id FROM im19.review_runs r WHERE r.id=OLD.review_run_id;
  ELSE
    RAISE EXCEPTION 'unsupported purgeable immutable table';
  END IF;
  IF v_document_version_id IS NULL OR NOT EXISTS (
    SELECT 1 FROM im19_security.purge_execution_authorizations a
    WHERE a.transaction_id=pg_catalog.txid_current()
      AND a.document_version_id=v_document_version_id
  ) THEN RAISE EXCEPTION 'append-only record'; END IF;
  RETURN OLD;
END $$;

DROP TRIGGER approvals_immutable ON im19.human_approvals;
CREATE TRIGGER approvals_purgeable_immutable BEFORE UPDATE OR DELETE ON im19.human_approvals
FOR EACH ROW EXECUTE FUNCTION im19_security.purgeable_immutable_record();
DROP TRIGGER reviews_immutable ON im19.review_runs;
CREATE TRIGGER reviews_purgeable_immutable BEFORE UPDATE OR DELETE ON im19.review_runs
FOR EACH ROW EXECUTE FUNCTION im19_security.purgeable_immutable_record();
CREATE TRIGGER review_findings_purgeable_immutable BEFORE UPDATE OR DELETE ON im19.review_findings
FOR EACH ROW EXECUTE FUNCTION im19_security.purgeable_immutable_record();

CREATE FUNCTION im19_security.purge_content_write_gate()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE
  v_document_version_id uuid;
  v_related_document_id uuid;
  v_document_state text;
BEGIN
  IF TG_TABLE_NAME IN ('document_pages','chunks','extraction_runs','knowledge_units','review_runs','knowledge_nodes') THEN
    v_document_version_id := NEW.document_id;
  ELSIF TG_TABLE_NAME='knowledge_claims' THEN
    SELECT u.document_id INTO v_document_version_id FROM im19.knowledge_units u WHERE u.id=NEW.id;
  ELSIF TG_TABLE_NAME='claim_evidence' THEN
    SELECT u.document_id INTO v_document_version_id FROM im19.knowledge_units u WHERE u.id=NEW.claim_id;
  ELSIF TG_TABLE_NAME='review_findings' THEN
    SELECT r.document_id,u.document_id INTO v_document_version_id,v_related_document_id
    FROM im19.review_runs r,im19.knowledge_units u
    WHERE r.id=NEW.review_run_id AND u.id=NEW.knowledge_id;
    IF v_related_document_id IS DISTINCT FROM v_document_version_id THEN
      RAISE EXCEPTION 'review finding crosses document versions';
    END IF;
  ELSIF TG_TABLE_NAME='human_approvals' THEN
    SELECT r.document_id INTO v_document_version_id FROM im19.review_runs r WHERE r.id=NEW.review_run_id;
  ELSIF TG_TABLE_NAME='embeddings' THEN
    SELECT c.document_id INTO v_document_version_id FROM im19.chunks c WHERE c.id=NEW.chunk_id;
  ELSIF TG_TABLE_NAME='knowledge_relations' THEN
    IF EXISTS (
      SELECT 1 FROM im19.knowledge_nodes n JOIN im19.document_versions v ON v.id=n.document_id
      WHERE n.id IN (NEW.source_id,NEW.target_id)
        AND (v.state IN ('QUARANTINED','SUPERSEDED') OR EXISTS (
          SELECT 1 FROM im19_security.purge_requests p WHERE p.document_version_id=v.id
        ))
    ) OR EXISTS (
      SELECT 1 FROM im19.claim_evidence e
      JOIN im19.knowledge_units u ON u.id=e.claim_id
      JOIN im19.document_versions v ON v.id=u.document_id
      WHERE e.id=NEW.evidence_id
        AND (v.state IN ('QUARANTINED','SUPERSEDED') OR EXISTS (
          SELECT 1 FROM im19_security.purge_requests p WHERE p.document_version_id=v.id
        ))
    ) THEN RAISE EXCEPTION 'cannot add graph relation to quarantined or purge-requested content'; END IF;
    RETURN NEW;
  ELSE
    RAISE EXCEPTION 'unsupported content write gate table';
  END IF;

  IF v_document_version_id IS NULL THEN RAISE EXCEPTION 'content parent document version is missing'; END IF;
  SELECT v.state INTO v_document_state FROM im19.document_versions v WHERE v.id=v_document_version_id;
  IF v_document_state IN ('QUARANTINED','SUPERSEDED') OR EXISTS (
    SELECT 1 FROM im19_security.purge_requests p WHERE p.document_version_id=v_document_version_id
  ) THEN
    RAISE EXCEPTION 'cannot write content for quarantined or purge-requested document version';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER pages_purge_write_gate BEFORE INSERT OR UPDATE ON im19.document_pages
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_content_write_gate();
CREATE TRIGGER chunks_purge_write_gate BEFORE INSERT OR UPDATE ON im19.chunks
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_content_write_gate();
CREATE TRIGGER extraction_runs_purge_write_gate BEFORE INSERT OR UPDATE ON im19.extraction_runs
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_content_write_gate();
CREATE TRIGGER knowledge_units_purge_write_gate BEFORE INSERT OR UPDATE ON im19.knowledge_units
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_content_write_gate();
CREATE TRIGGER knowledge_claims_purge_write_gate BEFORE INSERT OR UPDATE ON im19.knowledge_claims
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_content_write_gate();
CREATE TRIGGER claim_evidence_purge_write_gate BEFORE INSERT OR UPDATE ON im19.claim_evidence
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_content_write_gate();
CREATE TRIGGER review_runs_purge_write_gate BEFORE INSERT OR UPDATE ON im19.review_runs
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_content_write_gate();
CREATE TRIGGER review_findings_purge_write_gate BEFORE INSERT OR UPDATE ON im19.review_findings
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_content_write_gate();
CREATE TRIGGER human_approvals_purge_write_gate BEFORE INSERT OR UPDATE ON im19.human_approvals
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_content_write_gate();
CREATE TRIGGER knowledge_nodes_purge_write_gate BEFORE INSERT OR UPDATE ON im19.knowledge_nodes
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_content_write_gate();
CREATE TRIGGER knowledge_relations_purge_write_gate BEFORE INSERT OR UPDATE ON im19.knowledge_relations
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_content_write_gate();
CREATE TRIGGER embeddings_purge_write_gate BEFORE INSERT OR UPDATE ON im19.embeddings
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_content_write_gate();

CREATE FUNCTION im19_security.purge_job_write_gate()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $
DECLARE v_state text;
BEGIN
  SELECT v.state INTO v_state FROM im19.document_versions v
  WHERE v.id=NEW.document_id;
  IF v_state IS NULL OR v_state IN ('QUARANTINED','SUPERSEDED')
     OR EXISTS (
       SELECT 1 FROM im19_security.purge_requests p
       WHERE p.document_version_id=NEW.document_id
     ) THEN
    RAISE EXCEPTION 'cannot queue work for quarantined or purge-requested document version';
  END IF;
  RETURN NEW;
END $;

CREATE TRIGGER ingestion_jobs_purge_write_gate
BEFORE INSERT OR UPDATE ON im19.ingestion_jobs
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_job_write_gate();

CREATE FUNCTION im19_security.purge_version_state_gate()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM im19_security.purge_requests p WHERE p.document_version_id=OLD.id)
     AND NEW.state IS DISTINCT FROM OLD.state
     AND NEW.state IS DISTINCT FROM 'QUARANTINED' THEN
    RAISE EXCEPTION 'document version is locked by an immutable purge request';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER purge_version_state_gate BEFORE UPDATE ON im19.document_versions
FOR EACH ROW EXECUTE FUNCTION im19_security.purge_version_state_gate();

CREATE FUNCTION im19.execute_approved_source_purge(p_request_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE
  storage_node record;
  purge_row record;
  preview_row record;
  approval_row record;
  current_counts jsonb;
  tombstone_id uuid := pg_catalog.gen_random_uuid();
  active_nodes bigint;
  target_nodes bigint;
BEGIN
  SELECT * INTO storage_node FROM im19_security.current_storage_node();
  SELECT * INTO purge_row FROM im19_security.purge_requests WHERE id=p_request_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'purge request not found'; END IF;
  IF purge_row.status IN ('database_purged','completed') THEN
    RETURN pg_catalog.jsonb_build_object('status',purge_row.status,'request_id',p_request_id);
  END IF;
  IF purge_row.status<>'approved' THEN RAISE EXCEPTION 'purge request is not approved'; END IF;

  SELECT * INTO preview_row FROM im19_security.purge_previews
  WHERE request_id=p_request_id ORDER BY created_at DESC,id DESC LIMIT 1;
  SELECT * INTO approval_row FROM im19_security.purge_approvals
  WHERE request_id=p_request_id AND preview_id=preview_row.id;
  IF preview_row.id IS NULL OR approval_row.id IS NULL
     OR approval_row.approver_role_oid=purge_row.requester_role_oid THEN
    RAISE EXCEPTION 'current preview and independent reviewer approval are required';
  END IF;

  SELECT count(*) INTO active_nodes FROM im19_security.worker_storage_nodes n
  WHERE NOT EXISTS (SELECT 1 FROM im19_security.worker_storage_node_revocations x WHERE x.database_role_oid=n.database_role_oid);
  SELECT count(*) INTO target_nodes FROM im19_security.purge_storage_targets t WHERE t.request_id=p_request_id;
  IF active_nodes<>target_nodes OR EXISTS (
    SELECT 1 FROM im19_security.worker_storage_nodes n
    WHERE NOT EXISTS (SELECT 1 FROM im19_security.worker_storage_node_revocations x WHERE x.database_role_oid=n.database_role_oid)
      AND NOT EXISTS (
        SELECT 1 FROM im19_security.purge_storage_targets t
        WHERE t.request_id=p_request_id AND t.storage_node_id=n.storage_node_id
      )
  ) THEN RAISE EXCEPTION 'worker storage inventory changed; a new purge request and preview are required'; END IF;

  current_counts := im19_security.purge_inventory(purge_row.document_version_id);
  IF current_counts IS DISTINCT FROM preview_row.artifact_counts THEN
    UPDATE im19_security.purge_requests SET status='previewed' WHERE id=p_request_id;
    INSERT INTO im19_security.purge_request_events(request_id,event_type,status,actor_login,details)
    VALUES (p_request_id,'purge_preview_invalidated','previewed',session_user,
      pg_catalog.jsonb_build_object('reason','artifact_inventory_changed'));
    RETURN pg_catalog.jsonb_build_object('status','repreview_required','request_id',p_request_id,
      'current_artifact_counts',current_counts);
  END IF;

  INSERT INTO im19_security.purge_execution_authorizations(transaction_id,document_version_id,request_id)
  VALUES (pg_catalog.txid_current(),purge_row.document_version_id,p_request_id);

  DELETE FROM im19.knowledge_relations r
  WHERE r.source_id IN (SELECT id FROM im19.knowledge_nodes WHERE document_id=purge_row.document_version_id)
     OR r.target_id IN (SELECT id FROM im19.knowledge_nodes WHERE document_id=purge_row.document_version_id)
     OR r.evidence_id IN (
       SELECT e.id FROM im19.claim_evidence e
       WHERE e.claim_id IN (SELECT id FROM im19.knowledge_units WHERE document_id=purge_row.document_version_id)
          OR e.chunk_id IN (SELECT id FROM im19.chunks WHERE document_id=purge_row.document_version_id)
     );
  DELETE FROM im19.embeddings e USING im19.chunks c
  WHERE e.chunk_id=c.id AND c.document_id=purge_row.document_version_id;
  DELETE FROM im19.claim_evidence e
  WHERE e.claim_id IN (SELECT id FROM im19.knowledge_units WHERE document_id=purge_row.document_version_id)
     OR e.chunk_id IN (SELECT id FROM im19.chunks WHERE document_id=purge_row.document_version_id);
  DELETE FROM im19.review_findings f
  WHERE f.review_run_id IN (SELECT id FROM im19.review_runs WHERE document_id=purge_row.document_version_id)
     OR f.knowledge_id IN (SELECT id FROM im19.knowledge_units WHERE document_id=purge_row.document_version_id);
  DELETE FROM im19.human_approvals a USING im19.review_runs r
  WHERE a.review_run_id=r.id AND r.document_id=purge_row.document_version_id;
  DELETE FROM im19.review_runs WHERE document_id=purge_row.document_version_id;
  DELETE FROM im19.knowledge_claims k USING im19.knowledge_units u
  WHERE k.id=u.id AND u.document_id=purge_row.document_version_id;
  DELETE FROM im19.knowledge_units WHERE document_id=purge_row.document_version_id;
  DELETE FROM im19.knowledge_nodes WHERE document_id=purge_row.document_version_id;
  DELETE FROM im19.chunks WHERE document_id=purge_row.document_version_id;
  DELETE FROM im19.document_pages WHERE document_id=purge_row.document_version_id;
  DELETE FROM im19.extraction_runs WHERE document_id=purge_row.document_version_id;
  DELETE FROM im19.ingestion_jobs WHERE document_id=purge_row.document_version_id;

  INSERT INTO im19_security.purge_tombstones(
    id,request_id,source_file_id,document_version_id,revision,content_hash,
    reason_code,retention_policy_ref,legal_hold_check_ref,
    requester_reviewer_id,approver_reviewer_id,deleted_artifact_counts
  ) VALUES (
    tombstone_id,p_request_id,purge_row.source_file_id,purge_row.document_version_id,
    purge_row.revision,purge_row.content_hash,purge_row.reason_code,
    purge_row.retention_policy_ref,purge_row.legal_hold_check_ref,
    purge_row.requester_reviewer_id,approval_row.approver_reviewer_id,current_counts
  );

  UPDATE im19.document_versions
  SET checkpoint='{}'::jsonb,classification=NULL,review=NULL,content_sha256=NULL
  WHERE id=purge_row.document_version_id;

  IF NOT EXISTS (
    SELECT 1 FROM im19.document_versions v
    WHERE v.source_file_id=purge_row.source_file_id
      AND NOT EXISTS (SELECT 1 FROM im19_security.purge_tombstones t WHERE t.document_version_id=v.id)
  ) THEN
    UPDATE im19.source_files
    SET source_file_id='im19-purged:'||id::text,
        path='[purged]',filename='[purged]',extension='[purged]',
        size=0,source_uri='urn:im19:purged:'||id::text,
        metadata='{}'::jsonb,access_authorized=false,deleted=true
    WHERE id=purge_row.source_file_id;
  END IF;

  DELETE FROM im19_security.purge_execution_authorizations
  WHERE transaction_id=pg_catalog.txid_current()
    AND document_version_id=purge_row.document_version_id AND request_id=p_request_id;

  UPDATE im19_security.purge_requests
  SET status='database_purged',database_purged_at=pg_catalog.clock_timestamp()
  WHERE id=p_request_id;
  INSERT INTO im19_security.purge_request_events(request_id,event_type,status,actor_login,details)
  VALUES (p_request_id,'database_purge_completed','database_purged',session_user,
    pg_catalog.jsonb_build_object('tombstone_id',tombstone_id,'artifact_counts',current_counts));
  INSERT INTO im19.audit_events(document_id,event_type,details)
  VALUES (purge_row.document_version_id,'source_version_database_purged',
    pg_catalog.jsonb_build_object('purge_request_id',p_request_id,'tombstone_id',tombstone_id));

  RETURN pg_catalog.jsonb_build_object('status','database_purged','request_id',p_request_id,
    'tombstone_id',tombstone_id,'artifact_counts',current_counts,'pending_storage_nodes',target_nodes);
END $$;

CREATE FUNCTION im19.claim_local_purge_targets()
RETURNS TABLE(request_id uuid,document_version_id uuid,storage_node_id text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE storage_node record;
BEGIN
  SELECT * INTO storage_node FROM im19_security.current_storage_node();
  RETURN QUERY
  SELECT t.request_id,p.document_version_id,t.storage_node_id
  FROM im19_security.purge_storage_targets t
  JOIN im19_security.purge_requests p ON p.id=t.request_id
  WHERE p.status='database_purged' AND t.storage_node_id=storage_node.storage_node_id
    AND NOT EXISTS (
      SELECT 1 FROM im19_security.purge_storage_receipts r
      WHERE r.request_id=t.request_id AND r.storage_node_id=t.storage_node_id
    )
  ORDER BY p.database_purged_at,t.request_id;
END $$;

CREATE FUNCTION im19.record_local_purge_receipt(
  p_request_id uuid,p_document_version_id uuid,
  p_blob_files_removed integer,p_temp_files_removed integer,p_files_verified_absent boolean
)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE
  storage_node record;
  request_row record;
  receipt_count bigint;
  target_count bigint;
BEGIN
  SELECT * INTO storage_node FROM im19_security.current_storage_node();
  SELECT * INTO request_row FROM im19_security.purge_requests
  WHERE id=p_request_id AND document_version_id=p_document_version_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'purge request/document version mismatch'; END IF;
  IF request_row.status='completed' AND EXISTS (
    SELECT 1 FROM im19_security.purge_storage_receipts r
    WHERE r.request_id=p_request_id AND r.storage_node_id=storage_node.storage_node_id
  ) THEN RETURN 'completed'; END IF;
  IF request_row.status<>'database_purged' THEN RAISE EXCEPTION 'database purge is not complete'; END IF;
  IF p_blob_files_removed<0 OR p_temp_files_removed<0 OR p_files_verified_absent IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'local purge receipt must verify all version files absent';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM im19_security.purge_storage_targets t
    WHERE t.request_id=p_request_id AND t.storage_node_id=storage_node.storage_node_id
  ) THEN RAISE EXCEPTION 'storage node is not a target for this purge request'; END IF;

  INSERT INTO im19_security.purge_storage_receipts(
    request_id,storage_node_id,document_version_id,blob_files_removed,
    temp_files_removed,files_verified_absent,worker_login
  ) VALUES (
    p_request_id,storage_node.storage_node_id,p_document_version_id,
    p_blob_files_removed,p_temp_files_removed,true,storage_node.database_login_role
  ) ON CONFLICT(request_id,storage_node_id) DO NOTHING;

  SELECT count(*) INTO receipt_count FROM im19_security.purge_storage_receipts r WHERE r.request_id=p_request_id;
  SELECT count(*) INTO target_count FROM im19_security.purge_storage_targets t WHERE t.request_id=p_request_id;
  IF receipt_count=target_count THEN
    UPDATE im19_security.purge_requests SET status='completed',completed_at=pg_catalog.clock_timestamp()
    WHERE id=p_request_id AND status='database_purged';
    INSERT INTO im19_security.purge_request_events(request_id,event_type,status,actor_login,details)
    VALUES (p_request_id,'purge_completed','completed',session_user,
      pg_catalog.jsonb_build_object('storage_node_receipts',receipt_count));
    INSERT INTO im19.audit_events(document_id,event_type,details)
    VALUES (p_document_version_id,'source_version_purge_completed',
      pg_catalog.jsonb_build_object('purge_request_id',p_request_id));
    RETURN 'completed';
  END IF;
  RETURN 'database_purged';
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA im19_security FROM PUBLIC,im19_worker,im19_approver;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA im19_security FROM PUBLIC,im19_worker,im19_approver;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA im19 FROM PUBLIC;

GRANT EXECUTE ON FUNCTION im19.request_source_purge(uuid,text,text,text,boolean) TO im19_approver;
GRANT EXECUTE ON FUNCTION im19.preview_source_purge(uuid) TO im19_approver;
GRANT EXECUTE ON FUNCTION im19.approve_source_purge(uuid,text) TO im19_approver;
GRANT EXECUTE ON FUNCTION im19.execute_approved_source_purge(uuid) TO im19_worker;
GRANT EXECUTE ON FUNCTION im19.claim_local_purge_targets() TO im19_worker;
GRANT EXECUTE ON FUNCTION im19.record_local_purge_receipt(uuid,uuid,integer,integer,boolean) TO im19_worker;

COMMIT;
