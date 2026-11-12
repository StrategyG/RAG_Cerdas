from im19.benchmark import build_queries, percentile, summarize_plan


def test_percentile_uses_nearest_rank_and_rejects_empty_values():
    assert percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.95) == 5.0
    assert percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.50) == 3.0
    try:
        percentile([], 0.95)
    except ValueError:
        pass
    else:
        raise AssertionError("empty percentile input was accepted")


def test_plan_summary_extracts_index_and_buffer_evidence():
    plan = [
        {
            "Planning Time": 1.25,
            "Execution Time": 4.5,
            "Plan": {
                "Node Type": "Limit",
                "Plan Rows": 50,
                "Actual Rows": 50,
                "Shared Hit Blocks": 12,
                "Plans": [
                    {
                        "Node Type": "Bitmap Heap Scan",
                        "Relation Name": "chunks",
                        "Plans": [
                            {
                                "Node Type": "Bitmap Index Scan",
                                "Index Name": "chunks_text_search_gin_idx",
                            }
                        ],
                    }
                ],
            },
        }
    ]
    summary = summarize_plan(plan)
    assert summary["execution_time_ms"] == 4.5
    assert "Bitmap Index Scan" in summary["node_types"]
    assert summary["index_names"] == ["chunks_text_search_gin_idx"]
    assert summary["relations"] == ["chunks"]


def test_benchmark_queries_match_retrieval_index_expressions_and_bounds():
    vector = [1.0] + [0.0] * 383
    queries = build_queries("risk management", vector, "e5@sha256:test")

    lexical_sql, lexical_params = queries["lexical"]
    assert "pg_catalog.to_tsvector(" in lexical_sql
    assert "pg_catalog.plainto_tsquery(" in lexical_sql
    assert "chunks_text_search_gin_idx" not in lexical_sql
    assert "ORDER BY lexical_score DESC,c.id LIMIT 50" in lexical_sql
    assert lexical_params == ["risk management", "risk management"]

    dense_sql, dense_params = queries["dense"]
    assert "extensions.<=>" in dense_sql
    assert "LIMIT 50" in dense_sql
    assert dense_params == [
        "[" + ",".join(["1.0"] + ["0.0"] * 383) + "]",
        "e5@sha256:test",
        "[" + ",".join(["1.0"] + ["0.0"] * 383) + "]",
    ]
