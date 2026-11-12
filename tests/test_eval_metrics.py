from __future__ import annotations

import pytest

from eval_retrieval import (
    evaluation_case_status,
    metrics,
    normalize_reviewed_qrels,
    summarize_evaluation_coverage,
    validate_eval_cases,
)


def human_review_fields():
    return {
        "reviewer_id": "reviewer-verified-fixture-01",
        "review_attestation": {
            "reviewer_id": "reviewer-verified-fixture-01",
            "reviewer_type": "human",
            "reviewed_at": "2026-11-05T01:00:00+07:00",
            "rubric_version": "retrieval-relevance-v1",
        },
    }


def test_metrics_use_fixed_k_and_labeled_qrels():
    # Two relevant results at ranks 2 and 4; one has grade 2, the other grade 1.
    qrels = {"b": 2, "x": 1}
    result = metrics(["a", "b", "c", "x", "y"], qrels, 5)
    assert result["precision@5"] == 2 / 5
    assert result["recall@5"] == 1.0
    assert result["mrr@5"] == 0.5
    assert 0 < result["ndcg@5"] <= 1


def test_metrics_deduplicate_retrieved_chunk_ids_before_scoring():
    result = metrics(["b", "b", "b", "x"], {"b": 2, "x": 1}, 5)
    assert result["precision@5"] == 2 / 5
    assert result["recall@5"] == 1.0
    assert result["mrr@5"] == 1.0
    assert 0 < result["ndcg@5"] <= 1


def test_metrics_return_zero_when_no_relevant_results_are_labeled():
    result = metrics(["a", "b"], {}, 5)
    assert result["precision@5"] == 0
    assert result["recall@5"] == 0
    assert result["mrr@5"] == 0
    assert result["ndcg@5"] == 0


def test_unreviewed_qrels_are_withheld_even_if_ids_are_present():
    case = {
        "label_status": "needs_human_review_after_page_aware_ingestion",
        "relevant_chunk_ids": {"chunk-1": 2},
    }
    assert normalize_reviewed_qrels(case) == {}


def test_missing_review_status_withholds_qrels():
    assert normalize_reviewed_qrels({"relevant_chunk_ids": {"chunk-1": 1}}) == {}


def test_reviewed_mapping_qrels_require_and_accept_human_evidence():
    case = {
        "label_status": "reviewed",
        "relevant_chunk_ids": {"chunk-1": 2, "chunk-2": 0},
        **human_review_fields(),
    }
    assert normalize_reviewed_qrels(case) == {"chunk-1": 2, "chunk-2": 0}


def test_reviewed_list_qrels_are_accepted_as_binary_relevance():
    case = {
        "label_status": "reviewed",
        "relevant_chunk_ids": ["chunk-1", "chunk-2"],
        **human_review_fields(),
    }
    assert normalize_reviewed_qrels(case) == {"chunk-1": 1, "chunk-2": 1}


def test_reviewed_empty_list_qrels_are_rejected():
    case = {
        "label_status": "reviewed",
        "relevant_chunk_ids": [],
        **human_review_fields(),
    }
    with pytest.raises(ValueError, match="at least one relevant chunk"):
        normalize_reviewed_qrels(case)


def test_metrics_reject_invalid_relevance_grades():
    with pytest.raises(ValueError, match="non-negative integers"):
        metrics(["chunk-1"], {"chunk-1": True}, 5)
    with pytest.raises(ValueError, match="non-negative integers"):
        metrics(["chunk-1"], {"chunk-1": -1}, 5)


def test_reviewed_qrels_without_human_evidence_are_rejected():
    with pytest.raises(ValueError, match="human review evidence"):
        normalize_reviewed_qrels(
            {"label_status": "reviewed", "relevant_chunk_ids": {"chunk-1": 1}}
        )


def test_reviewed_qrels_reject_empty_or_all_zero_gold_sets():
    case = {
        "label_status": "reviewed",
        "relevant_chunk_ids": {"chunk-1": 0},
        **human_review_fields(),
    }
    with pytest.raises(ValueError, match="at least one relevant chunk"):
        normalize_reviewed_qrels(case)


