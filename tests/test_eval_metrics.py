from eval_retrieval import metrics


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
