from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from im19.contracts import PipelineError, digest, Page, Chunk
from im19.knowledge_mining.dropbox_discovery import normalize_entry, content_hash
from im19.storage.postgres import PostgresStore


def discover(
    store,
    data=b"sample",
    rev="123abc",
    path="/book.pdf",
    source_id="id:book",
    connection_id=None,
):
    with store.tx() as conn:
        if connection_id is None:
            connection_id = str(uuid4())
            conn.execute(
                "INSERT INTO im19.source_connections(id,access_scope) VALUES(%s,'app_folder')",
                (connection_id,),
            )
        previous = conn.execute(
            "SELECT cursor FROM im19.source_connections WHERE id=%s", (connection_id,)
        ).fetchone()["cursor"]
    entry = {
        ".tag": "file",
        "id": source_id,
        "name": path.rsplit("/", 1)[-1],
        "path_lower": path,
        "size": len(data),
        "content_hash": content_hash(data),
        "rev": rev,
        "server_modified": "2026-10-25T00:00:00Z",
    }
    store.commit_discovery_page(
        connection_id, previous, str(uuid4()), [normalize_entry(entry, "app_folder")]
    )
    with store.tx() as conn:
        row = conn.execute(
            "SELECT id FROM im19.document_versions ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return str(row["id"]), connection_id


def worker_store(store):
    with store.tx() as conn:
        conn.execute(
            "DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='im19_test_login') THEN CREATE ROLE im19_test_login LOGIN; END IF; END $$"
        )
        conn.execute("GRANT im19_worker TO im19_test_login")
    config = conninfo_to_dict(store.dsn)
    config["user"] = "im19_test_login"
    return PostgresStore(make_conninfo(**config), allow_local_test=True)


def test_migration_creates_entities_rls_and_publication_gate(database):
    with database.tx() as conn:
        tables = conn.execute(
            "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='im19' AND relkind='r'"
        ).fetchall()
        required = {
            "source_connections",
            "source_files",
            "document_versions",
            "extraction_runs",
            "document_pages",
            "chunks",
            "knowledge_units",
            "knowledge_claims",
            "claim_evidence",
            "review_runs",
            "review_findings",
            "human_approvals",
            "knowledge_nodes",
            "knowledge_relations",
            "embeddings",
            "ingestion_jobs",
            "audit_events",
        }
        assert {t["relname"] for t in tables} == required
        assert all(t["relrowsecurity"] and t["relforcerowsecurity"] for t in tables)
        assert not conn.execute(
            "SELECT has_schema_privilege('public','im19','USAGE') AS p"
        ).fetchone()["p"]
        assert conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname='vector'"
        ).fetchone()["extversion"]


def test_cursor_and_enqueue_are_atomic_and_replay_idempotent(database):
    doc, cid = discover(database)
    with database.tx() as conn:
        original = conn.execute(
            "SELECT * FROM im19.source_connections WHERE id=%s", (cid,)
        ).fetchone()
    with pytest.raises(PipelineError, match="CURSOR_CONFLICT"):
        database.commit_discovery_page(cid, "wrong", "next", [])
    with database.tx() as conn:
        assert (
            conn.execute(
                "SELECT cursor FROM im19.source_connections WHERE id=%s", (cid,)
            ).fetchone()["cursor"]
            == original["cursor"]
        )
    # Same file/revision on another cursor must not create another version or job.
    discover(database, connection_id=cid)
    with database.tx() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM im19.ingestion_jobs").fetchone()[
                "n"
            ]
            == 1
        )
        assert (
            conn.execute("SELECT count(*) AS n FROM im19.document_versions").fetchone()[
                "n"
            ]
            == 1
        )


def test_discovery_bad_page_rolls_back_all_entries_and_cursor(database):
    _, cid = discover(database)
    old = database.source_connection(cid)["cursor"]
    with pytest.raises(Exception):
        database.commit_discovery_page(
            cid, old, "new", [{"deleted": True, "path": "/book.pdf"}, {"path": "/bad"}]
        )
    with database.tx() as conn:
        assert not conn.execute("SELECT deleted FROM im19.source_files").fetchone()[
            "deleted"
        ]
    assert database.source_connection(cid)["cursor"] == old


