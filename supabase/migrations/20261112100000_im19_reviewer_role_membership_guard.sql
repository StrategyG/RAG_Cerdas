-- Close reviewer identity privilege-escalation paths through additional role memberships.
-- A reviewer LOGIN may inherit im19_approver only, and the restriction is
-- rechecked for every human decision so later role grants fail closed.
BEGIN;

CREATE FUNCTION im19_security.assert_reviewer_membership_scope(p_role_oid oid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=''
AS $$
DECLARE
  approver_oid oid;
BEGIN
  approver_oid := pg_catalog.to_regrole('im19_approver')::oid;
  IF p_role_oid IS NULL OR approver_oid IS NULL THEN
    RAISE EXCEPTION 'reviewer membership roles are not configured'
      USING ERRCODE='42501';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_roles r
    WHERE r.oid=p_role_oid
      AND r.rolcanlogin
      AND r.rolinherit
      AND NOT r.rolsuper
      AND NOT r.rolbypassrls
      AND NOT r.rolcreaterole
      AND NOT r.rolcreatedb
      AND NOT r.rolreplication
  ) THEN
    RAISE EXCEPTION 'reviewer principal is no longer a least-privileged LOGIN'
      USING ERRCODE='42501';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_auth_members membership
    WHERE membership.member=p_role_oid
      AND membership.roleid=approver_oid
      AND NOT membership.admin_option
  ) THEN
    RAISE EXCEPTION 'reviewer LOGIN must remain a direct im19_approver member without admin option'
      USING ERRCODE='42501';
  END IF;

  -- Inspect the complete transitive membership closure, not just direct grants.
  -- This also rejects a privileged role inherited through im19_approver itself.
  IF EXISTS (
    WITH RECURSIVE inherited_roles(role_oid) AS (
      SELECT membership.roleid
      FROM pg_catalog.pg_auth_members membership
      WHERE membership.member=p_role_oid
      UNION
      SELECT membership.roleid
      FROM pg_catalog.pg_auth_members membership
      JOIN inherited_roles inherited
        ON membership.member=inherited.role_oid
    )
    SELECT 1
    FROM inherited_roles
    WHERE role_oid <> approver_oid
  ) THEN
    RAISE EXCEPTION 'reviewer LOGIN must inherit only im19_approver'
      USING ERRCODE='42501';
  END IF;
END
$$;

CREATE FUNCTION im19_security.reviewer_identity_membership_guard()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=''
AS $$
BEGIN
  PERFORM im19_security.assert_reviewer_membership_scope(NEW.database_role_oid);
  RETURN NEW;
END
$$;

CREATE TRIGGER reviewer_identity_membership_guard
BEFORE INSERT ON im19_security.reviewer_identities
FOR EACH ROW EXECUTE FUNCTION im19_security.reviewer_identity_membership_guard();

-- Recheck the complete role-membership scope at decision time. An administrator
-- granting another group role after registration must not silently expand the
-- reviewer principal's authority.
CREATE OR REPLACE FUNCTION im19.assert_registered_reviewer()
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
  PERFORM im19_security.assert_reviewer_membership_scope(principal_oid);

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

REVOKE ALL ON FUNCTION im19_security.assert_reviewer_membership_scope(oid)
  FROM PUBLIC, im19_worker, im19_approver;
REVOKE ALL ON FUNCTION im19_security.reviewer_identity_membership_guard()
  FROM PUBLIC, im19_worker, im19_approver;
REVOKE ALL ON FUNCTION im19.assert_registered_reviewer()
  FROM PUBLIC, im19_worker, im19_approver;

COMMIT;
