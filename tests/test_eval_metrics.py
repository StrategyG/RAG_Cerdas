from __future__ import annotations

import pytest

from eval_retrieval import metrics, normalize_reviewed_qrels


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


def test_unreviewed_qrels_are_withheld_even_if_ids_are_present():
    case = {
        "label_status": "needs_human_review_after_page_aware_ingestion",
        "relevant_chunk_ids": {"chunk-1": 2},
    }
    assert normalize_reviewed_qrels(case) == {}


def test_missing_review_status_withholds_qrels():
    assert normalize_reviewed_qrels({"relevant_chunk_ids": {"chunk-1": 1}}) == {}


def test_reviewed_mapping_qrels_are_accepted():
    assert normalize_reviewed_qrels({
        "label_status": "reviewed",
        "relevant_chunk_ids": {"chunk-1": 2, "chunk-2": 0},
    }) == {"chunk-1": 2, "chunk-2": 0}


def test_reviewed_list_qrels_are_accepted_as_binary_relevance():
    assert normalize_reviewed_qrels({
        "label_status": "reviewed",
        "relevant_chunk_ids": ["chunk-1", "chunk-2"],
    }) == {"chunk-1": 1, "chunk-2": 1}


@pytest.mark.parametrize("qrels", [
    {"chunk-1": -1},
    {"chunk-1": True},
    {"": 1},
    {"chunk-1": "2"},
    [""],
    [True],
])
def test_invalid_reviewed_qrels_are_rejected(qrels):
    with pytest.raises(ValueError):
        normalize_reviewed_qrels({"label_status": "reviewed", "relevant_chunk_ids": qrels})
