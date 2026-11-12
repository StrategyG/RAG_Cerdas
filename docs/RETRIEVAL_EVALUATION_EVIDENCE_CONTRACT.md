# Retrieval evaluation label and evidence contract

**Contract version:** retrieval-relevance-v1  
**Status:** validation contract; not a production reviewer-authentication mechanism

## 1. A case can be scored only when

- `label_status` is exactly `reviewed`.
- `relevant_chunk_ids` is a non-empty list or mapping.
- At least one relevance grade is greater than zero.
- `reviewer_id` is present.
- `review_attestation.reviewer_id` exactly matches `reviewer_id`.
- `review_attestation.reviewer_type` is `human`.
- `review_attestation.reviewed_at` is an ISO-8601 timestamp with an explicit timezone.
- `review_attestation.rubric_version` is non-empty.

Example envelope (illustrative only; do not copy the fixture identity into a real dataset):

```json
{
  "query_id": "Q-EXAMPLE",
  "query": "What evidence supports the requested claim?",
  "label_status": "reviewed",
  "relevant_chunk_ids": {
    "actual-chunk-id-reviewed-by-a-human": 2
  },
  "reviewer_id": "canonical-reviewer-id",
  "review_attestation": {
    "reviewer_id": "canonical-reviewer-id",
    "reviewer_type": "human",
    "reviewed_at": "2026-11-05T01:00:00+07:00",
    "rubric_version": "retrieval-relevance-v1"
  }
}
```

## 2. What this code validates

The Python evaluators validate the structure and internal consistency of this evidence envelope. Unreviewed labels are withheld from metrics. Retrieval IDs are de-duplicated before Precision@K, Recall@K, MRR@K, and nDCG@K are calculated. Dataset identity is recorded as a SHA-256 digest by `eval_retrieval.py`.

This is a data-quality control, **not proof that a real human performed the review**. A JSON file can be edited. A `reviewer_id` string or `reviewer_type: human` field is not authentication.

## 3. Additional production requirements

Before evaluation results can authorize release or publication, a trusted server-side process must:

1. Resolve the reviewer against `institutional_rag.reviewer_registry` or another approved identity authority.
2. Verify the reviewer is active, authenticated, and authorized for the relevant corpus/domain.
3. Persist reviewer decision, case ID, relevant chunk IDs, rubric version, corpus/version hash, and timestamp in an append-only audit record.
4. Ensure the reviewed query and corpus version are the same versions used for the benchmark.
5. Prevent the evaluated process from creating or modifying its own human-review evidence.
6. Independently verify that every scored case has a valid review record.
7. Retain the dataset hash, code commit, embedding model ID/revision, retrieval configuration, and result artifact hash.

A fixture reviewer is a test oracle only. It must never be counted as a human corpus evaluation.

## 4. Current benchmark disposition

The repository's current `eval_cases.json` contains three cases that need human review and has no human relevance labels. It must remain unscored until reviewers inspect the actual source document and retrieved chunks. The expected status is therefore `blocked_no_human_reviewed_labels` when no scored case is present.

Do not fabricate relevance labels to make a benchmark pass. Retrieval quality, publication readiness, and production readiness remain blocked until a real reviewed dataset and the remaining release evidence exist.
