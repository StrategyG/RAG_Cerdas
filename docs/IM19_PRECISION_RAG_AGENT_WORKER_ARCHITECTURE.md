# IM19 Precision RAG — Agent/Worker Architecture and Production Plan

**Document ID:** IM19-PRECISION-RAG-AGENT-WORKER-001  
**Version:** 1.0  
**Status:** PROPOSAL — DESIGN ONLY; NOT IMPLEMENTED; NOT PRODUCTION-APPROVED  
**Repository baseline:** StrategyG/RAG_Cerdas  
**Baseline main SHA:** 1ead461e76d563445d179e7d5e80c25a9ca9f059  
**Related ecosystem work:** RusaAi PR #116 (Agent Runtime candidate), RusaAi PR #120 (precision Agent/Worker framework and 5M knowledge program), RAG_Cerdas PR #28 (canonical-store ADR alignment)

---

## 1. Purpose

Define a precise, evidence-first architecture for extending IM19 into a governed Precision RAG capability coordinated by Agents and executed by bounded Workers.

The target is a system that can:

- discover and process approved knowledge sources;
- preserve exact source, version, rights, page/locator and content-hash provenance;
- extract structured knowledge without treating model output as verified truth;
- retrieve evidence through hybrid search, ranking and controlled context expansion;
- produce citation-bound answers and abstain when evidence is insufficient;
- coordinate multi-step work through durable tasks, checkpoints and policy gates;
- recover safely from retries, worker crashes, source changes and partial failures;
- demonstrate retrieval quality, security, reliability and capacity using reproducible evidence.

This document is a RAG-specific architecture proposal. It does not authorize code activation, data movement, database migration, bulk ingestion, production deployment or cross-repository synchronization.

## 2. Architecture boundaries

### 2.1 RusaAi — Control Plane

RusaAi owns the ecosystem-level control plane:

- trusted identity and tenant context;
- Agent and capability registry;
- planning, task decomposition and DAG orchestration;
- durable task queue, scheduling, worker leases and checkpoints;
- policy evaluation, RBAC, approval and audit;
- tool gateway and sandbox boundary;
- shared model-access gateway;
- canonical shared Agent/Worker knowledge-store ownership.

The RusaAi Agent Runtime in PR #116 is the current implementation candidate. It is a draft PR, not mainline production functionality. Do not create a competing ecosystem-wide registry, DAG executor, task queue, lease service or checkpoint system inside RAG_Cerdas.

### 2.2 RusaModels — Model Plane

RusaModels owns model artifacts, immutable model manifests, model registry and release lifecycle, inference runtime, embedding runtime, quantization and model evaluation.

IM19 must call approved model capabilities through the versioned service contract selected by the ecosystem. It must not manage or publish production model artifacts independently.

### 2.3 RAG_Cerdas / IM19 — Knowledge Intelligence

IM19 owns the isolated knowledge-intelligence pilot:

- read-only source discovery;
- source-rights and processing-access checks;
- versioned document acquisition and integrity verification;
- page-aware extraction and selective OCR;
- classification and structured knowledge mining;
- AI review findings and pending relationship candidates;
- human-review workflow support;
- provenance and evidence validation;
- retrieval experimentation and retrieval evaluation.

The current IM19 private schema and retriever remain pilot-scoped. They are not a multi-tenant public knowledge API.

### 2.4 Canonical knowledge boundary

The current RUSA AI roadmap targets RusaAi's rusa_knowledge as the canonical shared Agent/Worker knowledge store. However, RAG_Cerdas ADR-0001 on main still records the canonical-store decision as unresolved, while RusaAi PR #117 and RAG_Cerdas PR #28 propose the corresponding architecture-document reconciliation.

Until the relevant ADRs are reviewed and accepted:

1. Keep IM19 and rusa_knowledge isolated.
2. Do not dual-write, cross-read, bulk-copy or synchronize knowledge between them.
3. Do not expose IM19's private retriever as a shared multi-tenant service.
4. Treat any future adapter as a separately reviewed, versioned API contract.
5. Preserve source IDs, version IDs, hashes, rights, locators and deletion lineage if an adapter is later approved.

The roadmap target is not evidence that an integration is already active.

---

## 3. Agent versus Worker responsibilities

An Agent plans and reasons within an explicitly granted capability set. A Worker performs one bounded, typed operation. Neither role can bypass the Policy Engine, human approval or data-governance lifecycle.

### 3.1 Agent rules

Agents may:

