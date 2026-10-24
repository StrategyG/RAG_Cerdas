# Institutional RAG Release Gates

**Default release decision until every required gate passes: NO-GO for production.** A green CI run is necessary but not sufficient.

| Gate | Acceptance criteria | Evidence required | Current status (2026-10-24) |
|---|---|---|---|
| G1 Repository integrity | Reviewed working branch; current PR head and commit known; no secret material committed | GitHub commit/PR metadata, secret scan | NOT TESTED for current head |
| G2 Automated tests | Full required suite passes on the exact candidate SHA; no tests removed or weakened to hide failures | Workflow URL, exact SHA, test counts and logs | NOT TESTED for current head |
| G3 Schema contract | Canonical schema selected; all worker SQL, RPC signatures, return types, grants, indexes, and migrations match live schema | Read-only schema/function audit and migration review | FAIL: dual schema tracks require explicit reconciliation |
| G4 Corpus integrity | Every active chunk has non-empty text, source hash/provenance, valid page/time data, compatible finite embeddings, and a valid generation | Read-only integrity report | FAIL: observed 25,343 `rag.chunks` embeddings NULL and page provenance absent; 5 institutional chunks embeddings NULL |
| G5 PDF pilot | One authorized PDF passes download, page-preserving extraction, chunking, embedding, generation activation, retrieval, correct citation, retry/idempotency, and no-evidence tests | Pilot manifest, hashes, counts, query outputs, verified source pages | NOT TESTED |
| G6 Video pilot | One authorized video passes download, transcription, duration/timestamp validation, embedding, generation activation, retrieval, timestamp citation, retry/recovery, and no-evidence tests | Pilot manifest, source hash, duration, chunk/embedding counts, query outputs | NOT TESTED |
| G7 Retrieval quality | At least 30 human-reviewed cases for pilot; release target 50–100+. Indonesian and English slices. Recall@5 >= 0.85; MRR@10 >= 0.75 | Versioned reviewed dataset, qrels, reproducible evaluation output | FAIL: no reviewed evaluation cases/results observed |
| G8 Citation and grounding | Citation accuracy >= 0.95; groundedness >= 0.90; source/page/time verified against retrieved records | Human-reviewed answer/citation evaluation | NOT TESTED |
| G9 Abstention | Abstention accuracy >= 0.90 on no-evidence cases; no claim that no result means the whole corpus lacks the answer | Reviewed no-evidence set and result report | NOT TESTED |
| G10 Security | No unauthorized access or cross-scope leakage; secrets redacted; RLS, grants, SECURITY DEFINER, search path, JWT/custom auth, rate/size/time limits tested | Policy/function audit and controlled auth tests | PARTIAL: RLS deny policies observed on rag tables; active Edge Function reports verify_jwt=false, custom key path not runtime-tested |
| G11 Operations/recovery | Retry ceilings, stale lease recovery, idempotency, active-generation rollback, logs/health semantics, and restore procedure tested | Failure-injection test outputs and recovery record | NOT TESTED |
| G12 Deployment safety | Migration reviewed in non-production; rollback tested; exact candidate and authorization recorded | Migration dry-run/review, deployment record | BLOCKED: pending migration not applied; no deployment authorized |
| G13 Source preservation | Dropbox originals unchanged; no deletes/moves/renames/overwrites caused by ingestion | Read-only API design plus source metadata comparison | NOT TESTED end-to-end |

## Decision rules

- **GO:** all required gates pass, evidence is attached to the exact release SHA, and production deployment is explicitly authorized.
- **CONDITIONAL GO:** only non-critical documented exceptions remain, each with owner, mitigation, expiry, and approval. Never use this status to bypass security, data integrity, or citation gates.
- **PILOT ONLY:** controlled, bounded tests are allowed; production claims and bulk ingestion are prohibited.
- **NO-GO:** a critical gate fails, evaluation is missing, or evidence is not reproducible.

## Required metric report

Report metric value, numerator/denominator or sample count, language, source type, label review status, tested commit, model/version, and timestamp. Do not populate a metric with an estimate. Report latency p50/p95 and ingestion failure/retry rates only when measured.

## Current decision

**NO-GO for production; PILOT ONLY after migration/RPC review and controlled PDF/video pilots.** Existing row counts, compilation, or a previous successful workflow cannot substitute for end-to-end proof.
