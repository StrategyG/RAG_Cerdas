from contextlib import contextmanager

from im19.retrieval import HybridRetriever


class EmptyCursor:
    def fetchall(self):
        return []


class RecordingConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=()):
        self.statements.append((statement, params))
        return EmptyCursor()


class RecordingStore:
    def __init__(self):
        self.connection = RecordingConnection()
        self.transaction_open = False

    @contextmanager
    def tx(self):
        self.transaction_open = True
        try:
            yield self.connection
        finally:
            self.transaction_open = False


class FixtureEmbedder:
    version = "fixture-e5"

    def __init__(self, store):
        self.store = store

    def query(self, text):
        # Embedding must finish before a DB transaction is opened.
        assert not self.store.transaction_open
        return [1.0] + [0.0] * 383


def test_retrieval_uses_bounded_database_lexical_and_vector_candidates(monkeypatch):
    import im19.retrieval as retrieval

    def no_python_corpus_scan(*args, **kwargs):
        raise AssertionError("The production retrieval path must not call Python BM25.")

    monkeypatch.setattr(retrieval, "bm25", no_python_corpus_scan)
    store = RecordingStore()
    retriever = HybridRetriever(store, FixtureEmbedder(store))

    result = retriever.search("risk management")

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["retrieval_backend"] == "postgresql_gin_fts+pgvector_hnsw+rrf"
    assert len(store.connection.statements) == 2

    lexical_sql, lexical_params = store.connection.statements[0]
    assert "pg_catalog.to_tsvector(" in lexical_sql
    assert "pg_catalog.plainto_tsquery(" in lexical_sql
    assert " @@ " in lexical_sql
    assert "ORDER BY lexical_score DESC,c.id LIMIT 50" in lexical_sql
    assert "count(" not in lexical_sql.lower()
    assert lexical_params == ["risk management", "risk management"]

    dense_sql, _ = store.connection.statements[1]
    assert "extensions.<=>" in dense_sql
    assert "LIMIT 50" in dense_sql
    assert "SELECT count(*)" not in dense_sql


class RowsCursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class GraphRecordingConnection(RecordingConnection):
    def execute(self, statement, params=()):
        self.statements.append((statement, params))
        if len(self.statements) == 1:
            return RowsCursor(
                [
                    {
                        "chunk_id": "chunk-1",
                        "document_id": "doc-1",
                        "locator": "pdf:page:1",
                        "page_start": 1,
                        "page_end": 1,
                        "text_content": "risk management evidence",
                        "content_hash": "a" * 64,
                        "title": "Risk handbook",
                        "source_uri": "https://example.invalid/risk.pdf",
                        "review": {},
                    }
                ]
            )
        return EmptyCursor()


def test_graph_expansion_joins_relation_endpoints_through_knowledge_nodes():
    store = RecordingStore()
    store.connection = GraphRecordingConnection()
    retriever = HybridRetriever(store, FixtureEmbedder(store))

    result = retriever.search("risk management", graph=True)

    assert result["status"] == "EVIDENCE_FOUND"
    assert len(store.connection.statements) == 3
    graph_sql, graph_params = store.connection.statements[2]
    assert "JOIN im19.knowledge_nodes src ON src.id=rel.source_id" in graph_sql
    assert (
        "JOIN im19.knowledge_nodes tgt ON tgt.id=rel.target_id "
        "AND tgt.node_type='Claim'"
    ) in graph_sql
    assert "JOIN im19.knowledge_units tgt_unit ON tgt_unit.id=tgt.id" in graph_sql
    assert "c.id=ANY(tgt_unit.source_chunk_ids)" in graph_sql
    assert "JOIN im19.knowledge_units src" not in graph_sql
    assert graph_params == [["doc-1"]]