- interpret a request and propose a task plan;
- decompose a request into typed DAG nodes;
- select among already-authorized capabilities;
- analyze retrieved evidence and identify missing evidence;
- propose query refinements, comparisons and follow-up retrieval;
- summarize operational telemetry and recommend a remediation plan.

Agents may not:

- grant themselves or another Agent a capability;
- change tenant or project scope;
- approve source rights or human publication;
- mark AI-generated claims as externally verified;
- write directly to production tables or bypass a Worker contract;
- execute arbitrary shell, SQL, network or browser actions;
- convert retry or task completion into human approval.

Every proposed action must be checked by the trusted policy layer before execution.

### 3.2 Proposed RAG Agent roles

These are logical responsibilities to map to the approved RusaAi registry. They are not a new registry and are not active role grants.

| Logical Agent | Responsibility | Forbidden authority |
|---|---|---|
| Ingestion Planner | Build a source-processing plan and estimate bounded work | Grant source rights, download unrestricted content, publish |
| Query Planner | Classify query intent, identify constraints and propose query variants | Choose or override tenant identity, bypass retrieval filters |
| Evidence Analyst | Compare and synthesize only retrieved evidence | Invent missing evidence or assert external truth |
| Conflict Auditor | Identify direct, contextual, temporal, definitional and methodological differences | Convert a candidate relation into a verified contradiction |
| Citation Auditor | Check claim-to-evidence coverage and locator completeness | Manufacture citations or page numbers |
| Evaluation Coordinator | Schedule frozen evaluation runs and report coverage gaps | Create human relevance labels or change thresholds after results |
| Operations Diagnostician | Read health, queue and retrieval telemetry; propose recovery steps | Mutate production state or deploy changes |

### 3.3 Worker rules

Workers must be deterministic at the contract boundary, narrowly scoped, idempotent where possible, resource-bounded and independently observable.

Each Worker must declare:

- capability ID and contract version;
- allowed input and output schema;
- required principal and database role;
- permitted source, tenant and project scope;
- idempotency-key derivation;
- timeout, memory, CPU and output-size limits;
- retry classification and maximum attempts;
- checkpoint and lease behavior;
- audit and metric fields;
- failure, quarantine and dead-letter behavior.

Workers must not trust tenant IDs, actor IDs, reviewer IDs, source paths or permissions supplied in an untrusted task payload.

### 3.4 Proposed Worker capabilities

| Worker | Bounded operation | Existing IM19 implementation surface |
|---|---|---|
| Source Discovery | Read allowlisted source metadata and advance an atomic cursor | knowledge_mining/dropbox_discovery.py |
| Rights Preflight | Read the exact-version rights and processing-access state | storage/postgres.py and source-rights migrations |
| Download Integrity | Fetch the pinned revision and verify provider block hash and whole-file SHA-256 | knowledge_mining/dropbox_discovery.py |
| Parse/OCR | Extract PDF/EPUB structure and route eligible PDF pages to bounded OCR | knowledge_mining/document_processor.py |
| Chunk and Locator | Produce stable, version-bound chunks with page/spine locators | document_processor.py and contracts.py |
| Classification | Apply the configured hierarchical multi-label taxonomy | knowledge_mining/classifier.py |
| Knowledge Mining | Extract typed claims/units with exact source-evidence binding | knowledge_mining/mining_engine.py |
| Deduplication | Identify exact duplicates and produce near-duplicate candidates for review | Existing exact-hash checks; semantic dedup requires further implementation/evaluation |
| Provenance Validator | Validate source version, hash, chunk, locator and evidence relationships | contracts.py and storage/postgres.py |
| AI Review | Run bounded logical review rubrics and create unverified findings | knowledge_review/review_engine.py |
| Human Approval Gate | Verify a separate human decision bound to an immutable review run | Database approval and reviewer-principal controls; not an AI Worker |
| Embedding | Generate vectors using a pinned local model identity and dimension | local_model.py and retrieval.py |
| Index/Publication | Index only eligible approved versions and verify read-back | storage/postgres.py and publication gate |
| Retrieval | Execute scoped lexical and dense candidate retrieval | retrieval.py |
| Reranking | Rerank a bounded candidate set using an approved model | Optional injected reranker; quality and performance remain unverified |
| Citation Validation | Resolve every citation to the exact source version and locator | Retrieval/evaluation contracts; answer-level validator requires completion |
| Evaluation | Run frozen suites and report only human-reviewed relevance metrics | evaluation.py and benchmark.py |
| Reconciliation | Compare job checkpoints, stored artifacts and index state | Existing stage/read-back mechanisms; full operational reconciliation needs validation |
| Purge | Execute an approved retention/deletion plan across all derived stores | NOT IMPLEMENTED as a complete audited purge workflow |

