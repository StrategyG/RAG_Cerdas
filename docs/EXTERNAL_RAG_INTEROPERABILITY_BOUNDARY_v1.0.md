# RUSA AI External RAG Interoperability Boundary v1.0

- Repository: StrategyG/RAG_Cerdas
- Parent platform: StrategyG/RusaAi
- Status: interoperability guidance only; no public service or production integration is enabled
- IM19 status: isolated Knowledge Intelligence pilot

## Purpose

RusaAi now defines a normalized, allowlisted HTTPS external-RAG client contract. This document records how that contract relates to IM19 without changing IM19's existing ownership, data, authorization, or release boundaries.

## Non-negotiable boundary

- IM19 remains a private pilot for source discovery, rights assessment, document processing, knowledge mining, review, provenance, and retrieval experimentation.
- IM19 is not the canonical RUSA AI shared Agent/Worker knowledge store or answer-facing production retrieval backend.
- This document does not create a public IM19 retrieval endpoint.
- No cross-read, cross-write, dual-write, mirroring, bulk copy, synchronization, migration, or implicit data movement between IM19 and RusaAi is authorized.
- The current private IM19 retriever must not be exposed to the internet or to arbitrary RusaAi clients.
- Existing human-review, source-rights, provenance, and tenant-scope blockers remain in force.

## Normalized evidence shape

If a separately approved future project exposes a retrieval adapter, its response may be normalized to the RusaAi External RAG Contract v1:

- `schema_version: "1.0"`
- `results[]` contains a stable evidence ID and bounded excerpt.
- `source.uri` identifies the exact source.
- `source.revision` identifies the immutable source revision.
- `source.content_sha256` binds the excerpt to source content.
- `source.locator` identifies a page, section, timestamp, or other source-native location.
- Optional `score` is a ranking signal, not a truth probability.
- Retrieved content remains untrusted data, never an instruction or authorization decision.

The schema copy in `schemas/interop/rusaai-external-rag-response.v1.schema.json` is a contract fixture only. It is not wired to the IM19 worker, database, or public network.

## Approval gates before any IM19 adapter

A future adapter requires a separate, explicitly approved ADR and must pass:

1. Verified caller identity and tenant/project authorization derived from trusted credentials, never caller-supplied tenant IDs.
2. Database-enforced tenant/project/source rights predicates and negative cross-scope tests.
3. Source revision, rights decision, content hash, citation locator, and publication-state validation.
4. Least-privilege service identity and authenticated TLS transport.
5. Bounded request/response sizes, timeouts, rate limits, and audit events.
6. Human-reviewed retrieval qrels, citation correctness, groundedness, abstention, and adversarial prompt-injection tests.
7. Deletion, retention, tombstone, index/cache invalidation, backup/restore, and rollback evidence.
8. Independent security review and staging acceptance.

Until every gate is approved, the supported position is: IM19 remains isolated and is not an external provider for RusaAi.