def test_changes_and_folder_deletion_invalidate_old_publication_without_deleting_history(
    database,
):
    old, cid = discover(database, path="/folder/book.pdf")
    new, _ = discover(
        database,
        data=b"changed",
        rev="def456",
        path="/folder/book.pdf",
        connection_id=cid,
    )
    assert old != new and database.load(old)["state"] == "SUPERSEDED"
    cursor = database.source_connection(cid)["cursor"]
    database.commit_discovery_page(
        cid, cursor, "deleted", [{"deleted": True, "path": "/folder"}]
    )
    assert database.load(new)["state"] == "SUPERSEDED"
    with database.tx() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM im19.document_versions").fetchone()[
                "n"
            ]
            == 2
        )


def test_concurrent_claims_fence_stale_worker_and_recover_checkpoint(database):
    doc, _ = discover(database)
    with ThreadPoolExecutor(2) as pool:
        jobs = list(pool.map(lambda i: database.claim("worker-" + str(i)), range(2)))
    assert sum(j is not None for j in jobs) == 1
    job = next(j for j in jobs if j)
    database.checkpoint(job, "DISCOVERED", "VALIDATED")
    with database.tx() as conn:
        conn.execute(
            "UPDATE im19.ingestion_jobs SET lease_expires_at=now()-interval '1 second'"
        )
    replacement = database.claim("replacement")
    assert replacement["attempts"] == 2 and database.load(doc)["state"] == "VALIDATED"
    with pytest.raises(PipelineError, match="LEASE_LOST"):
        database.checkpoint(job, "VALIDATED", "DOWNLOADED")
    database.checkpoint(
        replacement, "VALIDATED", "DOWNLOADED", content_sha256=digest("sample")
    )
    assert database.load(doc)["state"] == "DOWNLOADED"


def test_dead_letter_after_maximum_attempts(database):
    discover(database)
    with database.tx() as conn:
        conn.execute(
            "UPDATE im19.ingestion_jobs SET attempts=max_attempts,status='retry'"
        )
    assert database.claim("worker") is None
    with database.tx() as conn:
        assert (
            conn.execute("SELECT status FROM im19.ingestion_jobs").fetchone()["status"]
            == "dead"
        )


def test_worker_cannot_approve_or_authorize_and_audit_is_append_only(database):
    doc, _ = discover(database)
    worker = worker_store(database)
    worker.check_role()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with worker.tx() as conn:
            conn.execute("UPDATE im19.source_files SET access_authorized=true")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with worker.tx() as conn:
            conn.execute(
                "INSERT INTO im19.human_approvals(review_run_id,reviewer_id,decision,rationale) VALUES(%s,'model','approve','fake')",
                (uuid4(),),
            )
    with pytest.raises(psycopg.errors.RaiseException):
        with database.tx() as conn:
            conn.execute("UPDATE im19.audit_events SET event_type='changed'")
    # Worker can discover/update metadata using column privileges.
    with database.tx() as conn:
        cid = str(uuid4())
        conn.execute(
            "INSERT INTO im19.source_connections(id,access_scope) VALUES(%s,'app_folder')",
            (cid,),
        )
    discover(worker, source_id="id:second", path="/second.pdf", connection_id=cid)
    discover(
        worker,
        data=b"updated",
        rev="abc345",
        source_id="id:second",
        path="/second.pdf",
        connection_id=cid,
    )


def test_database_blocks_direct_publication(database):
    doc, _ = discover(database)
    with pytest.raises(psycopg.errors.RaiseException):
        with database.tx() as conn:
            conn.execute(
                "UPDATE im19.document_versions SET state='PUBLISHED' WHERE id=%s",
                (doc,),
            )
    assert database.load(doc)["state"] == "DISCOVERED"


