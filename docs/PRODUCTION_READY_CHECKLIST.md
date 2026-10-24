# Institutional RAG — Production Ready Checklist

**Default decision: NO-GO for production.** CI is necessary but insufficient: it proves only the checks actually run by the workflow. Production readiness also requires reproducible operational evidence, retrieval/citation quality, human review, and explicit deployment approval. Keep the PR in draft and run only bounded, explicitly authorized pilots until every critical gate has reproducible evidence.

## 1. Change and environment record

- [ ] Repository and branch recorded.
- [ ] Exact candidate commit SHA recorded; CI run corresponds to that exact SHA.
- [ ] Current working tree and diff reviewed; no unrelated features or generated archives included.
- [ ] Secrets exist only in Codespaces/server-side secret storage; no values in logs, commits, screenshots, or reports.
- [ ] Current Supabase project ref and environment (staging vs production) recorded without publishing credentials.
- [ ] Dropbox source of truth confirmed read-only: no rename, move, overwrite, delete, or permission changes.

## 2. Repository and automated tests

- [ ] Full required test suite passes on the exact candidate SHA.
- [ ] Python compilation and any JavaScript/TypeScript contract tests pass.
- [ ] CI logs and test counts retained; no skipped/removed tests used to manufacture a green result.
- [ ] Dependency and secret scan reviewed.
- [ ] Run `python scripts/production_gate.py --candidate-sha <FULL_SHA> --run-tests`; a local PASS is not treated as proof of live integration.

## 3. Schema and security — read-only audit first

- [ ] Canonical runtime data path selected and documented (rag vs institutional_rag); do not dual-write.
- [ ] Worker SQL, RPC signatures/return types, indexes, embedding dimensions and migration assumptions compared with live schema.
- [ ] Migration reviewed and dry-run on disposable/staging database; not applied to production during audit.
- [ ] RLS, table grants, function execution grants, SECURITY DEFINER, search_path, JWT/custom API-key behavior and rate/size/time limits reviewed.
- [ ] Authorized and unauthorized request behavior tested without exposing secrets.
- [ ] Backup/restore and rollback path tested before any write.
- [ ] Edge Function deployment, migration, RLS/grant changes and live secret rotation require separate explicit approval.

## 4. Pilot A — one PDF only

Record a pilot manifest with timestamp, candidate SHA, source Dropbox file ID, path, metadata, file size and SHA-256. Do not include document contents or credentials in the manifest.

- [ ] PDF is authorized and downloadable through read-only Dropbox access.
- [ ] File signature, size ceiling, timeout and SHA-256 verified.
- [ ] Page-by-page extraction tested; original 1-based page numbers preserved.
- [ ] Scanned/empty pages are explicitly reported; no invented text or page numbers.
- [ ] Chunk IDs are deterministic; each chunk has source ID, content hash, parser/model version and valid page provenance.
- [ ] Embeddings are finite, non-empty, correct dimension and compatible with the configured retrieval model.
- [ ] Writes, if explicitly approved, go to a new/inactive generation; no legacy chunks deleted or overwritten.
- [ ] Counts reconcile: eligible chunks = stored chunks = embedded chunks; no unexplained partial state.
- [ ] Exact known-answer query retrieves the expected passage and correct source/page citation.
- [ ] No-evidence query abstains rather than inventing an answer.
- [ ] Repeat-run test does not duplicate chunks or activate an incomplete generation.
- [ ] Failure/interruption leaves prior active generation intact; rollback is demonstrated.
- [ ] Human reviewer checks extracted text and every cited page against the original PDF.

**PDF result:** NOT RUN / PASS / FAIL — Commit SHA: ______ — Evidence reference: ______

## 5. Pilot B — one video only

Record source Dropbox ID/path, metadata, size, SHA-256, duration, language and model/version. The current worker indexes spoken audio/transcript; it does not establish visual-scene or slide OCR search.

