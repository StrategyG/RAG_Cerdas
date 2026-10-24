# IM19 validation, benchmark and production readiness — 25 October 2026

**Release decision: BLOCKED. Not production-ready; no autonomous worker is deployed.**

## Actual local evidence

- Baseline current-main suite: **100 passed in 0.34s** before modification.
- Expanded suite: **159 passed, 18 skipped** on Python 3.12. The 18 skipped cases are PostgreSQL/pgvector integration tests: this execution environment maps only UID 0 and PostgreSQL refuses root. Tests explicitly report that limitation; mocks are not counted as database verification.
- Python compilation, undefined-name/import checks (Ruff F rules), Git whitespace check and top-level SQL/PLpgSQL parsing passed. Parsing is not migration execution.
- Real PyMuPDF PDF/EPUB parsing and a synthetic scan through installed Tesseract were executed. Scan OCR recognized the expected text with a recorded confidence above the fixture threshold. This is not an OCR corpus accuracy benchmark.
- OAuth refresh/expiry/revocation, pagination, rate limits, hashes, prompt schemas, provenance, classification ambiguity, publication holds, state progression and legacy local-vs-Dropbox preflight were tested with deterministic provider/model fixtures.
- Initial CI run [40130182922](https://github.com/StrategyG/RAG_Cerdas/actions/runs/40130182922) on `b39f7c9` executed the real database tests: **170 passed, 1 failed**. The failure was an incorrect expected table count in a test, corrected to an explicit set of all 17 required entities. Additional hardening fences superseded jobs and fingerprints local embedding files; rerun the updated head before accepting it.
- CI run [40130458378](https://github.com/StrategyG/RAG_Cerdas/actions/runs/40130458378) on code commit `c2a4d744171b99dea16a8d674da978e779b20430` passed **175 tests in 4.85s** with no skips. It executed a disposable PostgreSQL/pgvector cluster, migration, actual transactions/concurrency/RLS, separate approvals/publication, embedding read-back, retrieval and citations. AI/vector provider fixtures were deterministic; this is not a live Qwen/E5 or Supabase result.
- The final patch adds extraction-replay consistency and database chunk-to-page provenance gates with two further database regressions. Check the final-head CI outcome before merge. No production service or deployment was touched.

## Feature delivery status

Statuses are scoped: TESTED below means the stated local tests, never live provider verification.

| Feature | Status | Evidence and limitations |
|---|---|---|
| Repository/branch audit | VERIFIED | Current commit, all remote branch heads, source diffs, baseline test execution; audit scope in `IM19_AUDIT_20261025.md` |
| Metadata-first Dropbox discovery | TESTED | Cursor/pagination/deletion normalization and failure replay fixtures; real account BLOCKED |
| OAuth refresh and 401 classification | TESTED | Refresh/revoked/second-401 tests; actual scope/token exchange BLOCKED |
| Secret manager integration | IMPLEMENTED | Mounted secrets and Colab adapters; real manager/rotation operational test BLOCKED |
| Revision/size/block-hash/whole-file integrity | TESTED | Hash fixtures, bounded download and mismatch rejection |
| PDF/EPUB structural extraction | TESTED | Real parsers on synthetic documents; complex tables/headings/footnotes completeness remains PARTIAL |
| Selective PDF OCR/confidence | TESTED | Real Tesseract synthetic scan; multilingual/low-quality real scan benchmark BLOCKED |
| EPUB embedded-image OCR | NOT_IMPLEMENTED | Image/empty spine held for review |
| Content multi-label classifier | TESTED | Taxonomy/schema/ambiguity fixtures; Qwen classification accuracy BLOCKED |
| Structured knowledge mining | TESTED | Fourteen types, quote binding, null confidence, deterministic units; real model entailment precision BLOCKED |
| Five logical reviewer roles/rubric | TESTED | Role coverage, schema, corruption, unknown scores and verification status fixtures; local Qwen run BLOCKED |
| Fact verification | IMPLEMENTED | Source attribution and same-concept comparison inputs; external evidence acquisition/adjudication BLOCKED; never marks model output VERIFIED |
| Contradiction candidates | TESTED | Direct/context/definition/method/period labels and pending edges; real contradiction precision BLOCKED |
| Knowledge graph | TESTED | Nodes/attribution edges persisted in real database pipeline test; author enrichment PARTIAL and graph quality not measured |
| Private migration/RLS/publication gates | VERIFIED | Additive migration executed in isolated PostgreSQL/pgvector CI; worker privileges/publication checks passed; target Supabase BLOCKED |
| BM25+dense+RRF retrieval | TESTED | BM25/RRF and actual SQL retrieval/citations pass synthetic database fixture; actual encoder and corpus quality BLOCKED |
| Metadata/page/review filters | IMPLEMENTED | Parameterized SQL filters; author/credibility often unavailable and must not be invented |
| Optional reranker/graph expansion | IMPLEMENTED | Injectable reranker, reviewed edges only; model quality/performance NOT VERIFIED |
| Durable worker/checkpoints/leases/DLQ | TESTED | Real database concurrent claims, fencing, stage recovery, supersession, dead-letter and approval resume passed; endurance/outage target pilot BLOCKED |
| Colab pilot | IMPLEMENTED | Valid notebook, unexecuted; not a 24/7 runtime |
| Deployment configuration | IMPLEMENTED | Container/compose example; image build and target deployment BLOCKED |
| Retention policy | IMPLEMENTED | Written conservative pilot policy; timed disposal automation NOT_IMPLEMENTED pending owner policy |
| Live Dropbox/Supabase/Qwen/E5 | BLOCKED | Credentials, models, target staging environment and operational evidence unavailable |
| 24/7 autonomy/monitoring/DR | BLOCKED | No deployment, alert channel, endurance run or backup/restore test |

## Benchmark report

No before/after performance improvement, readiness score or corpus quality percentage is claimed. The 100-test baseline and expanded fixture suite cover different functionality, so their elapsed times are not a speed benchmark.

| Requested metric | Current corpus result | Required evidence |
|---|---|---|
| Classification accuracy | BLOCKED / null | Human-labeled multi-category books and local model run |
| Extraction completeness | BLOCKED / null | Page/structure ground truth, including OCR and tables |
| Claim-evidence precision | BLOCKED / null | Adjudicated entailment judgments, not substring matching alone |
| Contradiction precision/recall | BLOCKED / null | Paired claims labeled with context/period/methodology |
| Citation accuracy | BLOCKED / null | Retrieved quotes checked against actual document pages/EPUB locators |
| Recall@5 and MRR | BLOCKED / null | Human-reviewed qrels across current published corpus |
| Unsupported claim rate | BLOCKED / null | Adjudicated generated claims/answers and source entailment |
| Throughput/latency/RAM | BLOCKED / null | Representative CPU hardware, exact model hashes, cold/warm runs and OCR mix |

`im19.evaluation.evaluate()` consumes only records with `label_status='reviewed'` and an accountable reviewer. It will not invent a gold set. Existing `eval_cases.json` remains an unlabeled template. The synthetic fixture tests are regression oracles, not human corpus evaluations. Set acceptance thresholds jointly with human evaluators before permitting automatic publication.

## Acceptance gates

| Gate | Decision | Missing release evidence |
|---|---|---|
| A Security | BLOCKED | Actual OAuth least scopes, target role/RLS checks, dependency review and adversarial/native-parser security tests |
| B Data integrity | PARTIAL | Local contracts pass; target source version/hash/provenance and DB read-back pilot |
| C Knowledge quality | BLOCKED | Calibrated rubric/risk thresholds, human-reviewed extraction/mining/review benchmark |
| D Retrieval | BLOCKED | Corpus Recall@5/MRR, page/EPUB citation accuracy and abstention evaluation |
| E Reliability | PARTIAL | Real target network outage/kill/restart and bounded resource pilot |
| F Production release | BLOCKED | Reviewed migration/backup/staging, built image, monitoring/alerts, restore/rollback rehearsal, endurance test and release approval |

All six must pass before a production-ready declaration. This branch intentionally provides reviewable code, migrations and evidence boundaries without applying production changes.
