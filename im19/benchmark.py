"""Read-only IM19 retrieval query-plan and latency benchmark.

This measures PostgreSQL candidate-query access paths only. It does not measure
embedding quality, relevance, citations, tenant isolation, or production readiness.
No schema, source, job, or index writes are performed.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import statistics
import time
from typing import Any


LEXICAL_CANDIDATE_LIMIT = 50
DENSE_CANDIDATE_LIMIT = 50
TABLES = ("chunks", "embeddings", "knowledge_units", "document_versions")


def percentile(values: list[float], quantile: float) -> float:
    if not values or not 0 < quantile <= 1:
        raise ValueError("percentile requires values and a quantile in (0, 1]")
    ordered = sorted(values)
    return ordered[math.ceil(quantile * len(ordered)) - 1]


def summarize_plan(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ValueError("unexpected PostgreSQL JSON plan")
    item = payload[0]
    root = item.get("Plan")
    if not isinstance(root, dict):
        raise ValueError("PostgreSQL plan root is missing")

    node_types: set[str] = set()
    index_names: set[str] = set()
    relations: set[str] = set()

    def walk(node: dict[str, Any]) -> None:
        if not isinstance(node, dict):
            return
        if isinstance(node.get("Node Type"), str):
            node_types.add(node["Node Type"])
        if isinstance(node.get("Index Name"), str):
            index_names.add(node["Index Name"])
        if isinstance(node.get("Relation Name"), str):
            relations.add(node["Relation Name"])
        for child in node.get("Plans", []):
            walk(child)

    walk(root)
    return {
        "node_types": sorted(node_types),
        "index_names": sorted(index_names),
        "relations": sorted(relations),
        "planning_time_ms": item.get("Planning Time"),
        "execution_time_ms": item.get("Execution Time"),
        "shared_hit_blocks": root.get("Shared Hit Blocks"),
        "shared_read_blocks": root.get("Shared Read Blocks"),
        "root_plan_rows": root.get("Plan Rows"),
        "root_actual_rows": root.get("Actual Rows"),
    }


def build_queries(query: str, vector: list[float], model_version: str):
    vector_json = json.dumps(vector, separators=(",", ":"))
    where = (
        "v.state='PUBLISHED' AND NOT f.deleted AND f.access_authorized "
        "AND v.revision=f.revision AND v.source_content_hash=f.content_hash"
    )
    fields = (
        "c.id AS chunk_id,c.document_id,c.locator,c.page_start,c.page_end,"
        "c.text_content,c.content_hash,f.filename AS title,f.source_uri,v.review"
    )
    fts_vector = (
        "pg_catalog.to_tsvector("
        "'pg_catalog.simple'::pg_catalog.regconfig, c.text_content)"
    )
    fts_query = (
        "pg_catalog.plainto_tsquery("
        "'pg_catalog.simple'::pg_catalog.regconfig, %s)"
    )
    lexical_sql = (
        "SELECT "
        + fields
        + f",pg_catalog.ts_rank_cd({fts_vector},{fts_query}) AS lexical_score "
        "FROM im19.chunks c "
        "JOIN im19.document_versions v ON v.id=c.document_id "
        "JOIN im19.source_files f ON f.id=v.source_file_id "
        "WHERE "
        + where
        + f" AND {fts_vector} @@ {fts_query} "
        "ORDER BY lexical_score DESC,c.id LIMIT "
        + str(LEXICAL_CANDIDATE_LIMIT)
    )
    dense_sql = (
        "SELECT "
        + fields
        + ",1-(e.embedding OPERATOR(extensions.<=>) %s::extensions.vector) AS similarity "
        "FROM im19.embeddings e "
        "JOIN im19.chunks c ON c.id=e.chunk_id "
        "JOIN im19.document_versions v ON v.id=c.document_id "
        "JOIN im19.source_files f ON f.id=v.source_file_id "
        "WHERE "
        + where
        + " AND e.model_version=%s AND e.content_hash=c.content_hash "
        "ORDER BY e.embedding OPERATOR(extensions.<=>) %s::extensions.vector LIMIT "
        + str(DENSE_CANDIDATE_LIMIT)
    )
    return {
        "lexical": (lexical_sql, [query, query]),
        "dense": (dense_sql, [vector_json, model_version, vector_json]),
    }


def _read_only_fetchall(connection, statement: str, params=()):
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        return connection.execute(statement, params).fetchall()


def _read_only_explain(connection, statement: str, params=()):
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        row = connection.execute(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement,
            params,
        ).fetchone()
        return row[0]


def _benchmark_one(connection, statement, params, *, warmup: int, iterations: int):
    plan = _read_only_explain(connection, statement, params)
    for _ in range(warmup):
        _read_only_fetchall(connection, statement, params)
    timings = []
    result_count = 0
    for _ in range(iterations):
        started = time.perf_counter()
        rows = _read_only_fetchall(connection, statement, params)
        timings.append((time.perf_counter() - started) * 1000)
        result_count = len(rows)
    return {
        "plan": summarize_plan(plan),
        "iterations": iterations,
        "warmup_iterations": warmup,
        "result_rows_last_iteration": result_count,
        "latency_ms": {
            "min": round(min(timings), 3),
            "p50": round(statistics.median(timings), 3),
            "p95": round(percentile(timings, 0.95), 3),
            "max": round(max(timings), 3),
        },
    }


def _database_snapshot(connection):
    estimates = _read_only_fetchall(
        connection,
        """
        SELECT c.relname AS table_name,
               GREATEST(c.reltuples, 0)::bigint AS estimated_rows,
               pg_total_relation_size(c.oid)::bigint AS total_bytes
        FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='im19' AND c.relkind='r'
          AND c.relname = ANY(%s)
        ORDER BY c.relname
        """,
        [list(TABLES)],
    )
    indexes = _read_only_fetchall(
        connection,
        """
        SELECT tablename,indexname,indexdef
        FROM pg_indexes
        WHERE schemaname='im19' AND tablename IN ('chunks','embeddings')
        ORDER BY tablename,indexname
        """,
    )
    return {
        "estimated_tables": estimates,
        "indexes": indexes,
        "row_counts_are_estimates": True,
    }


def run_benchmark(
    *,
    dsn: str,
    query: str,
    vector: list[float],
    model_version: str,
    warmup: int = 3,
    iterations: int = 20,
    allow_local_test: bool = False,
):
    from psycopg import connect
    from psycopg.conninfo import conninfo_to_dict
    from psycopg.rows import dict_row
    from im19.retrieval import validate_vector

    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("query must contain 1 to 2000 characters")
    if not 0 <= warmup <= 20 or not 5 <= iterations <= 200:
        raise ValueError("warmup/iteration limits are invalid")
    if not isinstance(model_version, str) or not model_version.strip() or len(model_version) > 512:
        raise ValueError("model_version is invalid")
    validate_vector(vector)

    config = conninfo_to_dict(dsn)
    host = config.get("host", "")
    local_host = (
        not host
        or host in {"localhost", "127.0.0.1", "::1"}
        or host.startswith("/")
    )
    if config.get("sslmode") != "verify-full":
        if not allow_local_test or not local_host:
            raise RuntimeError("DATABASE_TLS_VERIFY_FULL_REQUIRED")

    queries = build_queries(query, vector, model_version)
    with connect(dsn, connect_timeout=10, row_factory=dict_row, autocommit=True) as conn:
        # Session defaults and every benchmark statement are read-only.
        conn.execute("SET default_transaction_read_only = on")
        conn.execute("SET statement_timeout = '30s'")
        conn.execute("SET lock_timeout = '5s'")
        conn.execute("SET application_name = 'im19_readonly_retrieval_benchmark'")
        readonly = conn.execute("SHOW default_transaction_read_only").fetchone()[0]
        role = conn.execute(
            """
            SELECT rolsuper,rolbypassrls,
                   pg_has_role(current_user,'im19_approver','member') AS approver,
                   pg_has_role(current_user,'im19_worker','member') AS worker
            FROM pg_roles WHERE rolname=current_user
            """
        ).fetchone()
        if readonly not in {"on", True}:
            raise RuntimeError("READ_ONLY_SESSION_NOT_ENFORCED")
        if (
            role is None
            or role["rolsuper"]
            or role["rolbypassrls"]
            or role["approver"]
            or not role["worker"]
        ):
            raise RuntimeError("DATABASE_ROLE_NOT_LEAST_PRIVILEGED")

        snapshot = _database_snapshot(conn)
        index_defs = [x["indexdef"].lower() for x in snapshot["indexes"]]
        gin_found = any(
            "using gin" in definition and "to_tsvector" in definition
            for definition in index_defs
        )
        hnsw_found = any("using hnsw" in definition for definition in index_defs)

        report = {
            "status": "BENCHMARK_COMPLETED",
            "benchmark_kind": "read_only_database_candidate_queries",
            "read_only_enforced": True,
            "source_content_exported": False,
            "query": query,
            "model_version_filter": model_version,
            "vector_source": "synthetic_unit_vector" if vector == [1.0] + [0.0] * 383 else "provided_normalized_vector",
            "candidate_limits": {
                "lexical": LEXICAL_CANDIDATE_LIMIT,
                "dense": DENSE_CANDIDATE_LIMIT,
            },
            "tenant_scope": "NOT_IMPLEMENTED_IN_CURRENT_IM19_SCHEMA",
            "quality_metrics": "NOT_MEASURED",
            "production_capacity_certified": False,
            "database_snapshot": snapshot,
            "expected_index_presence": {
                "gin_lexical": gin_found,
                "hnsw_vector": hnsw_found,
            },
            "benchmarks": {
                name: _benchmark_one(
                    conn,
                    statement,
                    params,
                    warmup=warmup,
                    iterations=iterations,
                )
                for name, (statement, params) in queries.items()
            },
            "limitations": [
                "The benchmark measures database candidate-query access paths only; embedding and answer generation are excluded.",
                "The vector query defaults to a synthetic normalized unit vector unless a representative vector is supplied.",
                "Database row counts are PostgreSQL planner estimates, not exact approved knowledge-unit counts.",
                "No tenant predicate can be benchmarked until the IM19 data model has an approved tenant-aware design.",
                "A successful benchmark is not a 5-million-unit capacity certification.",
            ],
        }
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="retrieval benchmark")
    parser.add_argument("--vector-json", help="Optional normalized 384D query vector as JSON.")
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--secret-provider", choices=("mounted", "colab"), default="mounted")
    parser.add_argument("--allow-local-test", action="store_true")
    parser.add_argument("--output", help="Optional local JSON report path.")
    args = parser.parse_args(argv)

    from im19.retrieval import EMBED_MODEL
    from im19.secrets import ColabSecrets, MountedSecrets

    secrets = (
        ColabSecrets()
        if args.secret_provider == "colab"
        else MountedSecrets(os.getenv("IM19_SECRETS_DIR", "/run/secrets"))
    )
    dsn = secrets.get("IM19_DATABASE_DSN")
    model_sha256 = os.getenv("IM19_EMBEDDING_SHA256", "")
    if not dsn or not model_sha256:
        parser.error("IM19_DATABASE_DSN secret and IM19_EMBEDDING_SHA256 are required")
    try:
        vector = (
            json.loads(args.vector_json)
            if args.vector_json
            else [1.0] + [0.0] * 383
        )
        model_version = EMBED_MODEL + "@sha256:" + model_sha256
        report = run_benchmark(
            dsn=dsn,
            query=args.query,
            vector=vector,
            model_version=model_version,
            warmup=args.warmup,
            iterations=args.iterations,
            allow_local_test=args.allow_local_test,
        )
        rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    except Exception as exc:
        # Do not serialize DSNs, provider bodies, or source content in failure output.
        print(json.dumps({"status": "BLOCKED", "code": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
