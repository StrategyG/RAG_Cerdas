import pytest

from eval_retrieval import (
    evaluation_case_status,
    metrics,
    normalize_qrels,
    summarize_evaluation_coverage,
)


def test_metrics_use_fixed_k_and_labeled_qrels():
    # Two relevant results at ranks 2 and 4; one has grade 2, the other grade 1.
    qrels = {"b": 2, "x": 1}
    result = metrics(["a", "b", "c", "x", "y"], qrels, 5)
    assert result["precision@5"] == 2 / 5
    assert result["recall@5"] == 1.0
    assert result["mrr@5"] == 0.5
    assert 0 < result["ndcg@5"] <= 1


def test_metrics_return_zero_when_no_relevant_results_are_labeled():
    result = metrics(["a", "b"], {}, 5)
    assert result["precision@5"] == 0
    assert result["recall@5"] == 0
    assert result["mrr@5"] == 0
    assert result["ndcg@5"] == 0


def test_metrics_support_postgres_uuid_chunk_ids_case_insensitively():
    upper_uuid = "550E8400-E29B-41D4-A716-446655440000"
    lower_uuid = "550e8400-e29b-41d4-a716-446655440000"
    qrels = normalize_qrels({upper_uuid: 2})

    assert qrels == {lower_uuid: 2}
    result = metrics([lower_uuid], qrels, 1)
    assert result["precision@1"] == 1.0
    assert result["recall@1"] == 1.0
    assert result["mrr@1"] == 1.0
    assert result["ndcg@1"] == 1.0



@pytest.mark.parametrize(
    ("qrels", "reviewed", "expected"),
    [
        ({}, False, "needs_human_review"),
        ({}, True, "needs_human_qrels"),
        ({"chunk-1": 0, "chunk-2": 0}, True, "no_positive_relevance"),
        ({"chunk-1": 1}, True, "scored"),
        ({"chunk-1": 0, "chunk-2": 2}, True, "scored"),
    ],
)
def test_case_status_requires_positive_relevance_for_metric_scoring(qrels, reviewed, expected):
    assert evaluation_case_status(qrels, reviewed=reviewed) == expected


def test_coverage_is_not_reported_complete_when_some_cases_are_unreviewed():
    result = summarize_evaluation_coverage(
        ["scored", "needs_human_review", "no_positive_relevance"]
    )
    assert result["evaluation_coverage"] == pytest.approx(2 / 3)
    assert result["scored_case_count"] == 1
    assert result["reviewed_case_count"] == 2
    assert result["unreviewed_case_count"] == 1
    assert result["overall_status"] == "partial_or_unlabeled"


def test_complete_reviewed_dataset_exposes_metric_exclusions():
    result = summarize_evaluation_coverage(
        ["scored", "no_positive_relevance", "scored"]
    )
    assert result["evaluation_coverage"] == 1.0
    assert result["scored_case_count"] == 2
    assert result["no_positive_relevance_case_count"] == 1
    assert result["overall_status"] == "scored_with_exclusions"


def test_all_reviewed_cases_without_positive_relevance_are_not_scored():
    result = summarize_evaluation_coverage(["no_positive_relevance", "no_positive_relevance"])
    assert result["scored_case_count"] == 0
    assert result["overall_status"] == "no_metric_eligible_cases"


def test_coverage_rejects_unknown_case_status():
    with pytest.raises(ValueError, match="statuses are invalid"):
        summarize_evaluation_coverage(["scored", "maybe"])
