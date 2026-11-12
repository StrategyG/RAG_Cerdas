-- Bind human review records to a dedicated authenticated PostgreSQL LOGIN principal.
-- This is a database-principal binding, not an SSO/MFA identity-provider implementation.
-- Registry objects live in a separate private schema and are never exposed to worker/approver roles.
BEGIN;

CREATE SCHEMA IF NOT EXISTS im19_security;
REVOKE ALL ON SCHEMA im19_security FROM PUBLIC;
REVOKE ALL ON SCHEMA im19_security FROM im19_worker, im19_approver;

CREATE TABLE im19_security.reviewer_identities (
  database_role_oid oid PRIMARY KEY CHECK(database_role_oid > 0),
  database_login_role name NOT NULL,
  reviewer_id text NOT NULL CHECK(length(trim(reviewer_id)) BETWEEN 1 AND 128),
  display_name text NOT NULL CHECK(length(trim(display_name)) BETWEEN 1 AND 200),
  registered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  registered_by name NOT NULL DEFAULT session_user
);

CREATE INDEX reviewer_identities_reviewer_idx
  ON im19_security.reviewer_identities(reviewer_id);

CREATE TABLE im19_security.reviewer_identity_revocations (
  database_role_oid oid PRIMARY KEY
    REFERENCES im19_security.reviewer_identities(database_role_oid),
  reviewer_id text NOT NULL CHECK(length(trim(reviewer_id)) BETWEEN 1 AND 128),
  reason text NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 2000),
  revoked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  revoked_by name NOT NULL DEFAULT session_user
);

COMMENT ON SCHEMA im19_security IS
  'Private IM19 security control-plane objects; no worker or approver schema access.';
COMMENT ON TABLE im19_security.reviewer_identities IS
  'Immutable mapping from one dedicated PostgreSQL LOGIN role OID to one stable, non-PII reviewer identifier.';
COMMENT ON TABLE im19_security.reviewer_identity_revocations IS
  'Append-only revocation ledger. A revoked database principal cannot submit further human decisions.';

CREATE FUNCTION im19_security.reviewer_identity_insert_gate()
RETURNS trigger
LANGUAGE plpgsql
SET search_path=''
AS $$
DECLARE
  resolved_oid oid;
BEGIN
  resolved_oid := pg_catalog.to_regrole(NEW.database_login_role::text)::oid;
  IF resolved_oid IS NULL OR resolved_oid IS DISTINCT FROM NEW.database_role_oid THEN
    RAISE EXCEPTION 'reviewer identity role name/OID mismatch';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_roles r
    WHERE r.rolname=NEW.database_login_role
      AND r.rolcanlogin
      AND r.rolinherit
      AND NOT r.rolsuper
      AND NOT r.rolbypassrls
      AND NOT r.rolcreaterole
      AND NOT r.rolcreatedb
      AND NOT r.rolreplication
  ) THEN
    RAISE EXCEPTION 'reviewer identity requires a least-privileged LOGIN role';
  END IF;

  IF NOT pg_catalog.pg_has_role(
    NEW.database_login_role, 'im19_approver', 'MEMBER'
  ) THEN
    RAISE EXCEPTION 'reviewer LOGIN must inherit im19_approver';
  END IF;

  IF pg_catalog.pg_has_role(
    NEW.database_login_role, 'im19_worker', 'MEMBER'
  ) THEN
    RAISE EXCEPTION 'reviewer LOGIN must not inherit im19_worker';
  END IF;

  NEW.registered_at := pg_catalog.clock_timestamp();
  NEW.registered_by := session_user;

  IF EXISTS (
    SELECT 1
    FROM im19_security.reviewer_identities i
    WHERE i.database_role_oid=NEW.database_role_oid
      AND (
        i.database_login_role IS DISTINCT FROM NEW.database_login_role
        OR i.reviewer_id IS DISTINCT FROM NEW.reviewer_id
      )
  ) THEN
    RAISE EXCEPTION 'reviewer database principal is already bound to another identity';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM im19_security.reviewer_identities i
    WHERE i.reviewer_id=NEW.reviewer_id
      AND i.database_role_oid<>NEW.database_role_oid
      AND NOT EXISTS (
        SELECT 1
        FROM im19_security.reviewer_identity_revocations x
        WHERE x.database_role_oid=i.database_role_oid
      )
  ) THEN
    RAISE EXCEPTION 'reviewer already has an active database principal';
  END IF;

  RETURN NEW;
