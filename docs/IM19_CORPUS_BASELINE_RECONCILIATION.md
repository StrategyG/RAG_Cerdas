# IM19 / RUSA AI corpus baseline reconciliation

- **Snapshot:** 2026-11-12
- **Status:** Read-only reconciliation of the existing Dropbox planning and governance records
- **No ingestion or database mutation performed**

## 1. Counting rules

The RUSA AI Agent & Worker 5M plan defines 5,000,000 as distinct, source-grounded, deduplicated, reviewed, permission-scoped knowledge units. It is not a count of raw fragments, repeated passages, prompts, embeddings, database rows, vector points, or synthetic filler.

Keep these program targets separate:

| Target | Unit and purpose |
|---:|---|
| 50,000 | Initial production corpus target measured in eligible chunks |
| 100,000 | Earlier Dropbox knowledge-manifest planning target; not a verified current corpus |
| 5,000,000 | Agent/Worker distinct eligible knowledge-unit target |
| 1,000,000,000 | Separate global platform-capacity objective |
| 10,000–20,000 | Separate Training Engine SFT pilot examples; not RAG corpus units |

Do not add the targets together or use one as evidence that another has been reached.

## 2. Existing candidate ledger

The Dropbox master-ledger and 100K audit records establish the following working state:

| Item | Recorded state | Treatment |
|---|---:|---|
| Raw candidate IDs through Batches 001–022 and 026–027 | 784 | Preserve as the existing raw-ID ledger count; not a unique or approved count |
| Canonical namespace line in the ledger control block | RUSA-KB-001–653 | Stale/inconsistent with the 784 executive and batch totals; reconcile the ledger before treating the range as authoritative |
| Alternate Batch 016 bank | 50 candidate records, IDs 639–688 | Quarantine; IDs collide with canonical Batch 016, 017, 018, and early Batch 019 ranges |
| Domain-reference candidates in Batches 017–022 and 026–027 | 131 | Tagged memory_knowledge / not_worker; keep in separate domain collections, not Worker runtime knowledge |
| Batch 029 provisional source-paraphrase notes | 31, provisional IDs RUSA-KB-785–815 | Do not add to canonical count until rights, exact/near-duplicate, technical, and human review pass |
| Batches 023–025 | 7 source records, 0 candidate chunks | Source/rights/quality tracking only |
| Batch 027 | 3 source records, 27 candidate chunks | Included in the 784 raw candidate accounting; review and dedup still required |

### Ledger integrity issue

The Dropbox file is named “RUSA AI Master Knowledge Ledger v1.4 — Batches 001–016”, while its body heading says “v2.3 — Batches 001–027”, its control block says ledger version 1.4, and the canonical namespace line still ends at 653 while the executive and batch tables report 784. The separate 100K audit explicitly calls out this discrepancy.

**Required action:** reconcile the ledger title, version, batch coverage, canonical ID range, and batch accounting in one reviewed revision. Do not renumber or ingest the alternate 50 records as if they were canonical. Any surviving alternate records must receive new IDs only after duplicate review and approval.

## 3. Review, embedding, and publication status

The 100K audit and Batch 029 record state that:

- Human review and approval for the current candidate bank are pending; the Batch 016 audit records zero human-approved current candidates.
- The 31 Batch 029 notes are provisional and not approved.
- Candidate embeddings and vector-index writes from the documentation batches are recorded as zero.
- Production publication authorizations are recorded as zero.
- Exact and near-duplicate reconciliation against the 784 raw candidates is pending.
- The 131 memory_knowledge / not_worker records are not Worker runtime knowledge and require separate domain policy.

These are Dropbox-recorded statuses, not a live database query. They must be reconciled with a fresh read-only export before any production count is reported.

## 4. Dropbox root library and rights boundary

The 50K inventory and rights registers report a root-library snapshot of 384 Dropbox entries: 382 files (359 PDFs and 23 MP4 videos), approximately 4.28 GB / 3.98 GiB raw.

The 2026-11-11 owner attestation states that the user has rights/licences for internal RAG storage, extraction, embeddings, and derived chunking across the listed library. The file-level rights register records that declaration as sufficient for **controlled internal extraction and candidate preparation**. It is not independent legal verification, and the same register requires supporting licence/permission evidence, per-source terms, attribution, and conflict review before production publication. Explicit no-RAG-storage restrictions remain on hold.

Additional source-register facts:

- 22 title-similarity groups are filename-derived candidates, not proven exact duplicates. Raw-file SHA-256 and extracted-text similarity have not yet been reconciled for those groups.
- Z-Library/Z-Lib, PDFDrive, PDFCoffee, and OceanofPDF filename markers are provenance flags, not legal findings; they require source-level evidence and conflict review.
- A 50K inventory update records 25 distinct PDFs extracted: 17 used as candidate-chunk sources, two test-only, one diagram-heavy PDF quarantined, four books on explicit publisher-rights hold, and one crypto PDF quarantined for severe OCR corruption.
- Of the 207 PDFs at or below 5 MiB, 182 remain unextracted. The 152 larger PDFs and 23 videos require an alternate approved processing route.
- Raw file bytes do not establish extractable-text yield, rights eligibility, unique knowledge yield, or production readiness.

**Operating rule:** controlled internal extraction may proceed only within the owner-attested scope and per-file controls. No bulk production ingestion or publication is authorized by file presence or owner attestation alone. Respect explicit no-RAG holds, quarantine conflicts, and retain file-level rights and deletion lineage.