Human approval is a separate authenticated action, not a model role and not an automatic Worker success state.

---

## 4. End-to-end workflows

### 4.1 Governed ingestion DAG

The target ingestion plan is:

1. DISCOVER_SOURCE
2. VALIDATE_SOURCE_SCOPE
3. CHECK_PROCESSING_ACCESS_AND_RIGHTS
4. FETCH_PINNED_REVISION
5. VERIFY_SOURCE_HASHES
6. EXTRACT_DOCUMENT_STRUCTURE
7. OCR_ELIGIBLE_PAGES
8. CHUNK_AND_BIND_LOCATORS
9. EXACT_AND_NEAR_DUPLICATE_CHECK
10. CLASSIFY_AND_MINE_KNOWLEDGE
11. VALIDATE_PROVENANCE_AND_EVIDENCE
12. RUN_BOUNDED_AI_REVIEW
13. WAIT_FOR_DISTINCT_HUMAN_APPROVAL
14. GENERATE_PINNED_EMBEDDINGS
15. BUILD_OR_UPDATE_INDEX
16. VERIFY_INDEX_READ_BACK
17. PUBLISH_ELIGIBLE_VERSION
18. RECONCILE_AND_AUDIT

Required controls:

- Rights are checked before download and rechecked before each processing stage.
- Every stage binds to an immutable source revision and content hash.
- A changed source creates a new version; it must not silently reuse stale embeddings.
- A Worker cannot approve its own output.
- AI review output remains unverified.
- A human decision binds to an immutable review_run_id and authenticated reviewer principal.
- Publication fails closed if rights, review, approval, evidence or embedding completeness is missing.
- A later rights hold/reject removes the version from retrieval; this quarantine is not equivalent to erasure.
- No bulk ingestion or production publication occurs without separate approval.

### 4.2 Precision retrieval and grounded-answer DAG

The target query workflow is:

1. AUTHENTICATE_REQUEST
2. DERIVE_TRUSTED_SCOPE
3. CLASSIFY_QUERY_INTENT
4. NORMALIZE_AND_EXPAND_QUERY
5. APPLY_RIGHTS_AND_PUBLICATION_FILTERS
6. RUN_LEXICAL_RETRIEVAL
7. RUN_DENSE_RETRIEVAL
8. FUSE_RANKINGS
9. OPTIONAL_BOUNDED_RERANK
10. EXPAND_REVIEWED_CONTEXT
11. VALIDATE_EVIDENCE_AND_LOCATORS
12. ASSEMBLE_BUDGETED_EVIDENCE
13. GENERATE_GROUNDED_ANSWER
14. VALIDATE_CLAIM_TO_CITATION_SUPPORT
15. RETURN_ANSWER_OR_ABSTAIN
16. RECORD_RETRIEVAL_AND_ANSWER_EVIDENCE

The current IM19 retriever has a useful foundation:

- PostgreSQL GIN lexical candidate retrieval using ts_rank_cd with the simple text-search configuration;
- 384-dimensional pgvector HNSW dense retrieval;
- bounded retrieval of up to 50 lexical and 50 dense candidates;
- Reciprocal Rank Fusion (RRF);
- optional injected reranking;
- graph expansion limited to reviewed relationships;
- metadata filters and source citations;
- query embedding before opening the database transaction.

Important precision notes:

- The current lexical score is ts_rank_cd, not BM25.
- The Python BM25 helper is an offline reference helper, not the production retrieval path.
- RRF improves rank fusion; it does not prove relevance.
- A reranker must be evaluated against the same frozen, human-reviewed query set before activation.
- Graph expansion must never traverse pending AI-generated relations.
- Retrieval returns evidence candidates, not verified truth.
- The current IM19 retriever remains a private worker interface and must not be exposed as a multi-tenant public API.

The initial context policy should use a small bounded evidence set, with expansion only when the evidence validator finds a specific gap. The RUSA CPU-first design's 3–6 initial chunks and 8K context budget are starting constraints to benchmark, not universal quality guarantees.

### 4.3 Answer contract

Every answer-facing result should preserve:

- query ID and trace ID;
- retrieval configuration and version;
- source document ID and immutable source-version ID;
- source revision and content SHA-256;
- chunk ID and exact page or EPUB locator;
- quoted supporting evidence;
- ranking/fusion metadata needed for audit;
- verification status;
- rights/publication eligibility at retrieval time.

