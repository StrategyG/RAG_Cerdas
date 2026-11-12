# IM19 reviewer-principal identity contract

**Status:** Implemented in the P0 reviewer-principal branch; pending disposable PostgreSQL CI and review.  
**Scope:** Human publication approvals and source-rights decisions in the private IM19 pilot.

## Security contract

IM19 previously accepted the reviewer_id column as caller-supplied text. The private im19_approver role constrained who could write decisions, but did not bind the submitted reviewer identifier to the authenticated database principal.

The new migration introduces a private im19_security schema:

- reviewer_identities binds one PostgreSQL LOGIN role OID and role name to one stable, non-PII reviewer ID.
- reviewer_identity_revocations is an append-only revocation ledger.
- Registration is accepted only for an existing least-privileged LOGIN role with a direct im19_approver membership (without admin option). Its complete direct and transitive role-membership closure may contain im19_approver only; additional group roles, including roles inherited through im19_approver, are rejected. Superuser, BYPASSRLS, role-creation, database-creation, replication, and NOINHERIT roles are rejected.
- A reviewer ID can have only one active login principal at a time. Rotate by revoking the old principal and registering a new one.
- Both human_approvals and source_rights_reviews validate session_user and require the supplied reviewer_id to match the registered identity. The role-membership restriction is rechecked at every decision insert, so later grants of another group role fail closed.
- The trigger does not trust current_user, a request field, or a custom PostgreSQL setting.
- The registry schema is not granted to PUBLIC, im19_worker, or im19_approver. Registration and revocation are administrator operations.
- Registry and revocation records are append-only. Registration, revocation, and human-decision timestamps/actor fields are stamped by database triggers.

A shared database login or shared pooler credential cannot distinguish individual humans and must not be used for human approval sessions.

## Provisioning

1. An administrator provisions one dedicated least-privileged LOGIN role for each human reviewer and grants it membership in im19_approver only. Do not grant it any other group role, directly or transitively. Do not use the worker login, a role with BYPASSRLS/superuser privileges, or a shared service login.
2. Register the login principal as administrator. Replace the example values with a real role name and a stable, non-PII reviewer identifier:

   INSERT INTO im19_security.reviewer_identities (database_role_oid, database_login_role, reviewer_id, display_name) SELECT pg_catalog.to_regrole('im19_reviewer_alice')::oid, 'im19_reviewer_alice', 'reviewer:alice', 'Reviewer Alice' WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='im19_reviewer_alice' AND rolcanlogin) AND EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members WHERE member=pg_catalog.to_regrole('im19_reviewer_alice')::oid AND roleid=pg_catalog.to_regrole('im19_approver')::oid AND NOT admin_option);

3. Confirm that exactly one identity row exists for the login and reviewer ID using an administrator connection. The approver login cannot inspect the registry.
4. Connect to the database using that reviewer-specific LOGIN role when appending a source-rights decision or human approval. The submitted reviewer_id must exactly match the registered mapping.

## Revocation and rotation

An administrator revokes a reviewer by appending a row:

INSERT INTO im19_security.reviewer_identity_revocations (database_role_oid, reviewer_id, reason) SELECT database_role_oid, reviewer_id, 'Reviewer access withdrawn under approved access-change record' FROM im19_security.reviewer_identities WHERE database_login_role='im19_reviewer_alice' AND reviewer_id='reviewer:alice';

Revocation is permanent for that database role OID. To restore access, provision a new LOGIN role, grant im19_approver, and register the new role against the same stable reviewer ID after the old mapping is revoked. Do not delete or rewrite historical decisions or registry records.

After a database restore or role recreation, re-check role OIDs and re-register principals through the administrator workflow. A restored registry row whose OID no longer matches the recreated login will fail closed.

## Limitations

This mechanism proves that a decision was submitted through a registered PostgreSQL LOGIN principal and that its reviewer ID was not spoofed in the insert. It does not itself provide SSO, MFA, HR identity proofing, account lifecycle automation, or end-user authentication at an HTTP/API gateway. Those require a future trusted identity-provider integration. This mapping is global to the IM19 database and does not itself provide tenant/project authorization; tenant-scoped authorization remains a separate P0 gate. Do not treat this interim database binding as a complete enterprise identity solution.

No production migration, source ingestion, database cutover, or deployment is authorized by this change.
