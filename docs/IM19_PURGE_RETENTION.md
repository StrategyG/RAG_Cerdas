# IM19 revision-bound source purge and retention contract

**Status:** Implemented on the P0 purge branch; pending disposable PostgreSQL CI, security review, and staging rehearsal.  
**Scope:** One exact document_versions.id, revision, and source_content_hash at a time.

## Safety model

- Hold/reject remains quarantine only. It removes the exact published version from retrieval but does not erase stored content.
- Purge is a separate destructive workflow. A registered reviewer requests it; a different registered reviewer approves the latest dry-run preview.
- Request, preview, and approval are append-only evidence. The request is bound to the immutable document-version ID, source-file ID, revision, and content hash.
- The request requires a retention-policy reference and an affirmative legal-hold check reference. The boolean is an accountable human attestation; it is not an automated connection to a legal-hold system.
- Creating a request quarantines the version, blocks its ingestion job, clears the worker lease, and prevents new content/job writes for that version.
- Database execution rechecks the dry-run inventory. If any artifact count changed, it performs no deletion and returns repreview_required; a new preview and a new independent approval are required.
- The database purge runs in one transaction. It deletes derived pages, chunks, embeddings, knowledge units/claims, claim evidence, review findings/runs, human approvals, graph nodes/relations, extraction runs, and ingestion jobs for that exact version. Cross-document graph/evidence edges that point into the purged version are also removed.
- The document_versions row remains as a minimal tombstone. When every version of a source file has a purge tombstone, its source path/name/URI and metadata are scrubbed from source_files.
- source_rights_reviews and content-free audit_events remain as governance evidence. Purge request/approval/event/receipt/tombstone records remain content-free and append-only.

## Local storage coverage

Every distinct durable worker blob root must be registered in im19_security.worker_storage_nodes against a dedicated least-privileged PostgreSQL LOGIN directly inheriting im19_worker only. A shared worker credential across independent roots is not supported for purge completion.

Each registered root must contain .im19-storage-node-id whose contents exactly match the database storage_node_id. Provision the marker only after verifying the durable volume is mounted at IM19_WORKDIR. The cleanup command removes only:

- <document-version-uuid>.blob
- <document-version-uuid>.<lease-uuid>.tmp

It unlinks symlinks as directory entries and never follows their targets. It does not remove unrelated files. A local receipt is recorded only after the marker matches and both exact-version file patterns are verified absent. The purge request reaches completed only after every storage target has recorded a receipt.

Register all storage roots before ingestion. Storage-node registration/revocation is blocked while a purge is active, so the target inventory cannot silently change mid-purge.

## Operator sequence

1. Confirm the approved retention policy, owner request/rights withdrawal, and legal-hold status outside IM19. Use reference IDs, not copied source text, in the purge records.
2. Confirm all worker storage roots are registered and mounted. Verify each marker and its dedicated worker LOGIN.
3. As the requesting reviewer LOGIN, create a request:

   SELECT im19.request_source_purge('DOCUMENT_VERSION_UUID','rights_withdrawal','retention-policy:REF','legal-hold-check:REF',true);

4. Preview the exact request:

   SELECT im19.preview_source_purge('PURGE_REQUEST_UUID');

   Inspect every returned count. The preview does not reveal source text.
5. As a different reviewer LOGIN, approve the exact preview:

   SELECT im19.approve_source_purge('PURGE_REQUEST_UUID','approval-ticket:REF');

6. From a registered worker storage node, execute the database purge:

   python -m im19.cli purge-db --purge-request-id PURGE_REQUEST_UUID

7. On every registered storage node, with the matching IM19_WORKDIR, run:

   python -m im19.cli purge-local

8. Verify request status completed, one receipt per target, and the tombstone inventory. If a worker node is unavailable, the request remains database_purged; do not claim full completion.
9. Reconcile backups and external storage under their separately approved retention/expiry process.

## What completion does not mean

- It does not delete the original file from Dropbox; the connector is read-only and this workflow does not modify source files.
- It does not guarantee immediate physical erasure from immutable database backups, snapshots, or any external object store. Backup expiry/cryptographic-erasure guarantees must be verified for the target provider.
- It does not delete source-rights review records or audit history. Their retention/anonymization is a separate data-governance decision.
- It does not cover unregistered local caches, developer copies, exports, or external replicas. Inventory and an adapter/receipt for any such store are required before production.
- The legal-hold reference is an attestation, not legal advice or an automated legal-system integration.

No production migration, purge, Dropbox mutation, or deployment is performed by this code change.