The answer layer must distinguish:

- source-backed statement;
- inference derived from cited evidence;
- conflicting source statements;
- assumption;
- unknown or unsupported statement.

If evidence is absent, contradictory without adequate context, stale, not permitted or insufficiently relevant, the system must abstain or clearly qualify the answer. It must not fabricate a page, citation or confidence score. AI approval does not change NOT_EXTERNALLY_VERIFIED into externally verified truth.

---

## 5. Durable task and Worker execution contract

The ecosystem task queue and DAG runtime should be owned by RusaAi. IM19 should expose only approved, versioned capability contracts after architecture and security review.

A RAG task envelope should contain, at minimum:

- schema_version;
- task_id and root_task_id;
- capability_id and capability_version;
- request_id and trace_id;
- authenticated actor/service principal reference;
- trusted scope reference derived by the control plane;
- idempotency_key;
- input reference and input digest;
- source_id, source_version_id and source_hash when applicable;
- policy_decision_id;
- deadline_at and resource budget;
- attempt and maximum_attempts;
- lease owner, lease token and expiry;
- monotonic checkpoint version;
- output reference and output digest when complete.

The caller must not be able to choose its own trusted tenant, project, reviewer or privilege context. If a scope cannot be verified, the task is rejected.

### 5.1 Task states

Use explicit states:

- QUEUED
- CLAIMED
- RUNNING
- WAITING_FOR_HUMAN_APPROVAL
- RETRY_WAIT
- SUCCEEDED
- FAILED
- DEAD_LETTER
- CANCELLED
- SUPERSEDED

Only declared transitions are valid. A failed dependency blocks downstream DAG nodes. A retry never implies approval.

### 5.2 Reliability invariants

- Use at-least-once delivery with idempotent handlers; do not claim exactly-once side effects.
- Every write is fenced by the current lease token and task identity.
- Checkpoints advance monotonically using compare-and-set or an equivalent atomic mechanism.
- A stale Worker cannot commit after lease expiry or replacement.
- Retry only transient failures, with bounded exponential backoff and jitter.
- Permanent schema, rights, integrity and authorization failures go to a terminal or review state.
- Before retrying an ambiguous external side effect, read back and reconcile its idempotency key and expected digest.
- Cancellation prevents subsequent writes and is propagated to in-flight work where supported.
- Worker completion requires durable output read-back, not merely a successful process return code.

---

## 6. Knowledge quality and deduplication

A knowledge unit is eligible for production only when its lineage is complete:

- permitted source and exact source revision;
- content hash and parser/chunker versions;
- stable chunk and locator identity;
- source-bound evidence;
- classification and knowledge type;
- duplicate decision;
- review findings and risk state;
- separate human approval where required;
- embedding model identity, version, dimension and digest;
- index generation and publication state.

Exact-hash duplicate detection is not semantic equivalence. Near-duplicate detection must produce reviewable candidates and be evaluated for precision and recall. Do not delete or merge source records solely because an AI similarity score is high.

The 5,000,000 target counts distinct, source-grounded, deduplicated, reviewed and permission-scoped knowledge units. It is not a count of raw passages, embeddings, repeated chunks, prompts or database rows.

Report each lifecycle count separately:

- discovered sources;
- raw candidate units;
- unique candidate units;
- reviewed units;
- approved units;
- embedded units;
- indexed units;
- production-published units;
- quarantined, superseded and tombstoned units.

---

## 7. Evaluation and acceptance criteria

No retrieval or answer-quality score is valid without a frozen dataset and genuinely human-reviewed relevance judgments.

### 7.1 Required retrieval metrics

- Precision@K
- Recall@K
- MRR@K
- nDCG@K
- citation/page/locator accuracy
- answer evidence-support rate
- unsupported factual-claim rate
- abstention precision and recall
- contradiction detection precision and recall
- stale-version and rights-filter leakage
- cross-tenant leakage
- p50/p95/p99 retrieval latency and throughput

Report results by language, domain, document type, OCR status, query type and source trust tier. Aggregate averages must not hide a weak category.

### 7.2 Evaluation evidence

Every run must retain:

- dataset ID, version and SHA-256;
- human reviewer identity and immutable review record;
- corpus snapshot/version;
- code commit SHA;
- embedding model artifact digest;
- prompt and evaluator versions;
- retrieval filters, candidate limits, RRF parameters and reranker identity;
- raw per-case outcome and final report artifact digest.