## 5. Internal RUSA source overlap

The 50K inventory records that the supplied RUSA product architecture documents overlap previously mined batches and were already recorded as deduplicated in Batch 015. Re-ingest only material deltas after source-version, source-span, and content-hash comparison.

MASTER_CONTEXT.md is project operating context, not product knowledge, and is excluded from RAG. Do not turn operating instructions, secrets, private messages, or project-only context into product corpus records.

## 6. Canonical-store and schema boundary

The current repositories contain different operational knowledge implementations:

- RusaAi main contains an optional PostgreSQL/pgvector knowledge service with tenant_id/collection scope and forced tenant RLS.
- RAG_Cerdas IM19 contains source-version, provenance, review, approval, job, graph, and 384D embedding structures, but the current IM19 schema has no tenant_id columns or per-tenant RLS predicates; its worker policy is private-role scoped.

ADR-0001 remains **Proposed**. No canonical operational store has been selected. Until the architecture, security, data-governance, and operations owners approve a superseding ADR:

- keep both stores isolated;
- do not dual-write, cross-read, bulk-copy, or cut over;
- do not expose IM19 as a multi-tenant API;
- do not infer that historical database rows belong to the 784 candidate IDs;
- reconcile the target database schema and migration history read-only before any DDL.

A historical 2026-11-04 Dropbox snapshot reports 26,186 rows in rag.chunks, 682 embeddings present, 25,504 missing, and 669 unpublished institutional_rag.knowledge_candidates. These are historical values only; the current live database was not queried in this reconciliation. They are not added to the 50K or 5M counts.

## 7. Current count ledger

| Stage | Count/status at this snapshot | Evidence boundary |
|---|---:|---|
| Raw candidate IDs | 784 | Dropbox ledger/audit; header/range inconsistency remains |
| Alternate ID collisions | 50 | Quarantined; not canonical |
| Provisional Batch 029 notes | 31 | Not included in 784; review pending |
| Domain-only memory_knowledge / not_worker | 131 | Separate collection and policy |
| Deduplicated unique eligible units | Not established | Exact/near-duplicate review pending |
| Human-reviewed / approved | 0 recorded for Batch 016; no complete 784-wide review evidence | Must reconcile the full ledger |
| Embedded | 0 recorded for documentation batches | Not a live DB count |
| Indexed | 0 recorded for documentation batches | Not a live DB count |
| Production-published | 0 recorded authorizations | No production publication evidence |

The counts above describe different overlapping dimensions; do not sum them. A candidate can be in the raw-ID ledger and also be a domain-only item. The 50 alternate records and 31 provisional notes must not be added to the 784.

## 8. Next safe work sequence

1. Reconcile the master ledger metadata and the 784 ID range; preserve the alternate 50 in quarantine.
2. Reconcile the 131 domain-only records into separate collections and confirm whether their consumer agents are in approved scope.
3. Reconcile Batch 029 source terms, rights, provenance, and exact/near duplicates before assigning canonical IDs.
4. Continue file-level rights and extraction-status updates for the Dropbox root library; retain explicit no-RAG and publisher holds.
5. Perform exact raw-file and extracted-text hashing before selecting canonical editions.
6. Complete human review, publication authorization, and source-to-derived-record deletion lineage.
7. Select the canonical operational store through ADR-0001 and a reviewed migration/contract plan.
8. Only then begin approved ingestion batches, embedding, index reconciliation, and retrieval evaluation.

## 9. Source records inspected

- [RUSA AI Master Knowledge Ledger — Dropbox Paper](https://www.dropbox.com/scl/fi/0v7gd0m7ck39oqsjly1gd/RUSA-AI-Master-Knowledge-Ledger-v1.4-Batches-001-016.paper?dl=0)
- [RUSA_AI_KNOWLEDGE_100K_AUDIT_001 — Dropbox Paper](https://www.dropbox.com/scl/fi/tqumlp697bqzvkfzs596v/RUSA_AI_KNOWLEDGE_100K_AUDIT_001.paper?dl=0)
- [Batch 029 provisional candidate bank — Dropbox Paper](https://www.dropbox.com/scl/fi/h9ex2ci8e4s1aple11jo7/RUSA-AI-Official-Agent-Platform-RAG-MCP-Candidate-Chunk-Bank-Batch-029.paper?dl=0)
- [50K source inventory and build plan — Dropbox Paper](https://www.dropbox.com/scl/fi/u1xiepr1gkl09mb6uvqmp/RUSA-AI-Production-Initial-Corpus-50K-Source-Inventory-and-Build-Plan-v1.0.paper?dl=0)
- [50K root file-level rights intake register — Dropbox Paper](https://www.dropbox.com/scl/fi/wzsyqzn4kuulecwq7is35/RUSA-AI-50K-Corpus-Dropbox-Root-File-Level-Rights-Intake-Register-v1.0.paper?dl=0)
- [50K Dropbox library source eligibility and rights register — Dropbox Paper](https://www.dropbox.com/scl/fi/zrgq9fizwq9gk62sprqgu/RUSA-AI-50K-Corpus-Dropbox-Library-Source-Eligibility-and-Rights-Register-v1.0.paper?dl=0)

This document records a read-only metadata reconciliation. It does not extract, copy, embed, index, approve, or publish Dropbox source content.
