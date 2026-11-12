from uuid import uuid4

import pytest

from im19.contracts import PipelineError
from im19.purge import purge_local_artifacts


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
