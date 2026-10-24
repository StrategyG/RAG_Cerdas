import pytest
from im19.evaluation import evaluate


def test_unreviewed_labels_are_never_scored():
    assert (
        evaluate([{"label_status": "draft", "relevant_chunk_ids": ["a"]}])["metrics"]
        is None
    )


def test_reviewed_counts_and_ranking_metrics():
    result = evaluate(
        [
            {
                "label_status": "reviewed",
                "reviewer_id": "synthetic-fixture-author",
                "relevant_chunk_ids": ["a", "b"],
                "retrieved_chunk_ids": ["x", "a", "a", "b"],
                "reviewed_counts": {
                    "citation_accuracy": [2, 3],
                    "unsupported_claim_rate": [1, 4],
                },
            }
        ]
    )
    assert result["metrics"]["recall@5"] == 1 and result["metrics"]["MRR"] == 0.5
    assert result["metrics"]["citation_accuracy"] == pytest.approx(2 / 3)
    assert result["metrics"]["unsupported_claim_rate"] == 0.25
