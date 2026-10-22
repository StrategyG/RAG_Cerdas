import io
import tarfile
from pathlib import Path

import pytest

from scripts.validate_workspace_archive import extract_archive


def make_archive(path: Path, entries):
    with tarfile.open(path, "w:gz") as tar:
        for name, kind, data in entries:
            info = tarfile.TarInfo(name)
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            elif kind == "file":
                payload = data if isinstance(data, bytes) else data.encode()
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = data
                tar.addfile(info)


def test_extracts_valid_archive_and_writes_manifest(tmp_path):
    archive = tmp_path / "valid.tar.gz"
    destination = tmp_path / "out"
    make_archive(archive, [
        ("docs", "dir", ""),
        ("docs/guide.txt", "file", "safe content"),
    ])

    count, size = extract_archive(archive, destination)

    assert (destination / "docs/guide.txt").read_text() == "safe content"
    assert "docs/guide.txt" in (destination / "workspace_manifest.txt").read_text()
    assert count == 1
    assert size == len("safe content")


@pytest.mark.parametrize(
    "entries",
    [
        [("../escape.txt", "file", "bad")],
        [("/absolute.txt", "file", "bad")],
        [("folder\\escape.txt", "file", "bad")],
        [("safe.txt", "symlink", "../outside")],
        [("same.txt", "file", "one"), ("same.txt", "file", "two")],
        [("node/child.txt", "file", "child"), ("node", "file", "parent")],
    ],
)
def test_rejects_unsafe_or_ambiguous_archives_before_creating_destination(tmp_path, entries):
    archive = tmp_path / "bad.tar.gz"
    destination = tmp_path / "out"
    make_archive(archive, entries)

    with pytest.raises(ValueError):
        extract_archive(archive, destination)

    assert not destination.exists()


def test_refuses_to_overwrite_existing_destination(tmp_path):
    archive = tmp_path / "valid.tar.gz"
    destination = tmp_path / "out"
    destination.mkdir()
    make_archive(archive, [("safe.txt", "file", "safe")])

    with pytest.raises(FileExistsError):
        extract_archive(archive, destination)

    assert list(destination.iterdir()) == []


def test_failed_extraction_cleans_staging_directory(tmp_path, monkeypatch):
    archive = tmp_path / "valid.tar.gz"
    destination = tmp_path / "out"
    make_archive(archive, [("safe.txt", "file", "safe")])

    monkeypatch.setattr(tarfile.TarFile, "extractfile", lambda self, member: None)

    with pytest.raises(ValueError, match="could not read archive member"):
        extract_archive(archive, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".out.tmp-*"))