@pytest.mark.parametrize(
    "attestation",
    [
        {"reviewer_id": "other", "reviewer_type": "human", "reviewed_at": "2026-11-05T01:00:00Z", "rubric_version": "v1"},
        {"reviewer_id": "reviewer-verified-fixture-01", "reviewer_type": "model", "reviewed_at": "2026-11-05T01:00:00Z", "rubric_version": "v1"},
        {"reviewer_id": "reviewer-verified-fixture-01", "reviewer_type": "human", "reviewed_at": "2026-11-05T01:00:00", "rubric_version": "v1"},
        {"reviewer_id": "reviewer-verified-fixture-01", "reviewer_type": "human", "reviewed_at": "2026-11-05T01:00:00Z", "rubric_version": ""},
    ],
)
def test_invalid_review_attestation_is_rejected(attestation):
    case = {
        "label_status": "reviewed",
        "relevant_chunk_ids": {"chunk-1": 1},
        "reviewer_id": "reviewer-verified-fixture-01",
        "review_attestation": attestation,
    }
    with pytest.raises(ValueError, match="human review evidence"):
        normalize_reviewed_qrels(case)


@pytest.mark.parametrize(
    "qrels",
    [
        {"chunk-1": -1},
        {"chunk-1": True},
        {"": 1},
        {"chunk-1": "2"},
        [""],
        [True],
    ],
)
def test_invalid_reviewed_qrels_are_rejected(qrels):
    with pytest.raises(ValueError):
        normalize_reviewed_qrels(
            {
                "label_status": "reviewed",
                "relevant_chunk_ids": qrels,
                **human_review_fields(),
            }
        )


def test_eval_dataset_rejects_duplicate_query_ids():
    case = {"query_id": "Q1", "query": "What is retrieval?", "label_status": "draft"}
    with pytest.raises(ValueError, match="Duplicate"):
        validate_eval_cases([case, case])


def test_eval_dataset_requires_nonempty_queries():
    with pytest.raises(ValueError, match="non-empty query"):
        validate_eval_cases(
            [{"query_id": "Q1", "query": " ", "label_status": "draft"}]
        )


def test_eval_dataset_does_not_treat_existing_unreviewed_labels_as_gold():
    cases = validate_eval_cases(
        [
            {
                "query_id": "Q1",
                "query": "What is retrieval?",
                "label_status": "needs_human_review",
                "relevant_chunk_ids": ["unreviewed-chunk"],
            }
        ]
    )
    assert normalize_reviewed_qrels(cases[0]) == {}


def test_evaluation_case_status_separates_unreviewed_labels_from_missing_qrels():
    assert evaluation_case_status(
        {"label_status": "draft", "relevant_chunk_ids": {"chunk-1": 1}}
    ) == "labels_not_reviewed"
    assert evaluation_case_status(
        {"label_status": "needs_human_review", "relevant_chunk_ids": {}}
    ) == "needs_human_qrels"
    assert evaluation_case_status(
        {
            "label_status": "reviewed",
            "relevant_chunk_ids": {"chunk-1": 1},
            **human_review_fields(),
        }
    ) == "scored"


def test_evaluation_coverage_reports_review_and_metric_coverage_separately():
    result = summarize_evaluation_coverage(
        ["scored", "labels_not_reviewed", "needs_human_qrels"]
    )
    assert result["scored_case_count"] == 1
    assert result["reviewed_case_count"] == 1
    assert result["unreviewed_case_count"] == 2
    assert result["labels_not_reviewed_count"] == 1
    assert result["needs_human_qrels_count"] == 1
    assert result["review_coverage"] == pytest.approx(1 / 3)
    assert result["evaluation_coverage"] == pytest.approx(1 / 3)
    assert result["overall_status"] == "partial_or_unlabeled"


def test_evaluation_coverage_blocks_when_no_case_has_reviewed_qrels():
    result = summarize_evaluation_coverage(
        ["labels_not_reviewed", "needs_human_qrels", "needs_human_qrels"]
    )
    assert result["scored_case_count"] == 0
    assert result["reviewed_case_count"] == 0
    assert result["review_coverage"] == 0
    assert result["evaluation_coverage"] == 0
    assert result["overall_status"] == "blocked_no_human_reviewed_labels"


def test_evaluation_coverage_is_complete_only_when_every_case_is_scored():
    result = summarize_evaluation_coverage(["scored", "scored"])
    assert result["review_coverage"] == 1
    assert result["evaluation_coverage"] == 1
    assert result["overall_status"] == "scored"


def test_evaluation_coverage_rejects_unknown_statuses():
    with pytest.raises(ValueError, match="statuses are invalid"):
        summarize_evaluation_coverage(["scored", "unknown"])

