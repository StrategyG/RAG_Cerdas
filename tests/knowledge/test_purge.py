from hashlib import sha256
import json
from uuid import uuid4

import psycopg
import pytest

from im19.contracts import PipelineError, KnowledgeUnit, Page, Chunk, digest
from im19.purge import purge_local_artifacts
from .test_postgres import (
    authorize_and_approve_source_rights,
    discover,
    reviewer_tx,
    worker_store,
)


def _storage_root(root, storage_node_id="fixture-node"):
    root.mkdir(parents=True, exist_ok=True)
    (root / ".im19-storage-node-id").write_text(storage_node_id, encoding="utf-8")
    return root


def test_local_purge_removes_only_exact_version_blob_and_lease_temps(tmp_path):
    root = _storage_root(tmp_path / "work")
    version_id = str(uuid4())
    lease_id = str(uuid4())
    blob = root / f"{version_id}.blob"
    temp = root / f"{version_id}.{lease_id}.tmp"
    other_blob = root / f"{uuid4()}.blob"
    unrelated_temp = root / f"{version_id}.not-a-lease.tmp"
    for path in (blob, temp, other_blob, unrelated_temp):
        path.write_text("fixture", encoding="utf-8")

    result = purge_local_artifacts(root, version_id, "fixture-node")

    assert result == {
        "blob_files_removed": 1,
        "temp_files_removed": 1,
        "files_verified_absent": True,
    }
    assert not blob.exists()
    assert not temp.exists()
    assert other_blob.is_file()
    assert unrelated_temp.is_file()
    assert (root / ".im19-storage-node-id").is_file()


def test_local_purge_is_idempotent_after_first_success(tmp_path):
    root = _storage_root(tmp_path / "work")
    version_id = str(uuid4())
    (root / f"{version_id}.blob").write_text("fixture", encoding="utf-8")

    first = purge_local_artifacts(root, version_id, "fixture-node")
    second = purge_local_artifacts(root, version_id, "fixture-node")

    assert first["blob_files_removed"] == 1
    assert second["blob_files_removed"] == 0
    assert second["temp_files_removed"] == 0
    assert second["files_verified_absent"] is True


def test_local_purge_unlinks_symlink_without_touching_external_target(tmp_path):
    root = _storage_root(tmp_path / "work")
    outside = tmp_path / "outside.blob"
    outside.write_text("do not delete", encoding="utf-8")
    version_id = str(uuid4())
    (root / f"{version_id}.blob").symlink_to(outside)

    result = purge_local_artifacts(root, version_id, "fixture-node")

    assert result["files_verified_absent"] is True
    assert not (root / f"{version_id}.blob").is_symlink()
    assert outside.read_text(encoding="utf-8") == "do not delete"