AI-generated relevance labels, synthetic fixtures and an editable reviewer_id string are not human evaluation evidence.

### 7.3 Proposed pilot thresholds

The existing production-readiness gate proposes the following pilot targets:

- Recall@5 >= 0.85;
- citation page accuracy >= 0.95;
- zero unsupported factual answers on the unanswerable test set.

These are proposed acceptance thresholds, not current measured results. Owners and human evaluators must approve the final thresholds before the held-out test is run. Thresholds must not be relaxed after observing results.

The current evaluation contract reports three cases without human-reviewed relevance labels. Therefore retrieval quality remains BLOCKED / NOT SCORED. No metric should be fabricated.

---

## 8. Security, governance and production blockers

The following are release gates, not optional enhancements.

### P0 — Identity and isolation

- Derive actor and scope from a trusted authenticated principal.
- Implement tenant/project authorization at the API and database boundaries.
- Add negative tests for search, metadata, graph expansion, job claims, review, approval, audit, export and deletion across tenants.
- Keep the IM19 private worker interface isolated until tenant-aware authorization is proven.
- Database reviewer-principal binding is not a substitute for SSO, MFA or end-user/API identity.

### P0 — Rights, approval and retention

- Preserve exact-version rights decisions and processing-access authorization.
- Require distinct human approval for publication.
- Keep AI reviewers separate from human approvers.
- Implement a separately privileged, audited purge/retention workflow covering blobs, extracted text, chunks, embeddings, indexes, caches and derived artifacts.
- Distinguish quarantine, tombstone, retention hold and verified erasure.

### P0 — Supply chain and sandbox

- Pin dependencies, base images, model files and embedding artifacts.
- Retain SBOM, license and vulnerability evidence.
- Review residual HIGH findings; a scanner gate using ignore-unfixed is not a zero-vulnerability result.
- Keep document text untrusted and incapable of issuing tools or policy instructions.
- Harden native parser isolation and run adversarial file/parser tests.
- Keep secrets out of source, logs, artifacts and prompts.

### P0 — Reliability and operations

- Define SLI/SLO for ingestion, retrieval, queues and Workers.
- Add structured logs, metrics, traces, alerting and operator runbooks.
- Prove restart, lease expiry, retry, cancellation, dead-letter and reconciliation behavior.
- Test backup integrity, isolated restore and rollback.
- Run sustained staging tests on the intended hardware and database profile.

### P0 — Release governance

- Reconcile the canonical-store ADRs before cross-repository integration.
- Review exact PR base/head SHAs and CI evidence.
- Apply migrations only to an approved backup-restored staging database after schema reconciliation.
- Do not bulk-ingest or publish production data without explicit authorization.
- Production certification requires project-owner, security and operations approval.

---

## 9. Staged rollout

Use the RusaAi 5M program's evidence-gated progression. Do not advance based on raw row counts.

| Stage | Corpus milestone | Required proof |
|---|---:|---|
| P0 | 1K–5K | Contracts, source rights, locator accuracy, human-reviewed gold set |
| P1 | 25K | Parser coverage, deduplication precision, quality calibration, replay |
| P2 | 100K | Domain/language retrieval evaluation, tenant and rights isolation |
| P3 | 500K | Throughput, backpressure, index rebuild, recovery and cost |
| P4 | 1M | SLOs, monitoring, backup/restore, rollback and independent security review |
| P5 | 5M | Sustained load/soak, retrieval non-regression, full lineage, capacity and cost proof |

The 50K initial production corpus and the 1B global platform-capacity objective are separate milestones. Neither is implied by this IM19 proposal.

---

## 10. Implementation sequence and dependency gates

This plan maps to the RUSA AI ecosystem roadmap. It does not bypass its dependency graph.

| Work package | Scope | Dependency / exit gate |
|---|---|---|
| RAG-AW-00 | Reconcile current main, open PRs, ADRs, source files and exact CI evidence | Baseline inventory accepted |
| RAG-AW-01 | Align RusaAi and RAG_Cerdas canonical-store ADRs and ownership | Architecture decision accepted; no unresolved conflict |
| RAG-AW-02 | Complete identity, tenant/project scope and least-privilege contract | Cross-tenant negative tests pass |
| RAG-AW-03 | Close rights, reviewer, approval, retention and purge lifecycle | Exact-version and deletion tests pass |
| RAG-AW-04 | Map IM19 bounded capabilities to the approved RusaAi Agent/Worker runtime | Runtime PR reviewed; policy and adapters verified |
| RAG-AW-05 | Complete Precision RAG retrieval, reranking, answer and citation evaluation | Human-reviewed held-out benchmark passes |
| RAG-AW-06 | Run representative staging load, restart, restore and rollback tests | Operational SLO and DR evidence passes |
| RAG-AW-07 | Assemble production evidence dossier and obtain owner approvals | Explicit GO decision |