- [ ] One authorized video only; do not use a corpus-wide limit.
- [ ] Read-only download, byte ceiling, timeouts and temporary-file cleanup verified.
- [ ] Transcription model/version and language recorded; transcript reviewed against the media.
- [ ] Segment text is non-empty; timestamps are finite, valid, monotonic and within media duration.
- [ ] Chunk metadata preserves exact start/end seconds and source identity.
- [ ] Embeddings have correct dimension and finite values.
- [ ] Any approved writes use a new/inactive generation and preserve previous chunks.
- [ ] Counts reconcile: transcript chunks = stored chunks = embedded chunks.
- [ ] Known-answer retrieval cites the correct video and accurate timestamp interval.
- [ ] Invalid/no-evidence query abstains; citation end time is strictly greater than start time.
- [ ] Repeated run is idempotent; interrupted run and stale-job recovery are tested.
- [ ] Prior active generation remains available if any stage fails.

**Video result:** NOT RUN / PASS / FAIL — Commit SHA: ______ — Evidence reference: ______

## 6. Retrieval quality and grounding

- [ ] At least 30 human-reviewed evaluation questions with non-empty, verified relevant chunk IDs; include Indonesian and English, PDF and video, answerable and unanswerable cases.
- [ ] Dataset labels reference real chunks from the tested generation; no fabricated IDs or labels.
- [ ] Recall@5 >= 0.85 and MRR@10 >= 0.75, measured and reported with denominators.
- [ ] Citation accuracy >= 0.95 and groundedness >= 0.90, human-reviewed.
- [ ] Abstention accuracy >= 0.90 on the no-evidence subset; no unsupported factual answers in the release test set.
- [ ] Metrics report includes candidate SHA, model/version, source type, language, sample counts, timestamp and label-review status.
- [ ] Latency and retry/failure metrics are reported only if actually measured.

These are project acceptance thresholds, not claims that the current RAG meets them.

## 7. Operations, privacy and source preservation

- [ ] Bounded retries, redacted errors, structured request/job IDs and stuck-job recovery tested.
- [ ] Generation activation is atomic; previous generation remains recoverable.
- [ ] Dropbox original metadata is unchanged after the pilot.
- [ ] No full private source text, credentials, authorization headers or sensitive user data in logs.
- [ ] Backup restore and rollback rehearsal results attached.
- [ ] Usage limits, timeout and payload limits tested.
- [ ] A documented operator can stop a run safely and explain recovery steps.

## 8. Required release evidence beyond CI

CI may establish that the exact commit compiles and its configured automated tests pass. It does **not** prove these operational gates:

- [ ] **Source validation:** one authorized PDF and one authorized video have verified identity, integrity, file bounds, and readable/processable content.
- [ ] **Ingestion idempotency:** repeated runs produce no duplicate active chunks; interrupted runs cannot activate partial generations.
- [ ] **Page/timestamp correctness:** human-reviewed PDF citations match original 1-based pages; video timestamps match the source media and satisfy start < end <= duration.
- [ ] **Retrieval quality and citation accuracy:** a versioned, human-reviewed evaluation set passes the approved retrieval, grounding, citation, and abstention thresholds.
- [ ] **Approved deployment:** named owner has approved the exact candidate SHA and target environment after reviewing migration and Edge Function diffs.
- [ ] **Backup/rollback:** restore and rollback were rehearsed in a safe environment and evidence is attached.
- [ ] **Human review:** reviewer signs off source extraction, representative retrievals, citations, and failure/abstention cases.

A gate must remain BLOCKED when evidence is missing. Do not treat a green CI badge, code presence, or a manually set boolean as proof by itself. The evidence reference must point to a reviewable artifact or test result for the exact candidate SHA.

## 9. Evidence manifest and final decision

For each gate, attach a durable reference (CI URL/log, SQL audit result, pilot manifest, reviewer record or recovery test output). The evidence must correspond to the exact candidate SHA.

Required by scripts/production_gate.py when using --evidence:

- candidate_commit: full 40-character SHA.
- gates: all required booleans set to true.
- evidence: non-empty reference for every gate.

Do not set a gate to true merely because a script exists or a previous commit passed CI.

### Final release decision

- [ ] **GO** — all critical gates pass; evidence independently reviewed; production deployment explicitly authorized.
- [ ] **PILOT ONLY** — bounded pilot allowed, production use prohibited.
- [ ] **NO-GO** — any critical gate failed or evidence is missing.

Decision: ______
Reviewer / date: ______
Candidate SHA: ______
Outstanding blockers: ______