def test_local_purge_fails_closed_when_storage_marker_is_missing_or_wrong(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    version_id = str(uuid4())

    with pytest.raises(PipelineError, match="LOCAL_PURGE_STORAGE_MARKER_MISSING"):
        purge_local_artifacts(root, version_id, "fixture-node")

    (root / ".im19-storage-node-id").write_text("other-node", encoding="utf-8")
    with pytest.raises(PipelineError, match="LOCAL_PURGE_STORAGE_NODE_MISMATCH"):
        purge_local_artifacts(root, version_id, "fixture-node")


def test_local_purge_rejects_non_uuid_version_id(tmp_path):
    root = _storage_root(tmp_path / "work")
    with pytest.raises(PipelineError, match="LOCAL_PURGE_INPUT_INVALID"):
        purge_local_artifacts(root, "../outside", "fixture-node")


def _published_fixture(database):
    data = b"Source evidence for purge."
    document_id, _ = discover(database, data=data)
    authorize_and_approve_source_rights(database, document_id)
    job = database.claim("purge-fixture-worker")
    page_text = "Source evidence for purge."
    page = Page("pdf:page:1", page_text, 1)
    chunk = Chunk(
        str(uuid4()), document_id, page.locator, page.text, 1, 1, digest(page.text)
    )
    database.save_extraction(job, [page], [chunk])
    unit = KnowledgeUnit(
        str(uuid4()),
        document_id,
        "Purge fixture",
        "Test",
        "Purge",
        "principle",
        page_text,
        page_text,
        1,
        1,
        [chunk.chunk_id],
        page.locator,
        "fixture-model",
        digest(page_text),
    )
    database.save_units(job, [unit])
    database.save_embeddings(
        job, [chunk], [[1.0] + [0.0] * 383], "fixture-e5"
    )

    review_id = str(uuid4())
    review_result = {"integrity_ok": True}
    with database.tx() as conn:
        conn.execute(
            "INSERT INTO im19.review_runs("
            "id,document_id,model_version,rubric_version,result) "
            "VALUES(%s,%s,'fixture-model','rubric-v2',%s::jsonb)",
            (review_id, document_id, json.dumps(review_result)),
        )
        conn.execute(
            "INSERT INTO im19.review_findings(review_run_id,knowledge_id,role,finding) "
            "VALUES(%s,%s,'A','{}'::jsonb)",
            (review_id, unit.knowledge_id),
        )
    with reviewer_tx(database, "fixture-human-publisher") as conn:
        conn.execute(
            "INSERT INTO im19.human_approvals("
            "review_run_id,reviewer_id,decision,rationale) "
            "VALUES(%s,'fixture-human-publisher','approve','Synthetic test approval')",
            (review_id,),
        )

    with database.tx() as conn:
        conn.execute(
            "UPDATE im19.document_versions SET state='INDEXED',"
            "classification='{\"status\":\"CLASSIFIED\"}'::jsonb,"
            "review=%s::jsonb,checkpoint=%s::jsonb,content_sha256=%s "
            "WHERE id=%s",
            (
                json.dumps(review_result),
                json.dumps({
                    "review_run_id": review_id,
                    "embedding_model": "fixture-e5",
                }),
                sha256(data).hexdigest(),
                document_id,
            ),
        )
        conn.execute(
            "UPDATE im19.document_versions SET state='PUBLISHED' WHERE id=%s",
            (document_id,),
        )
    assert database.load(document_id)["state"] == "PUBLISHED"
    return document_id


def _request_preview_approve(database, document_id):
    with reviewer_tx(database, "fixture-purge-requester") as conn:
        request_id = conn.execute(
            "SELECT im19.request_source_purge("
            "%s,'owner_request','policy:retention-v1','hold-check:case-42',true) "
            "AS request_id",
            (document_id,),
        ).fetchone()["request_id"]
        preview = conn.execute(
            "SELECT im19.preview_source_purge(%s) AS result",
            (request_id,),
        ).fetchone()["result"]

    with pytest.raises(psycopg.errors.RaiseException, match="cannot approve their own"):
        with reviewer_tx(database, "fixture-purge-requester") as conn:
            conn.execute(
                "SELECT im19.approve_source_purge(%s,'approval:case-42')",
                (request_id,),
            )

    with reviewer_tx(database, "fixture-purge-approver") as conn:
        conn.execute(
            "SELECT im19.approve_source_purge(%s,'approval:case-42')",
            (request_id,),
        )
    return str(request_id), preview


def _finish_local_purge(worker, request_id, document_id, workdir):
    targets = worker.claim_local_purge_targets()
    target = next(
        (
            item for item in targets
            if str(item["request_id"]) == str(request_id)
            and str(item["document_version_id"]) == str(document_id)
        ),
        None,
    )
    assert target is not None
    receipt = purge_local_artifacts(
        workdir, document_id, target["storage_node_id"]
    )
    return worker.record_local_purge_receipt(
        request_id,
        document_id,
        receipt["blob_files_removed"],
        receipt["temp_files_removed"],
    )


def test_purge_requires_two_registered_reviewers_and_removes_exact_version_content(
    database, tmp_path
):
    document_id = _published_fixture(database)
    worker = worker_store(database)
    worker.check_role()

    workdir = _storage_root(tmp_path / "worker-data", "fixture-storage-node")
    lease_id = str(uuid4())
    (workdir / f"{document_id}.blob").write_bytes(b"private source bytes")
    (workdir / f"{document_id}.{lease_id}.tmp").write_bytes(b"partial download")

    request_id, preview = _request_preview_approve(database, document_id)
    assert preview["status"] == "previewed"
    assert preview["artifact_counts"]["chunks"] == 1
    assert preview["artifact_counts"]["embeddings"] == 1
    assert database.load(document_id)["state"] == "QUARANTINED"

    with pytest.raises(psycopg.errors.RaiseException, match="cannot write content"):
        with database.tx() as conn:
            conn.execute(
                "INSERT INTO im19.document_pages("
                "document_id,locator,page_number,text_content,content_hash,structure,"
                "ocr_used,ocr_confidence,warnings) "
                "VALUES(%s,'pdf:page:99',99,'late write',%s,'{}'::jsonb,false,NULL,'[]'::jsonb)",
                (document_id, digest("late write")),
            )

    result = worker.execute_approved_source_purge(request_id)
    assert result["status"] == "database_purged"
    assert _finish_local_purge(worker, request_id, document_id, workdir) == "completed"

    with database.tx() as conn:
        version = conn.execute(
            "SELECT state,checkpoint,classification,review,content_sha256 "
            "FROM im19.document_versions WHERE id=%s",
            (document_id,),
        ).fetchone()
        source = conn.execute(
            "SELECT source_file_id,path,filename,extension,size,source_uri,metadata,"
            "access_authorized,deleted FROM im19.source_files "
            "WHERE id=(SELECT source_file_id FROM im19.document_versions WHERE id=%s)",
            (document_id,),
        ).fetchone()
        request = conn.execute(
            "SELECT status FROM im19_security.purge_requests WHERE id=%s",
            (request_id,),
        ).fetchone()
        tombstone = conn.execute(
            "SELECT deleted_artifact_counts FROM im19_security.purge_tombstones "
            "WHERE request_id=%s",
            (request_id,),
        ).fetchone()
        assert request["status"] == "completed"
        assert version["state"] == "QUARANTINED"
        assert version["checkpoint"] == {}
        assert version["classification"] is None
        assert version["review"] is None
        assert version["content_sha256"] is None
        assert source["source_file_id"] == f"im19-purged:{source['source_file_id'].split(':')[-1]}" or source["source_file_id"].startswith("im19-purged:")
        assert source["path"] == "[purged]"
        assert source["filename"] == "[purged]"
        assert source["size"] == 0
        assert source["metadata"] == {}
        assert source["access_authorized"] is False and source["deleted"] is True
        assert tombstone["deleted_artifact_counts"]["chunks"] == 1
        assert tombstone["deleted_artifact_counts"]["knowledge_units"] == 1
        assert conn.execute(
            "SELECT count(*) AS n FROM im19.source_rights_reviews"
        ).fetchone()["n"] == 1
        for table in (
            "extraction_runs","document_pages","chunks","embeddings",
            "knowledge_units","knowledge_claims","claim_evidence","review_runs",
            "review_findings","human_approvals","knowledge_nodes",
            "knowledge_relations","ingestion_jobs",
        ):
            assert conn.execute(
                f"SELECT count(*) AS n FROM im19.{table}"
            ).fetchone()["n"] == 0
    assert not (workdir / f"{document_id}.blob").exists()
    assert not (workdir / f"{document_id}.{lease_id}.tmp").exists()


def test_purge_is_revision_scoped_and_preserves_newer_source_head(database, tmp_path):
    old_document_id, connection_id = discover(database)
    new_document_id, _ = discover(
        database,
        data=b"newer revision must remain",
        rev="def456",
        source_id="id:book",
        connection_id=connection_id,
    )
    assert database.load(old_document_id)["state"] == "SUPERSEDED"
    worker = worker_store(database)
    workdir = _storage_root(tmp_path / "worker-data", "fixture-storage-node")

    request_id, _ = _request_preview_approve(database, old_document_id)
    assert worker.execute_approved_source_purge(request_id)["status"] == "database_purged"
    assert _finish_local_purge(worker, request_id, old_document_id, workdir) == "completed"

    assert database.load(old_document_id)["state"] == "SUPERSEDED"
    assert database.load(new_document_id)["state"] == "DISCOVERED"
    with database.tx() as conn:
        source = conn.execute(
            "SELECT source_file_id,path,filename,revision,deleted "
            "FROM im19.source_files WHERE id=(SELECT source_file_id "
            "FROM im19.document_versions WHERE id=%s)",
            (new_document_id,),
        ).fetchone()
        assert source["source_file_id"] == "id:book"
        assert source["path"] == "/book.pdf"
        assert source["filename"] == "book.pdf"
        assert source["revision"] == "def456"
        assert source["deleted"] is False


def test_unregistered_reviewer_cannot_request_purge(database):
    document_id, _ = discover(database)
    worker_store(database)
    with reviewer_tx(database, "fixture-unregistered-purge-requester", register=False) as conn:
        with pytest.raises(
            psycopg.errors.InsufficientPrivilege,
            match="not registered, active, or least-privileged",
        ):
            conn.execute(
                "SELECT im19.request_source_purge("
                "%s,'owner_request','policy:retention-v1','hold-check:case-42',true)",
                (document_id,),
            )