END
$$;

CREATE TRIGGER reviewer_identity_insert_gate
BEFORE INSERT ON im19_security.reviewer_identities
FOR EACH ROW EXECUTE FUNCTION im19_security.reviewer_identity_insert_gate();

CREATE TRIGGER reviewer_identity_immutable
BEFORE UPDATE OR DELETE ON im19_security.reviewer_identities
FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();

CREATE FUNCTION im19_security.reviewer_revocation_insert_gate()
RETURNS trigger
LANGUAGE plpgsql
SET search_path=''
AS $$
DECLARE
  registered_reviewer_id text;
BEGIN
  SELECT i.reviewer_id
  INTO registered_reviewer_id
  FROM im19_security.reviewer_identities i
  WHERE i.database_role_oid=NEW.database_role_oid;

  IF registered_reviewer_id IS NULL
     OR registered_reviewer_id IS DISTINCT FROM NEW.reviewer_id THEN
    RAISE EXCEPTION 'reviewer revocation does not match registered identity';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM im19_security.reviewer_identity_revocations r
    WHERE r.database_role_oid=NEW.database_role_oid
  ) THEN
    RAISE EXCEPTION 'reviewer principal is already revoked';
  END IF;

  NEW.revoked_at := pg_catalog.clock_timestamp();
  NEW.revoked_by := session_user;
  RETURN NEW;
END
$$;

CREATE TRIGGER reviewer_revocation_insert_gate
BEFORE INSERT ON im19_security.reviewer_identity_revocations
FOR EACH ROW EXECUTE FUNCTION im19_security.reviewer_revocation_insert_gate();

CREATE TRIGGER reviewer_revocation_immutable
BEFORE UPDATE OR DELETE ON im19_security.reviewer_identity_revocations
FOR EACH ROW EXECUTE FUNCTION im19.immutable_record();

-- SECURITY DEFINER is required because the private registry is deliberately unreadable
-- by approver/worker roles. session_user is used, not current_user or a caller-settable GUC.
CREATE FUNCTION im19.assert_registered_reviewer()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=''
AS $$
DECLARE
  principal_name name := session_user;
  principal_oid oid;
  expected_reviewer_id text;
BEGIN
  principal_oid := pg_catalog.to_regrole(session_user::text)::oid;

  SELECT i.reviewer_id
  INTO expected_reviewer_id
  FROM im19_security.reviewer_identities i
  WHERE i.database_role_oid=principal_oid
    AND i.database_login_role=principal_name
    AND NOT EXISTS (
      SELECT 1
      FROM im19_security.reviewer_identity_revocations r
      WHERE r.database_role_oid=i.database_role_oid
    );

  IF expected_reviewer_id IS NULL THEN
    RAISE EXCEPTION 'reviewer principal is not registered or has been revoked'
      USING ERRCODE='42501';
  END IF;

  IF NEW.reviewer_id IS DISTINCT FROM expected_reviewer_id THEN
    RAISE EXCEPTION 'reviewer_id does not match authenticated database principal'
      USING ERRCODE='42501';
  END IF;

  NEW.created_at := pg_catalog.clock_timestamp();
  RETURN NEW;
END
$$;

CREATE TRIGGER human_approval_reviewer_identity
BEFORE INSERT ON im19.human_approvals
FOR EACH ROW EXECUTE FUNCTION im19.assert_registered_reviewer();

CREATE TRIGGER source_rights_reviewer_identity
BEFORE INSERT ON im19.source_rights_reviews
FOR EACH ROW EXECUTE FUNCTION im19.assert_registered_reviewer();

REVOKE ALL ON ALL TABLES IN SCHEMA im19_security FROM PUBLIC, im19_worker, im19_approver;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA im19_security FROM PUBLIC, im19_worker, im19_approver;
REVOKE ALL ON FUNCTION im19.assert_registered_reviewer() FROM PUBLIC, im19_worker, im19_approver;

COMMIT;
