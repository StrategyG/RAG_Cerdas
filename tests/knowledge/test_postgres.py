from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
from uuid import uuid4
import pytest
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from im19.contracts import PipelineError, digest, Page, Chunk
from im19.knowledge_mining.dropbox_discovery import normalize_entry, content_hash
from im19.storage.postgres import PostgresStore


def _test_reviewer_role_name(reviewer_id):
    return "im19_test_reviewer_" + sha256(reviewer_id.encode("utf-8")).hexdigest()[:16]


def _ensure_test_reviewer(store, reviewer_id, *, register=True):
    role_name = _test_reviewer_role_name(reviewer_id)
    with psycopg.connect(store.dsn, row_factory=dict_row) as admin:
        exists = admin.execute(
            "SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=%s", (role_name,)
        ).fetchone()
        if not exists:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role_name))
            )
        admin.execute(
            sql.SQL("GRANT im19_approver TO {}").format(sql.Identifier(role_name))
        )
        if register:
            admin.execute(
                "INSERT INTO im19_security.reviewer_identities("
                "database_role_oid,database_login_role,reviewer_id,display_name) "
                "SELECT pg_catalog.to_regrole(%s)::oid,%s,%s,%s "
                "WHERE EXISTS(SELECT 1 FROM pg_catalog.pg_roles "
                "WHERE rolname=%s AND rolcanlogin) "
                "ON CONFLICT(database_role_oid) DO NOTHING",
                (role_name, role_name, reviewer_id, reviewer_id, role_name),
            )
            identity = admin.execute(
                "SELECT reviewer_id,database_login_role "
                "FROM im19_security.reviewer_identities "
                "WHERE database_role_oid=pg_catalog.to_regrole(%s)::oid",
                (role_name,),
            ).fetchone()
            if (
                identity is None
                or identity["reviewer_id"] != reviewer_id
                or identity["database_login_role"] != role_name
            ):
                raise AssertionError("test reviewer principal was not registered as expected")
    return role_name


@contextmanager
def reviewer_tx(store, reviewer_id, *, register=True):
    """Open a real PostgreSQL session as a reviewer-specific LOGIN principal."""
    role_name = _ensure_test_reviewer(store, reviewer_id, register=register)
    config = conninfo_to_dict(store.dsn)
    config["user"] = role_name
    with psycopg.connect(make_conninfo(**config), row_factory=dict_row) as conn:
        yield conn


