#!/usr/bin/env python3
"""Validate and safely extract a workspace tar.gz archive without following links."""
from __future__ import annotations

import argparse
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


MAX_MEMBERS = 25_000
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
RESERVED_MEMBER_NAMES = {"workspace_manifest.txt"}


def validate_members(members, root: Path, *, max_members=MAX_MEMBERS,
                     max_uncompressed_bytes=MAX_UNCOMPRESSED_BYTES):
    """Validate all archive members before any extraction or destination writes."""
    if len(members) > max_members:
        raise ValueError(f"archive has too many members: {len(members)}")

    seen: dict[str, bool] = {}
    validated = []
    total_size = 0
    root = root.resolve()

    for member in members:
        raw_name = member.name
        path = PurePosixPath(raw_name)
        normalized = path.as_posix().rstrip("/")
        basename = PurePosixPath(normalized).name if normalized else ""
        if (
            not raw_name
            or path.is_absolute()
            or chr(92) in raw_name
            or "\x00" in raw_name
            or ".." in path.parts
            or not path.parts
            or ":" in path.parts[0]
            or basename in RESERVED_MEMBER_NAMES
        ):
            raise ValueError(f"unsafe archive path rejected: {raw_name!r}")
        if not (member.isdir() or member.isreg()):
            raise ValueError(f"links/special archive entries are not allowed: {raw_name!r}")

        if not normalized or normalized in seen:
            raise ValueError(f"duplicate or ambiguous archive path rejected: {normalized!r}")

        # Reject a regular-file ancestor (a file cannot also be a directory).
        parts = PurePosixPath(normalized).parts
        for i in range(1, len(parts)):
            ancestor = PurePosixPath(*parts[:i]).as_posix()
            if seen.get(ancestor) is False:
                raise ValueError(f"archive file/directory conflict: {ancestor!r}")
        if member.isreg() and any(
            existing.startswith(normalized + "/") for existing in seen
        ):
            raise ValueError(f"archive file/directory conflict: {normalized!r}")

        target = (root / Path(*parts)).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"archive path escapes destination: {raw_name!r}") from exc

        if member.isdir():
            seen[normalized] = True
        else:
            seen[normalized] = False
            total_size += member.size
            if member.size < 0 or total_size > max_uncompressed_bytes:
                raise ValueError("archive exceeds the uncompressed size limit")
        validated.append((member, path, target))

    return validated, total_size


def extract_archive(archive: Path, destination: Path) -> tuple[int, int]:
    if not archive.is_file():
        raise FileNotFoundError(f"archive not found: {archive}")
    if destination.exists():
        raise FileExistsError("destination already exists; refusing to overwrite it")

    # Validate every entry before creating a staging directory.
    with tarfile.open(archive, mode="r:gz") as tar:
        members, total_size = validate_members(tar.getmembers(), destination.resolve())
        staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
        try:
            root = staging.resolve()
            for member, path, _target in members:
                target = (root / Path(*path.parts)).resolve()
                try:
                    target.relative_to(root)
                except ValueError as exc:
                    raise ValueError(f"archive path escapes staging directory: {member.name!r}") from exc
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise ValueError(f"could not read archive member: {member.name!r}")
                with source, target.open("xb") as output:
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)

            files = sorted(
                p.relative_to(root).as_posix()
                for p in root.rglob("*")
                if p.is_file()
            )
            manifest = root / ".workspace_manifest.txt"
            manifest.write_text("\n".join(files) + ("\n" if files else ""), encoding="utf-8")
            staging.rename(destination)
            return len(files), total_size
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("workspace(1).tar.gz"))
    parser.add_argument("--destination", type=Path, default=Path("extracted_workspace"))
    args = parser.parse_args()
    count, size = extract_archive(args.archive, args.destination)
    print(f"Archive validated. Extracted files: {count}; declared uncompressed bytes: {size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