Do not create a parallel Agent Runtime in RAG_Cerdas. PR #116 is the current RusaAi candidate to review; PR #120 contains the candidate framework and five-million knowledge program. Both remain unmerged draft work at the time of this document.

---

## 11. Current evidence and honest status

The following findings are based on source inspection and repository documentation at the recorded main SHA. They are not live staging or production measurements.

| Area | Current evidence | Status |
|---|---|---|
| Document discovery and versioning | IM19 discovery and source-version modules exist | IMPLEMENTED; live provider verification required |
| PDF/EPUB extraction and selective PDF OCR | Parser and OCR path exists | TESTED on fixtures; real-corpus completeness not measured |
| Structured knowledge mining | Fourteen knowledge types and exact quote binding exist | TESTED on fixtures; entailment precision not measured |
| Logical AI review | Five review roles and explicit unverified status exist | TESTED on fixtures; reviewers are not statistically independent |
| Human reviewer principal | Reviewer registry and role-guard migrations are present in the current repository line | Verify exact-main CI and target identity deployment; not SSO/MFA |
| Rights and publication | Exact-version rights and publication gates exist | Quarantine exists; complete purge/retention remains open |
| Hybrid retrieval | GIN lexical, HNSW dense, RRF and optional reranker exist | Code-level/CI evidence exists; staging quality and capacity not verified |
| Retrieval evaluation | Human-reviewed evidence contract exists | BLOCKED: current cases lack human-reviewed qrels |
| Tenant isolation | IM19 schema lacks tenant/project predicates in the documented baseline | BLOCKED for multi-tenant exposure |
| Worker recovery | Durable stage machine, leases and checkpoints exist | Fixture/disposable-DB tests do not prove long-running target reliability |
| 5M scale | Read-only benchmark harness and staged plan exist | NOT VERIFIED; no representative staging capacity run |
| Production deployment | Container/Compose example and runbook exist | NOT DEPLOYED / NOT CERTIFIED |

### Known documentation reconciliation

The mainline documentation contains historical status statements that need reconciliation against later code:

- IM19 architecture/security documents still contain older reviewer-registry status wording.
- The canonical-store ADR on RAG_Cerdas main still says the decision is unresolved.
- RusaAi PR #117 and RAG_Cerdas PR #28 are the current proposed documentation-alignment changes.
- The RusaAi Agent Runtime PR #116 and precision framework PR #120 are drafts, not active production services.

Update these statements only after checking the exact branch and CI evidence. Do not silently treat a draft PR as merged.

### Release decision

**PRODUCTION: NO-GO / NOT VERIFIED.**

The repository has a substantial knowledge-intelligence and hybrid-retrieval foundation. It does not yet have sufficient evidence for multi-tenant production exposure, calibrated retrieval quality, complete erasure, representative scale, target deployment, backup/restore, sustained operations or end-to-end ecosystem activation.

---

## 12. Definition of Done

This proposal is complete as an architecture design only. Implementation is complete only when all of the following are independently evidenced:

1. Every Agent and Worker maps to an approved capability and least-privilege policy.
2. RusaAi owns orchestration; IM19 executes only approved bounded capabilities.
3. No unauthorized cross-read, cross-write or dual-write exists.
4. Every published knowledge unit has source, version, rights, evidence, review, approval, embedding and index lineage.
5. Retrieval filters enforce trusted scope, rights and publication state.
6. Retrieval and answer quality pass frozen, human-reviewed held-out evaluation.
7. Citations resolve to the exact source version and page/locator.
8. Unanswerable, conflicting, stale and unauthorized queries fail closed.
9. Workers recover from crash, lease replacement and retry without stale or duplicate side effects.
10. Tenant isolation, parser security, dependency security and reviewer separation pass.
11. Retention, purge, backup, restore and rollback are proven in staging.
12. Capacity and cost are measured at each approved rollout stage.
13. Exact commit, CI, benchmark and deployment evidence are retained.
14. Project, security and operations owners explicitly approve production activation.

**No role activation, production data publication, migration, deployment or production-ready claim is authorized by this document.**