def _insert_test_rights_decision(
    conn,
    document_id,
    reviewer_id,
    *,
    decision="approve",
    storage_allowed=True,
    embedding_allowed=True,
):
    source = conn.execute(
        "SELECT f.id,f.revision,f.content_hash FROM im19.document_versions v "
        "JOIN im19.source_files f ON f.id=v.source_file_id WHERE v.id=%s",
        (document_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO im19.source_rights_reviews("
        "source_file_id,revision,content_hash,decision,rights_basis,license_identifier,"
        "attribution,evidence_reference,rationale,storage_allowed,embedding_allowed,"
        "derivative_notes_allowed,reviewer_id) "
        "VALUES(%s,%s,%s,%s,'owner_attestation',NULL,'Synthetic test fixture',"
        "'test-fixture://source-rights','Synthetic fixture rights decision',%s,%s,false,%s)",
        (
            source["id"],
            source["revision"],
            source["content_hash"],
            decision,
            storage_allowed,
            embedding_allowed,
            reviewer_id,
        ),
    )



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


def approve_source_rights(
    store,
    document_id,
    *,
    decision="approve",
    storage_allowed=None,
    embedding_allowed=None,
    reviewer_id="fixture-rights-reviewer",
):
    """Append a test-only rights decision through a mapped reviewer LOGIN."""
    if storage_allowed is None:
        storage_allowed = decision == "approve"
    if embedding_allowed is None:
        embedding_allowed = decision == "approve"
    with reviewer_tx(store, reviewer_id) as conn:
        _insert_test_rights_decision(
            conn,
            document_id,
            reviewer_id,
            decision=decision,
            storage_allowed=storage_allowed,
            embedding_allowed=embedding_allowed,
        )


def authorize_and_approve_source_rights(store, document_id):
    with store.tx() as conn:
        conn.execute(
            "UPDATE im19.source_files SET access_authorized=true "
            "WHERE id=(SELECT source_file_id FROM im19.document_versions WHERE id=%s)",
            (document_id,),
        )
    approve_source_rights(store, document_id)


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
            "source_rights_reviews",
        }
        assert {t["relname"] for t in tables} == required
        assert all(t["relrowsecurity"] and t["relforcerowsecurity"] for t in tables)
        assert not conn.execute(
            "SELECT has_schema_privilege('public','im19','USAGE') AS p"
        ).fetchone()["p"]
        assert conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname='vector'"
        ).fetchone()["extversion"]
        lexical_index = conn.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname='im19' AND indexname='chunks_text_search_gin_idx'"
        ).fetchone()
        assert lexical_index is not None
        assert "using gin" in lexical_index["indexdef"].lower()
        assert "to_tsvector" in lexical_index["indexdef"].lower()
        assert conn.execute(
            "SELECT has_table_privilege('im19_worker','im19.source_rights_reviews','INSERT') AS p"
        ).fetchone()["p"] is False
        assert conn.execute(
            "SELECT has_table_privilege('im19_approver','im19.source_rights_reviews','INSERT') AS p"
        ).fetchone()["p"] is True


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
    authorize_and_approve_source_rights(database, doc)
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
    authorize_and_approve_source_rights(database, doc)
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
    authorize_and_approve_source_rights(database, doc)
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
    authorize_and_approve_source_rights(database, doc)
    job = database.claim("worker")
    page = Page("pdf:page:1", "Source text", 1)
    invented = Chunk(
        str(uuid4()), doc, page.locator, "Invented text", 1, 1, digest("Invented text")
    )
    with pytest.raises(psycopg.errors.RaiseException, match="chunk page provenance"):
        database.save_extraction(job, [page], [invented])
    assert not database.extraction(doc)[0]  # Whole extraction transaction rolls back.


def test_source_rights_are_revision_bound_and_latest_decision_wins(database):
    doc, cid = discover(database)
    approve_source_rights(database, doc)
    assert database.load(doc)["rights_approved"] is True

    approve_source_rights(database, doc, decision="reject")
    assert database.load(doc)["rights_approved"] is False

    # A new Dropbox revision/hash is not covered by the old approval.
    new_doc, _ = discover(
        database,
        data=b"new source revision",
        rev="def456",
        connection_id=cid,
    )
    assert database.load(new_doc)["rights_approved"] is False


def test_source_rights_lookup_uses_document_version_not_mutable_source_head(database):
    doc, _ = discover(database)
    authorize_and_approve_source_rights(database, doc)
    before = database.load(doc)
    with database.tx() as conn:
        conn.execute(
            "UPDATE im19.source_files SET revision='next-revision',content_hash=%s WHERE id=%s",
            (digest("next revision"), before["source_file_id"]),
        )
    assert database.load(doc)["rights_approved"] is True
    with pytest.raises(PipelineError, match="SOURCE_SUPERSEDED"):
        database.assert_source_rights(doc)


def test_worker_cannot_insert_document_version_directly_as_published(database):
    doc, _ = discover(database)
    source = database.load(doc)
    worker = worker_store(database)
    with pytest.raises(psycopg.errors.RaiseException, match="must begin at DISCOVERED"):
        with worker.tx() as conn:
            conn.execute(
                "INSERT INTO im19.document_versions(id,source_file_id,revision,source_content_hash,pipeline_version,state) "
                "VALUES(%s,%s,%s,%s,'fixture','PUBLISHED')",
                (str(uuid4()), source["source_file_id"], source["revision"], source["source_content_hash"]),
            )


def test_worker_cannot_persist_extraction_without_source_rights(database):
    doc, _ = discover(database)
    with database.tx() as conn:
        conn.execute("UPDATE im19.source_files SET access_authorized=true")
    job = database.claim("worker")
    page = Page("pdf:page:1", "Source text", 1)
    chunk = Chunk(str(uuid4()), doc, page.locator, page.text, 1, 1, digest(page.text))
    with pytest.raises(PipelineError, match="SOURCE_RIGHTS_REVIEW_REQUIRED"):
        database.save_extraction(job, [page], [chunk])


