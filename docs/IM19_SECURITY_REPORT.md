# IM19 security report

## Controls implemented and locally testable

- Read-only Dropbox route allowlist; OAuth request is restricted to `files.metadata.read files.content.read`; no write/share/move/delete API exists in the new client. Authorization scope enforcement at the provider still needs a live app-console review.
- OAuth refresh secrets come from mounted secret managers or Colab Secrets; refreshed access tokens live in process memory. The legacy CLI environment adapter remains for compatibility. Credentials, response bodies and raw exception messages are not persisted by the new worker.
- New DB login must use TLS `sslmode=verify-full`; CLI rejects superuser/BYPASSRLS logins. New schema has RLS+FORCE RLS and no PUBLIC/API grants. Worker and human approver use separate roles. Do not use production `postgres` or `service_role` as the worker login.
- Audit and approval/review records reject UPDATE/DELETE; workers have no DELETE/TRUNCATE privilege. A privileged DBA can still alter triggers/schema: ship backups and audit exports into a separate trust domain before production.
- New documents are held before download until a separate role authorizes processing access; the worker cannot authorize itself.
- UUID-only download filenames, path traversal rejection, bounded ZIP expansion, no EPUB network/resource fetching, defused XML, PDF/OCR quotas, parser subprocess timeout and resource limits.
- Source data has no execution/tool capability. Strict model schemas, quote binding, injection signals and independent publication gate prevent model-created source citations or approvals from silently publishing.
- Graph relationships remain pending; a difference of context/definition/period/methodology maps to RELATED_TO rather than factual CONTRADICTS. Exact source quotation does not prove a model's paraphrase or relation is correct.

## Outstanding verification

Live OAuth refresh/revocation, read scopes, token rotation, actual Supabase grants/RLS, external identity/access control, native-parser penetration testing, dependency/SBOM/CVE review, encrypted backup/restore and network segmentation are **BLOCKED / NOT VERIFIED** here. The requirements use bounded versions, not a fully pinned reproducible dependency lock. Production must pin reviewed wheels/images/model hashes and retain their licenses/SBOM.

Source files are metadata-first and private. Set `access_authorized` only after verifying rights to process the specific documents. Copyright ownership is not inferred from Dropbox possession. Do not expose this schema through PostgREST or the legacy public Edge Function. The supplied search API is a trusted-worker Python interface; it is not a multi-tenant public service.

## Retention and incident policy

Pilot policy: preserve originals unchanged; preserve immutable review/approval/audit history and version identity; keep working downloads on a restricted volume. No automatic document/audit deletion is implemented. Before production, the owner must approve a retention period, legal holds, backup schedule and a separately privileged, audited disposal workflow. Do not weaken append-only triggers to implement routine cleanup.

For compromised Dropbox credentials: halt the connector, revoke/rotate through Dropbox and the secret manager, restart the worker to clear in-memory access tokens, verify least scopes with one metadata read, and explicitly reactivate its connection. For compromised DB login: stop workers, revoke login, preserve logs/backups, rotate credentials and review publication history. Do not paste secrets into reports or issue comments.
