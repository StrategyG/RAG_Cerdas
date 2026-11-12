"""Exact-version local artifact cleanup for the IM19 purge workflow."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from im19.contracts import PipelineError


_TEMP_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\."
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.tmp$"
)


def purge_local_artifacts(workdir: str | Path, document_version_id: str) -> dict:
    """Remove only the UUID-named blob and lease temp files for one document version.

    Symlinks are unlinked as directory entries; their targets are never followed.
    Missing files are treated as already absent, making retries idempotent.
    """
    try:
        version_id = str(UUID(str(document_version_id)))
        root = Path(workdir).expanduser().resolve()
    except (TypeError, ValueError, OSError) as exc:
        raise PipelineError("FAILED", "LOCAL_PURGE_INPUT_INVALID") from exc

    if not root.exists():
        return {
            "blob_files_removed": 0,
            "temp_files_removed": 0,
            "files_verified_absent": True,
        }
    if not root.is_dir():
        raise PipelineError("FAILED", "LOCAL_PURGE_ROOT_NOT_DIRECTORY")

    blob_path = root / f"{version_id}.blob"
    temp_paths = [
        path
        for path in root.glob(f"{version_id}.*.tmp")
        if _TEMP_PATTERN.fullmatch(path.name)
    ]

    blob_removed = 0
    temp_removed = 0
    try:
        if blob_path.exists() or blob_path.is_symlink():
            if blob_path.is_dir() and not blob_path.is_symlink():
                raise PipelineError("FAILED", "LOCAL_PURGE_PATH_TYPE_UNSAFE")
            blob_path.unlink()
            blob_removed = 1

        for path in temp_paths:
            if path.exists() or path.is_symlink():
                if path.is_dir() and not path.is_symlink():
                    raise PipelineError("FAILED", "LOCAL_PURGE_PATH_TYPE_UNSAFE")
                path.unlink()
                temp_removed += 1

        remaining_blob = blob_path.exists() or blob_path.is_symlink()
        remaining_temp = any(
            path.exists() or path.is_symlink()
            for path in root.glob(f"{version_id}.*.tmp")
            if _TEMP_PATTERN.fullmatch(path.name)
        )
    except OSError as exc:
        raise PipelineError("FAILED", "LOCAL_PURGE_IO_ERROR") from exc

    if remaining_blob or remaining_temp:
        raise PipelineError("FAILED", "LOCAL_PURGE_VERIFICATION_FAILED")

    return {
        "blob_files_removed": blob_removed,
        "temp_files_removed": temp_removed,
        "files_verified_absent": True,
    }
