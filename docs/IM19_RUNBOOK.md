# IM19 operational runbook

## Prerequisites and staging setup

1. Review `IM19_AUDIT_20261025.md`, migration and privileges. Take a backup and prove restore in staging. New migration assumes pgvector is already installed in `extensions`; it deliberately fails otherwise. Never run a migration from worker startup.
2. On an isolated staging DB, apply **only** `20261025010000_im19_knowledge_intelligence.sql` after its prerequisite. Existing legacy migrations need a historical `rag` base and must not be blindly applied to an empty DB.
3. Administrator provisions separate LOGIN credentials inheriting `im19_worker` and `im19_approver`; use certificate-verified TLS. Workers must not inherit approver/admin roles. Store DSN in mounted `im19_database_dsn`; put Dropbox app key/secret/refresh token in secret-manager mounts with their lowercase names. Do not commit them.
4. Register a Dropbox OAuth app with read scopes only and approved app-folder access. Complete official OAuth consent with `token_access_type=offline`; store its issued refresh token in the secret manager. The worker refreshes existing authorization; it does not fabricate consent or capture credentials. Revocation/rotation occurs through the provider/secret manager, followed by worker restart.
5. Admin creates a row in `im19.source_connections` with a deliberately approved `root_path` and access scope. Copy its UUID into non-secret configuration. Run `python -m im19.cli health`, then `python -m im19.cli discover --connection-id UUID --max-pages 1` against staging. Discovery writes metadata/cursor only; no source download.
6. Use the separate approver to authorize processing rights for one `source_files` row. Obtain its `document_versions.id`. Supply reviewed Qwen GGUF/E5 local files via `IM19_GGUF_PATH`, `IM19_GGUF_SHA256` and `IM19_EMBEDDING_PATH` / `IM19_EMBEDDING_SHA256`. E5 is loaded with local-files-only. Models are not automatically downloaded by the worker. Compute the E5 tree identity with `python -m im19.model_integrity /models/multilingual-e5-small` and verify it against the reviewed artifact before configuring it. Copy model files into a local directory; symlinks are refused.
7. `python -m im19.cli pilot --document-id UUID` processes only that queued document, stopping at review/publication gates. Add `--enable-ocr` after installing Tesseract/language packs. Inspect source pages, quotes, all review roles, category labels and relationship candidates. AI output remains unverified.
8. With the separate approver credential, insert a decision into `im19.human_approvals` using the immutable `review_run_id`, accountable `reviewer_id`, `decision` and rationale. Approving a review does not verify factual truth. Worker `resume_approved()` schedules approved held jobs; then rerun the one-document pilot.
9. Read back pages, units, embeddings, version state and citations; test one deliberately unanswerable query. Build a human-reviewed dataset across categories/OCR/contradictions before calibrating any automation threshold.

## Worker deployment (after release approval)

Build `deploy/Dockerfile.knowledge`, review/pin its image and dependencies, provide read-only model/secret mounts and durable `/data/im19`, then use `deploy/compose.knowledge.yml`. Worker polls every five minutes by default, with bounded metadata pages per cycle. This example has not been built/deployed in this change. Colab notebooks cannot provide 24/7 operation.

Health command reports DB reachability and job counts, not overall production readiness. Use `supabase/verification/im19_operational_health.sql` for queue/dead-letter/lease/source status and latest audit timestamps. Configure monitoring for AUTH_BLOCKED, no stage progress, repeated retries, dead-letter growth, disk/memory limits, source-to-publication lag and backup age. Alert delivery is not configured here.

## Recovery

- **401 / revoked authorization:** connector becomes AUTH_BLOCKED, not a missing-file result. Discovery refuses further calls until operator reauthentication and explicit connection reactivation. Other local workflows remain available. Never reset file statuses to hide an authentication failure.
- **429/5xx/network timeout:** bounded exponential backoff+jitter; long Retry-After defers work; job retries retain the last committed stage. After attempt budget, inspect dead letter and reconcile before an explicit requeue.
- **Expired lease/crash:** a replacement gets a new fencing token. Old workers cannot commit after the lease changes. Heartbeats extend live processing leases. Crash recovery reuses SQL checkpoints and read-back embeddings. An interrupted model stage may rerun; it does not mean previously published content is rewritten.
- **Colab disconnect/lost disk:** reconnect to the same staging DB. Missing downloads are fetched again by pinned revision and both hashes must match before parsing. No claim of Colab persistence is made.
- **Cursor reset (409 reset):** halt for reconciliation. Preserve inventory/cursor evidence, compare a fresh metadata traversal and explicitly review tombstones. Do not drop the cursor and assume missing sources were handled.
- **OCR_REQUIRED/encrypted/corrupt/ambiguous:** held/quarantined, not published. Fix the parser/config/source through reviewed changes; never insert invented text/pages. Remediation may require a new processing version or explicit requeue after operator review.
- **Source change/deletion:** old version is SUPERSEDED and retrieval rechecks current source revision/hash/access. Original Dropbox files are never modified. Dedup holds identical content for review and keeps source identities.
- **Database outage:** transactions rollback, discovery cursor remains unchanged and uncommitted stage work replays; restart policy may restart a failed service. Native DB failover and disaster recovery still require target-environment tests.

## Rollback

Stop the new worker, disable the new source connection, and use the previous application image/branch. New schema does not affect legacy `rag`. Preserve `im19` data/reviews/audit for diagnosis. Do not DROP schema/tables, delete source files or roll back migrations destructively. A schema rollback requires a backup-restored staging rehearsal, explicit human approval and a separate reviewed migration. No schema rollback is executed here.
