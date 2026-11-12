import pytest

from im19.evaluation import evaluate


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


def test_unreviewed_labels_are_never_scored():
    result = evaluate([{"label_status": "draft", "relevant_chunk_ids": ["a"]}])
    assert result["metrics"] is None
    assert result["reason"] == "HUMAN_REVIEWED_LABELS_AND_ATTESTATIONS_REQUIRED"


def test_reviewed_records_without_human_evidence_are_never_scored():
    result = evaluate(
        [
            {
                "label_status": "reviewed",
                "reviewer_id": "unverified-fixture",
                "relevant_chunk_ids": ["a"],
                "retrieved_chunk_ids": ["a"],
            }
        ]
    )
    assert result["status"] == "BLOCKED"
    assert result["metrics"] is None


def test_reviewed_counts_and_ranking_metrics():
    result = evaluate(
        [
            {
                "label_status": "reviewed",
                "relevant_chunk_ids": ["a", "b"],
                "retrieved_chunk_ids": ["x", "a", "a", "b"],
                "reviewed_counts": {
                    "citation_accuracy": [2, 3],
                    "unsupported_claim_rate": [1, 4],
                },
                **human_review_fields(),
            }
        ]
    )
    assert result["metrics"]["recall@5"] == 1
    assert result["metrics"]["MRR"] == 0.5
    assert result["metrics"]["citation_accuracy"] == pytest.approx(2 / 3)
    assert result["metrics"]["unsupported_claim_rate"] == 0.25


def test_empty_reviewed_gold_set_is_rejected():
    with pytest.raises(ValueError, match="at least one relevant chunk"):
        evaluate(
            [
                {
                    "label_status": "reviewed",
                    "relevant_chunk_ids": [],
                    "retrieved_chunk_ids": [],
                    **human_review_fields(),
                }
            ]
        )


def test_graded_qrels_exclude_zero_relevance_ids():
    result = evaluate(
        [
            {
                "label_status": "reviewed",
                "relevant_chunk_ids": {"a": 2, "b": 0},
                "retrieved_chunk_ids": ["b", "a"],
                **human_review_fields(),
            }
        ]
    )
    assert result["metrics"]["recall@5"] == 1
    assert result["metrics"]["MRR"] == 0.5


def test_graded_qrels_with_no_positive_relevance_are_rejected():
    with pytest.raises(ValueError, match="at least one relevant chunk"):
        evaluate(
            [
                {
                    "label_status": "reviewed",
                    "relevant_chunk_ids": {"a": 0},
                    "retrieved_chunk_ids": ["a"],
                    **human_review_fields(),
                }
            ]
        )


def test_reviewed_counts_must_be_a_mapping():
    with pytest.raises(ValueError, match="reviewed_counts"):
        evaluate(
            [
                {
                    "label_status": "reviewed",
                    "relevant_chunk_ids": ["a"],
                    "retrieved_chunk_ids": ["a"],
                    "reviewed_counts": None,
                    **human_review_fields(),
                }
            ]
        )


def test_invalid_k_is_rejected():
    with pytest.raises(ValueError, match="positive integer"):
        evaluate([], k=0)
