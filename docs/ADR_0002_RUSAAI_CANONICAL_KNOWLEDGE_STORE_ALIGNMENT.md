# ADR-0002 — RAG_Cerdas Alignment with the RusaAi Canonical Knowledge Store

- **Status:** Adopted for architecture/documentation alignment; production activation remains NOT APPROVED
- **Date:** 2026-11-13
- **Decision authority:** RusaAi project-owner decision recorded in RusaAi ADR-0002
- **Scope:** RAG_Cerdas / IM19 ownership boundary within the RUSA AI ecosystem
- **Source decision:** [StrategyG/RusaAi ADR-0002](https://github.com/StrategyG/RusaAi/blob/main/docs/adr/ADR-0002-canonical-shared-agent-worker-knowledge-store.md)
- **Source main commit verified during alignment:** `1adac8d340e5870570910168b6626fe285dd2cf2`

## 1. Context

RusaAi ADR-0002 is marked accepted by the project owner for implementation planning. It selects RusaAi PostgreSQL/pgvector `rusa_knowledge` as the canonical shared Agent/Worker knowledge store. That decision explicitly does not authorize production activation.

RAG_Cerdas ADR-0001 was written as a proposed decision and stated that no canonical shared store had been selected. That statement is now stale relative to the accepted parent-ecosystem decision. This ADR records the resulting repository alignment without changing the IM19 runtime or authorizing production data operations.

The ecosystem has three distinct ownership domains:

- **RusaAi — Control Plane and canonical shared knowledge:** agent/task orchestration, policy, identity context, tool gateway, and the canonical shared Agent/Worker knowledge store.
- **RusaModels — Model Plane:** model registry, immutable artifacts, inference, embeddings, conversion, and quantization.
- **RAG_Cerdas / IM19 — isolated Knowledge Intelligence pilot:** source discovery, rights assessment, document processing, knowledge mining, review, provenance, and retrieval experimentation.

## 2. Decision

1. RusaAi `rusa_knowledge` is the selected canonical shared Agent/Worker knowledge store, subject to its implementation and release gates.
2. RAG_Cerdas / IM19 remains an isolated Knowledge Intelligence pilot and is not the canonical production writer or answer-facing retrieval backend under the current decision.
3. IM19 must not perform cross-read, cross-write, dual-write, mirroring, bulk synchronization, or bulk copying with RusaAi `rusa_knowledge`.
4. IM19 must not be exposed as a public or multi-tenant production retrieval API under this ADR.
5. RusaModels is the only production Model Plane. RusaAi uses its authenticated Model Server API. IM19's existing `local_model.py` GGUF/CPU adapter is a pilot-local experimental runtime only; it is not a second production Model Plane and has no access to RusaModels private artifacts, credentials, databases, or runtime ports. Whether future IM19 pilot inference remains local or uses RusaModels through a separately approved authenticated, versioned service contract is an OPEN_DECISION. Repositories must not access one another's private databases, artifact credentials, or internal filesystem paths.
6. SQLite/FTS5 remains device-local state and local full-text retrieval. It is not a second writer or replica of the canonical shared corpus.
7. This ADR records architecture/documentation alignment only. It does not authorize production migration, DDL, ingestion, embedding, source mutation, data transfer, API exposure, deployment, or production activation.

## 3. IM19 operating boundary

Until a separately approved integration decision exists:

- Keep IM19 data stores and workers isolated from the RusaAi canonical store.
- Keep the current GGUF/CPU adapter in `local_model.py` confined to the IM19 pilot; it is not a shared or production model service. Do not fetch RusaModels artifacts or call private RusaModels runtime ports from IM19. A future move to the RusaModels API requires a separate approved contract and security review.
- Continue only approved pilot work using authorized sources and controlled test/staging data.
- Preserve exact source revision, content hash, provenance, rights state, reviewer evidence, and audit history.
- Keep source discovery, candidate, reviewed, approved, embedded, indexed, and published counts distinct.
- Treat rights withdrawal quarantine and permanent purge as different operations.
- Do not claim tenant-safe multi-tenant service capability while tenant/project scope is not enforced by the database and independently tested.
- Do not treat logical AI reviewer roles as independent human approval.

## 4. Conditions for any future integration

Any future IM19-to-RusaAi integration requires a new or explicitly superseding approved ADR and, at minimum:

1. Versioned authenticated API contract with named owner and consumers.
2. Trusted principal and tenant/project authorization derived from verified identity.
3. Database-enforced scope and cross-tenant negative tests.
4. Source-rights, retention, provenance, and publication-state mapping.
5. Explicit data ownership and transfer semantics; no implicit dual-write.
6. Idempotency, retry, deletion, purge, and reconciliation behavior.
7. Threat model, security review, human approval, and audit coverage.
8. Human-reviewed retrieval and citation evaluation.
9. Migration, rollback, backup, and operational evidence.
10. Project-owner approval before any production-impacting action.

## 5. Consequences

- RAG_Cerdas ADR-0001 is superseded for ecosystem-level canonical-store selection; its comparative analysis remains historical reference material.
- RAG_Cerdas roadmap v1.2 is the current IM19 roadmap and must describe IM19 as an isolated pilot under this boundary.
- Production readiness remains NO-GO until all applicable security, data-integrity, quality, reliability, and release gates pass.
- The accepted canonical-store architecture does not imply that the canonical store has been migrated, populated, deployed, or activated.

## 6. Explicit non-decisions

This ADR does not:

- Decide whether IM19's pilot-local GGUF/CPU runtime remains in place or is replaced by an authenticated RusaModels Model Server integration.

- Approve a specific embedding model, vector dimension, or production model artifact.
- Approve migration or transfer of IM19 data into RusaAi.
- Approve cross-system reads/writes, replication, mirroring, or dual-write.
- Approve public IM19 API exposure or multi-tenant production operation.
- Approve bulk ingestion, source mutation, production DDL, or deployment.
- Certify retrieval quality, corpus capacity, or production readiness.

**Final decision:** RusaAi `rusa_knowledge` is the selected canonical shared Agent/Worker knowledge store for the ecosystem. RAG_Cerdas / IM19 remains an isolated pilot. Production activation and all cross-system data operations remain blocked pending their own approvals and evidence.
