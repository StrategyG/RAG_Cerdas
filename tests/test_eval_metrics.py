from eval_retrieval import metrics, normalize_qrels


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
