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
