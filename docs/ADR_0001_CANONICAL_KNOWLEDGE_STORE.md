# ADR-0001 — Canonical RUSA AI knowledge store and RAG integration

- **Status:** Proposed — no canonical-store decision approved
- **Date:** 2026-11-12
- **Decision owners:** RUSA AI architecture, security, data governance, and operations
- **Related:** RUSA AI Agent & Worker 5M Hybrid Corpus Expansion Plan v1.0; RusaAi Architecture v2.0; RAG_Cerdas IM19 Production Roadmap v1.1

## 1. Context

The architecture and repositories describe three distinct layers. They are not interchangeable and must not be treated as one database or one production service.

### Local device memory baseline — SQLite / FTS5

RusaAi Architecture v2.0 and the CPU Deployment Configuration v1.0 specify SQLite for local metadata and state, SQLite FTS5 for full-text retrieval, durable task/checkpoint state, and vector search as optional after benchmarking. This is the device-local memory/runtime baseline. The supplied documents do not define a replication or synchronization contract from this local store to a shared corpus, and the local baseline does not by itself establish a central 5M Agent/Worker corpus store.

### Option A — RusaAi rusa_knowledge

Observed on StrategyG/RusaAi main:

- Optional application service under rusa_knowledge/; it is not enabled in the core API merely because the package is installed.
- PostgreSQL tables public.rusa_knowledge_documents and public.rusa_knowledge_chunks.
- tenant_id and collection are first-class scope columns; the migration enables and forces RLS, and the store sets transaction-local tenant context.
- Dedicated non-login knowledge role and read-only tenant-authenticated MCP tools exist.
- Hybrid retrieval uses PostgreSQL full-text search plus pgvector and weighted RRF.
- The store supports separate 1,536-dimensional and 384-dimensional vector columns/configurations. The 384-dimensional path requires query/passage input types.
- The current service chunk defaults are 1,200 characters with 180-character overlap. These are character limits, not the Architecture v2.0 token baseline.

This implementation already has a tenant-oriented database boundary, but its schema and pipeline do not yet represent the full IM19 source-version, rights, review, human-approval, evidence, and graph lifecycle.

### Option B — RAG_Cerdas im19

Observed on StrategyG/RAG_Cerdas main:

- Private im19 PostgreSQL schema for source connections/files, document versions, page locators, chunks, knowledge units/claims, evidence, review findings, human approvals, graph relations, embeddings, jobs, and audit events.
- 384-dimensional pgvector embeddings and HNSW index.
- Versioned source hashes, access authorization flags, page/spine provenance, fenced ingestion jobs, and append-only audit/review/approval records.
- The migration creates private im19_worker and im19_approver roles. Its worker/approver policies use broad private-role access (USING true); the schema does not currently include tenant identifiers or per-tenant RLS predicates.
- The current HybridRetriever is a private worker interface, not a public multi-tenant API.

The IM19 implementation is stronger in source/knowledge lifecycle and evidence modeling, but it is not currently safe to expose as a multi-tenant RUSA API.

### Other live-schema concern

RAG_Cerdas's 5 November 2026 validation record describes a connected Supabase project whose observed schema did not contain im19 and whose applied migration history did not match the repository migration inventory. That is a historical read-only observation, not a current live-state guarantee. Any future deployment must repeat a read-only schema/migration reconciliation against the explicitly approved target before preparing DDL.

## 2. Decision

**No canonical shared Agent/Worker corpus store is selected by this ADR.** The SQLite/FTS5 device-local memory baseline remains the Architecture v2.0 default for local metadata/state and local full-text search; this ADR does not replace it with a remote database.

Until a superseding ADR is approved:

1. Preserve SQLite/FTS5 as the documented local runtime baseline.
2. Keep the optional RusaAi rusa_knowledge PostgreSQL service and RAG_Cerdas IM19 database isolated.
3. Do not dual-write, mirror, bulk-copy, or cross-read production knowledge between the PostgreSQL stores.
4. Do not expose the IM19 schema or retriever as a multi-tenant API.
5. Do not assume a sync/replication path between local SQLite memory and either PostgreSQL store; no such contract is established by the supplied baseline documents.
6. Do not run production migrations, ingestion, embedding, source mutation, or cutover.
7. Keep source discovery, candidate, reviewed, approved, embedded, indexed, and published counts separate.
8. Continue isolated development and disposable/staging validation only, with approved source rights and no secrets/private data in Git.

This is an intentional hold point, not a claim that either implementation is the selected source of truth.

## 3. Options for the eventual decision

### A. Select IM19 as the shared Agent/Worker corpus store

