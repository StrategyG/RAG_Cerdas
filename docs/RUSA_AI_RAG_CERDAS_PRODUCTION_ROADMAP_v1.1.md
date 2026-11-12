# RUSA AI — RAG_Cerdas / IM19 Production Roadmap v1.1

- Repository: StrategyG/RAG_Cerdas
- Parent ecosystem: StrategyG/RusaAi
- Version: 1.1.0
- Updated: 2026-11-12
- Status: Engineering roadmap; production remains BLOCKED

> RAG_Cerdas is the official knowledge-ingestion, knowledge-mining, indexing, retrieval, evidence, and evaluation engine of RUSA AI. It is not a second RAG product. RusaAi remains the control plane and consumes RAG_Cerdas through versioned, authorized contracts.

## 1. Program targets — keep counts distinct

The RUSA AI Agent & Worker 5M Hybrid Corpus Expansion Plan v1.0 defines the target as **5,000,000 distinct, source-grounded, deduplicated, reviewed, permission-scoped knowledge units**.

A raw chunk, repeated passage, prompt, embedding, database row, vector point, or generated filler is not a valid counted unit.

Keep these milestones separate:

| Target | Meaning |
|---:|---|
| 50,000 | Initial production corpus target |
| 5,000,000 | Agent/Worker knowledge-unit expansion target |
| 1,000,000,000 | Separate global platform-capacity objective |

Report each stage separately: raw candidates, unique candidates, reviewed units, approved units, embedded units, indexed units, and production-published units. Do not infer approval, publication, or retrieval activation from source registration or embedding counts.

## 2. Architecture ownership

### RAG_Cerdas / IM19 owns

- Source discovery, rights/access gate, ingestion, versioning, and source integrity.
- PDF/EPUB processing, selective OCR, page/spine provenance.
- Classification, structured knowledge mining, review findings, contradiction candidates, and knowledge graph.
- Chunking, embedding/index lifecycle, lexical/vector retrieval, reranking, evidence assembly, and retrieval evaluation.
- Durable ingestion/indexing workers, checkpoint, lease fencing, retry, and dead-letter handling.

### RusaAi control plane owns

- Supreme Orchestrator, Planner, Task Decomposer, agent registry, task queue, scheduler, and workflow lifecycle.
- Policy Engine, Tool Gateway, sandbox, approval, audit, and cross-agent authorization.
- Memory lifecycle and routing, Context Manager, and shared Model Access Gateway.
- User-facing/API boundary and versioned contracts.

RusaAi should use a thin adapter/client to RAG_Cerdas. Do not create a second source ingestion pipeline, vector index, or knowledge database in RusaAi. Record any change to this ownership boundary in an ADR.

### Security boundary

The current IM19 retriever is a private worker interface, not a multi-tenant public API. Tenant identity must come from a verified principal, not a caller-supplied tenant ID. Enforce tenant/project/source scope inside the database query and authorization boundary before public exposure. Keep the legacy unscoped Edge Function disabled until its tenant-aware successor and cross-tenant tests are approved.

## 3. CPU-first and knowledge design

- Local-first and CPU-first by default; no automatic cloud fallback for private data.
- Use the shared RUSA AI model runtime where integration contracts are available; do not load one model per agent.
- Keep background ingestion and embedding bounded so interactive inference retains its resource budget.
- RusaAi Architecture v2.0 baseline for prose: 400–600 tokens; evaluate 50–80 token overlap and apply only where adjacent context is needed.
- Initial retrieval: 3–6 chunks. Expand to 6–10 only when evidence is insufficient.
- Respect the 8,192-token context budget and dynamic Context Manager allocation.
- Preserve exact source revision, commit/blob/hash, attribution, locator, rights, tenant, classification, and verification state.
- MASTER_CONTEXT.md, credentials, private messages, unclear-rights material, no-RAG sources, and synthetic filler are excluded from product corpus.

Public source availability is not permission to archive full text. Use source-level rights review, pin revisions, preserve attribution, and store concise original notes where full-text archival is not authorized.

## 4. Phase plan