def test_source_rights_reviews_are_append_only_and_worker_cannot_write(database):
    doc, _ = discover(database)
    approve_source_rights(database, doc)
    worker = worker_store(database)
    source = database.load(doc)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with worker.tx() as conn:
            conn.execute(
                "INSERT INTO im19.source_rights_reviews("
                "source_file_id,revision,content_hash,decision,rights_basis,attribution,"
                "evidence_reference,rationale,storage_allowed,embedding_allowed,reviewer_id) "
                "VALUES(%s,%s,%s,'approve','owner_attestation','fake','fake','fake',true,true,'worker')",
                (source["source_file_id"], source["revision"], source["source_content_hash"]),
            )

    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with database.tx() as conn:
            conn.execute(
                "UPDATE im19.source_rights_reviews SET rationale='tampered' WHERE source_file_id=%s",
                (source["source_file_id"],),
            )


def test_unregistered_reviewer_principal_cannot_submit_source_rights(database):
    doc, _ = discover(database)
    with reviewer_tx(database, "fixture-unregistered-reviewer", register=False) as conn:
        with pytest.raises(
            psycopg.errors.InsufficientPrivilege,
            match="not registered or has been revoked",
        ):
            _insert_test_rights_decision(
                conn, doc, "fixture-unregistered-reviewer"
            )


def test_reviewer_principal_cannot_claim_another_reviewer_id(database):
    doc, _ = discover(database)
    review_id = str(uuid4())
    with database.tx() as conn:
        conn.execute(
            "INSERT INTO im19.review_runs(id,document_id,model_version,rubric_version,result) "
            "VALUES(%s,%s,'fixture-model','rubric-v2','{}'::jsonb)",
            (review_id, doc),
        )
    with reviewer_tx(database, "fixture-reviewer-alice") as conn:
        with pytest.raises(
            psycopg.errors.InsufficientPrivilege,
            match="does not match authenticated database principal",
        ):
            conn.execute(
                "INSERT INTO im19.human_approvals("
                "review_run_id,reviewer_id,decision,rationale) "
                "VALUES(%s,'fixture-reviewer-bob','approve','Mismatched identity test')",
                (review_id,),
            )


def test_revoked_reviewer_principal_cannot_submit_source_rights(database):
    doc, _ = discover(database)
    reviewer_id = "fixture-revoked-reviewer"
    _ensure_test_reviewer(database, reviewer_id)
    with database.tx() as conn:
        identity = conn.execute(
            "SELECT database_role_oid FROM im19_security.reviewer_identities "
            "WHERE reviewer_id=%s",
            (reviewer_id,),
        ).fetchone()
        conn.execute(
            "INSERT INTO im19_security.reviewer_identity_revocations("
            "database_role_oid,reviewer_id,reason) VALUES(%s,%s,'Synthetic revocation test')",
            (identity["database_role_oid"], reviewer_id),
        )
    with reviewer_tx(database, reviewer_id, register=False) as conn:
        with pytest.raises(
            psycopg.errors.InsufficientPrivilege,
            match="not registered or has been revoked",
        ):
            _insert_test_rights_decision(conn, doc, reviewer_id)


def test_reviewer_registry_is_private_from_worker_and_approver(database):
    with database.tx() as conn:
        assert not conn.execute(
            "SELECT has_schema_privilege('im19_worker','im19_security','USAGE') AS allowed"
        ).fetchone()["allowed"]
        assert not conn.execute(
            "SELECT has_schema_privilege('im19_approver','im19_security','USAGE') AS allowed"
        ).fetchone()["allowed"]

    with reviewer_tx(database, "fixture-private-registry-reviewer") as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM im19_security.reviewer_identities")