This would not replace the SQLite/FTS5 device-local memory baseline. Required before approval:

- Add tenant and project/access-scope ownership to the IM19 data model, including source connections, source files, versions, chunks, knowledge units, claims/evidence, graph records, embeddings, jobs, approvals, and audit access as appropriate.
- Derive tenant identity from a verified RusaAi principal or signed service identity; never accept a caller-selected tenant as authority.
- Replace broad private worker RLS with database-enforced tenant/project predicates and explicit least-privilege service roles.
- Add cross-tenant negative tests for retrieval, source metadata, graph expansion, job claims, review, approval, audit, deletion, and direct SQL.
- Publish a versioned, authenticated ingestion/retrieval contract with stable IDs, provenance, rights, embedding model/version/dimension, timeouts, trace/task IDs, error envelope, idempotency, tombstones, and deletion lineage.
- Define how the RusaAi tenant-scoped store is migrated, frozen, or retired without losing authorized data or violating retention obligations.
- Benchmark GIN/HNSW query plans and end-to-end capacity at the 10K, 50K, 100K, 1M, and 5M gates.

### B. Select RusaAi rusa_knowledge as the shared Agent/Worker corpus store

This would not replace the SQLite/FTS5 device-local memory baseline. Required before approval:

- Extend the RusaAi schema and contracts to preserve IM19 source revisions, exact locators, rights/attribution, content hashes, knowledge units, claim-evidence links, review findings, human approval, graph lineage, index generation, and immutable audit state.
- Keep verified-principal tenant isolation and forced RLS as mandatory invariants.
- Port or adapt IM19 mining and source-ingestion stages to write through a versioned, authorized contract; do not create a second ungoverned write path.
- Reconcile 384d versus 1,536d vector spaces and pin exact model artifact/version and query/passage preprocessing. Equal dimensions do not prove embedding compatibility.
- Align chunking with the approved token-based Architecture v2.0 baseline and preserve the current tenant-specific collections and project scopes.
- Benchmark the same quality, scale, security, recovery, and cost gates as Option A.

### C. Shared database or dual-write

Not recommended as a default. It increases schema coupling and creates two competing lifecycle/approval authorities. Consider only if a measured requirement cannot be met by a versioned service boundary and if one system remains the sole writer for every canonical record.

## 4. Decision criteria

Score each viable option using the same evidence:

1. Verified-principal authentication and zero cross-tenant leakage.
2. Tenant/project/source scope enforced in the database, not only in application code.
3. Rights, attribution, source revision, content hash, exact locator, deletion, and retention lineage.
4. Human review, publication authorization, and immutable audit.
5. Stable IDs, idempotent replay, checkpoints, lease fencing, retries, and recovery.
6. Exact embedding model artifact/version/dimension and safe index-generation changes.
7. Hybrid retrieval quality, citations, abstention, and human-reviewed qrels.
8. 10K/50K/100K/1M/5M capacity, p95 latency, CPU/RAM/disk, cost, and operability.
9. Backup/restore, rollback, source freshness, and maintainability.
10. Compatibility with RusaAi Memory & Knowledge, Context Manager, Orchestrator, and shared Model Access Gateway.

## 5. RUSA AI operating constraints

- The 5,000,000 target counts distinct, source-grounded, deduplicated, reviewed, permission-scoped knowledge units. It is not a raw chunk, embedding, database-row, or SFT-example target.
- The 50,000 initial production corpus and 1,000,000,000 global platform-capacity objective remain separate.
- Training Engine SFT examples remain a separate workstream.
- Start prose chunking at 400–600 tokens, evaluate 50–80 token overlap only where needed, retrieve 3–6 chunks initially, and expand to 6–10 only when evidence is insufficient.
- The 16 GB Windows 11 / Intel Core i5 CPU baseline allows one active LLM generation, up to three pending inference requests, and at most two lightweight indexing workers until measured otherwise.
- Do not use the constrained interactive device as the assumed full 5M batch-processing environment. Use a separately budgeted batch environment or approved remote workers with bounded resource controls.
- MASTER_CONTEXT.md, secrets, private messages, unclear-rights sources, no-RAG sources, and synthetic filler are excluded from the product corpus.

## 6. Approval and supersession

A final decision requires a reviewed ADR update with:

- explicit selected option and rejected alternatives;
- architecture, security, data-governance, and operations approvals;
- exact repository commit SHAs and migration inventory;
- target-database read-only reconciliation;
- threat model and cross-tenant test evidence;
- migration/cutover/rollback plan;
- benchmark and evaluation evidence.

No implementation branch, passing unit test, repository presence, or historical live-schema snapshot alone constitutes approval.