| Phase | Priority | Work | Exit evidence |
|---|---|---|---|
| R0 — Baseline/governance | P0 | Refresh main/branch/PR state; review existing PR #17 security and #15 evaluation work; define ownership ADR; synchronize docs | Exact SHA, reviewed PR dependency map, owner and acceptance criteria per issue |
| R1 — Contracts/authorization | P0 | Versioned retrieval/ingestion contract; verified principal; tenant/project scope; trace/task IDs; timeout/error envelope; cross-repo contract tests | Positive and negative authorization tests; zero cross-tenant results |
| R2 — Source integrity | P0 | OAuth least scopes; revision/block-hash/SHA256; rights gate; parser/OCR quotas; source locator; tombstone and replay semantics | Staging connector evidence; 100% published source/version/location provenance |
| R3 — Chunk/embedding/index | P0 | Versioned structure-aware chunker; stable IDs; pinned embedding artifacts; finite/dimension checks; resumable batches; atomic index generations | Reproducible replay; no mixed vector spaces; publication read-back |
| R4 — Retrieval/evaluation | P0 | Indexed lexical search; vector search; RRF; optional reranking/MMR; reviewed graph expansion; human-reviewed qrels; citation/abstention evaluation | Reviewed qrels; Recall@5, MRR@10, citation and abstention report |
| R5 — Worker and capacity | P0 | Bounded queues, bulk jobs, checkpoints, leases/fencing, backpressure, partition/index strategy, reindex and deletion lineage | 100K/500K/1M/5M staged capacity reports; recovery and resource evidence |
| R6 — Native RUSA integration | P0 | Memory & Knowledge adapter; Orchestrator task contracts; worker jobs; shared model gateway; context/evidence assembly; independent QA | End-to-end agent workflow and grounded-answer evidence |
| R7 — Operations/security | P0 | TLS/roles/RLS, adversarial parser/prompt tests, SBOM, secrets, metrics, alerts, backup/restore, rollback | Security review, restore drill, runbooks, operational dashboards |
| R8 — Release | P0 | Staging pilot, scale certification, canary, operator sign-off | All six production gates PASS; release tag and exact CI evidence |

## 5. Production gates

| Gate | Required evidence |
|---|---|
| A — Security | OAuth least-scope, verified caller identity, database-enforced tenant isolation, role/RLS review, adversarial tests, dependency/SBOM scan |
| B — Data integrity | Pinned source revision/hash, rights/access authorization, provenance, idempotent replay, target DB read-back |
| C — Knowledge quality | Human-reviewed classification, extraction, claim-evidence, contradiction, and publication benchmark |
| D — Retrieval | Human-reviewed qrels, Recall@K/MRR/nDCG, citation correctness, groundedness, abstention |
| E — Reliability | Outage/kill/restart, lease recovery, backpressure, bounded resource, soak, backup/restore |
| F — Release | Reviewed migration, built/pinned image, monitoring/alerts, rollback rehearsal, release approval |

Production is NO-GO while any mandatory gate is BLOCKED or PARTIAL. Automated tests are not proof of live provider behavior, corpus quality, or production operation.

## 6. Proposed quality targets (not measured results)

Agree final thresholds with product, QA, Security, and DevOps before release:

- Recall@5 ≥ 0.85 on human-reviewed qrels.
- MRR@10 ≥ 0.70 on human-reviewed qrels.
- Citation correctness ≥ 98%.
- Unsupported claim rate ≤ 1% on adjudicated answer tests.
- Retrieval P95 ≤ 2 seconds on the declared target workload and hardware.
- Zero cross-tenant results in the security test suite.
- 100% published units carry source/version/locator and permission lineage.

## 7. Current engineering focus

The current implementation branch moves lexical candidate retrieval from a Python full-corpus scan to PostgreSQL GIN-indexed full-text search, combines bounded lexical and pgvector candidates with RRF, and performs query embedding before opening a database transaction.

This change improves the retrieval architecture but does not certify 5-million-unit capacity. Representative load tests, tenant/project filters, target staging, human-reviewed qrels, and live integration evidence remain mandatory.

## 8. GitHub delivery rules

- Never commit directly to main.
- Use small feature branches and reviewable PRs.
- Do not apply migrations from worker startup.
- Do not run bulk ingestion, source mutation, production DDL, or deployment without explicit approval and backup/rollback evidence.
- Pin exact commit SHA, CI run, model artifact, and dataset hash for every VERIFIED claim.
- Keep secrets, private source documents, GGUF files, and model weights out of Git.
- Recheck existing open PR head SHA, base, overlap, and CI before merge.