def test_reviewer_identity_and_revocation_records_are_append_only(database):
    reviewer_id = "fixture-immutable-reviewer"
    _ensure_test_reviewer(database, reviewer_id)
    with database.tx() as conn:
        identity = conn.execute(
            "SELECT database_role_oid FROM im19_security.reviewer_identities "
            "WHERE reviewer_id=%s",
            (reviewer_id,),
        ).fetchone()
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with database.tx() as conn:
            conn.execute(
                "UPDATE im19_security.reviewer_identities SET display_name='Changed' "
                "WHERE database_role_oid=%s",
                (identity["database_role_oid"],),
            )
    with database.tx() as conn:
        conn.execute(
            "INSERT INTO im19_security.reviewer_identity_revocations("
            "database_role_oid,reviewer_id,reason) VALUES(%s,%s,'Immutable test')",
            (identity["database_role_oid"], reviewer_id),
        )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with database.tx() as conn:
            conn.execute(
                "UPDATE im19_security.reviewer_identity_revocations SET reason='Changed' "
                "WHERE database_role_oid=%s",
                (identity["database_role_oid"],),
            )


def test_reviewer_registration_rejects_login_that_also_inherits_worker(database):
    reviewer_id = "fixture-worker-reviewer"
    role_name = _ensure_test_reviewer(database, reviewer_id, register=False)
    with database.tx() as conn:
        conn.execute(
            sql.SQL("GRANT im19_worker TO {}").format(sql.Identifier(role_name))
        )
    with pytest.raises(
        psycopg.errors.RaiseException,
        match="reviewer LOGIN must not inherit im19_worker",
    ):
        with database.tx() as conn:
            conn.execute(
                "INSERT INTO im19_security.reviewer_identities("
                "database_role_oid,database_login_role,reviewer_id,display_name) "
                "SELECT pg_catalog.to_regrole(%s)::oid,%s,%s,%s",
                (role_name, role_name, reviewer_id, reviewer_id),
            )

def test_reviewer_registration_rejects_any_additional_group_membership(database):
    reviewer_id = "fixture-extra-registration-" + uuid4().hex
    role_name = _ensure_test_reviewer(database, reviewer_id, register=False)
    extra_role = "im19_test_extra_" + uuid4().hex[:16]
    with psycopg.connect(database.dsn) as admin:
        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(extra_role)))
        admin.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(extra_role), sql.Identifier(role_name)
            )
        )

    try:
        with pytest.raises(
            psycopg.errors.InsufficientPrivilege,
            match="reviewer LOGIN must inherit only im19_approver",
        ):
            with database.tx() as conn:
                conn.execute(
                    "INSERT INTO im19_security.reviewer_identities("
                    "database_role_oid,database_login_role,reviewer_id,display_name) "
                    "SELECT pg_catalog.to_regrole(%s)::oid,%s,%s,%s",
                    (role_name, role_name, reviewer_id, reviewer_id),
                )
    finally:
        with psycopg.connect(database.dsn) as admin:
            admin.execute(
                sql.SQL("REVOKE {} FROM {}").format(
                    sql.Identifier(extra_role), sql.Identifier(role_name)
                )
            )
            admin.execute(
                sql.SQL("REVOKE im19_approver FROM {}").format(sql.Identifier(role_name))
            )
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(extra_role)))


def test_reviewer_decisions_reject_group_memberships_granted_after_registration(database):
    doc, _ = discover(database)
    reviewer_id = "fixture-extra-decision-" + uuid4().hex
    role_name = _ensure_test_reviewer(database, reviewer_id)
    extra_role = "im19_test_extra_" + uuid4().hex[:16]
    with psycopg.connect(database.dsn) as admin:
        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(extra_role)))
        admin.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(extra_role), sql.Identifier(role_name)
            )
        )

    try:
        with reviewer_tx(database, reviewer_id, register=False) as conn:
            with pytest.raises(
                psycopg.errors.InsufficientPrivilege,
                match="reviewer LOGIN must inherit only im19_approver",
            ):
                _insert_test_rights_decision(conn, doc, reviewer_id)
    finally:
        with psycopg.connect(database.dsn) as admin:
            admin.execute(
                sql.SQL("REVOKE {} FROM {}").format(
                    sql.Identifier(extra_role), sql.Identifier(role_name)
                )
            )
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(extra_role)))