def test_real_embedding_persistence_and_readback(database):
    doc, _ = discover(database)
    job = database.claim("worker")
    p = Page("pdf:page:1", "risk management", 1)
    c = Chunk(str(uuid4()), doc, p.locator, p.text, 1, 1, digest(p.text))
    database.save_extraction(job, [p], [c])
    database.save_embeddings(job, [c], [[1.0] + [0.0] * 383], "fixture-e5")
    database.save_embeddings(job, [c], [[1.0] + [0.0] * 383], "fixture-e5")
    with database.tx() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM im19.embeddings").fetchone()["n"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT extensions.vector_dims(embedding) AS dims FROM im19.embeddings"
            ).fetchone()["dims"]
            == 384
        )


def test_superseded_running_job_is_fenced_and_removed_from_active_queue(database):
    doc, cid = discover(database)
    old_job = database.claim("old-worker")
    discover(database, data=b"new-content", rev="def456", connection_id=cid)
    with database.tx() as conn:
        row = conn.execute(
            "SELECT status,lease_token,last_error_code FROM im19.ingestion_jobs WHERE document_id=%s",
            (doc,),
        ).fetchone()
    assert (
        row["status"] == "blocked"
        and row["lease_token"] is None
        and row["last_error_code"] == "SOURCE_SUPERSEDED"
    )
    with pytest.raises(PipelineError, match="LEASE_LOST"):
        database.heartbeat(old_job)


def test_database_rejects_fabricated_unit_quotes_and_worker_source_reconfiguration(
    database,
):
    from im19.contracts import KnowledgeUnit

    doc, cid = discover(database)
    job = database.claim("worker")
    text = "Risk management protects capital."
    page = Page("pdf:page:1", text, 1)
    chunk = Chunk(str(uuid4()), doc, page.locator, text, 1, 1, digest(text))
    database.save_extraction(job, [page], [chunk])
    unit = KnowledgeUnit(
        str(uuid4()),
        doc,
        "Risk",
        "Trading",
        "Risk Management",
        "principle",
        text,
        "Fake quotation",
        1,
        1,
        [chunk.chunk_id],
        page.locator,
        "fixture-model",
        digest(text),
    )
    with pytest.raises(psycopg.errors.RaiseException, match="provenance"):
        database.save_units(job, [unit])
    worker = worker_store(database)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with worker.tx() as conn:
            conn.execute(
                "UPDATE im19.source_connections SET root_path='/unapproved' WHERE id=%s",
                (cid,),
            )
    with worker.tx() as conn:
        assert not conn.execute(
            "SELECT has_table_privilege(current_user,'im19.chunks','UPDATE') AS p"
        ).fetchone()["p"]


def test_extraction_replay_cannot_mix_changed_text_with_prior_checkpoint(database):
    from im19.contracts import PipelineError

    doc, _ = discover(database)
    job = database.claim("worker")
    page = Page("pdf:page:1", "Original extracted text", 1)
    c = Chunk(str(uuid4()), doc, page.locator, page.text, 1, 1, digest(page.text))
    database.save_extraction(job, [page], [c])
    database.save_extraction(job, [page], [c])
    changed = Page("pdf:page:1", "Changed OCR output", 1)
    with pytest.raises(PipelineError, match="EXTRACTION_REPLAY_MISMATCH"):
        database.save_extraction(job, [changed], [])
    assert database.extraction(doc)[0][0].text == page.text


def test_database_rejects_chunk_content_absent_from_its_page(database):
    doc, _ = discover(database)
    job = database.claim("worker")
    page = Page("pdf:page:1", "Source text", 1)
    invented = Chunk(
        str(uuid4()), doc, page.locator, "Invented text", 1, 1, digest("Invented text")
    )
    with pytest.raises(psycopg.errors.RaiseException, match="chunk page provenance"):
        database.save_extraction(job, [page], [invented])
    assert not database.extraction(doc)[0]  # Whole extraction transaction rolls back.
