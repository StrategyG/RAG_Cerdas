"""Reproducible local model tree identity; no network or model execution."""

import hashlib
from pathlib import Path
from im19.contracts import PipelineError


def tree_sha256(model_path):
    root = Path(model_path).resolve()
    if not root.is_dir():
        raise PipelineError("AUTH_BLOCKED", "LOCAL_MODEL_DIRECTORY_REQUIRED")
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if ".git" in rel.parts:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise PipelineError("AUTH_BLOCKED", "MODEL_SYMLINK_REJECTED")
        if not path.is_file():
            continue
        file_hash = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                file_hash.update(block)
        digest.update(rel.as_posix().encode() + b"\x00" + file_hash.digest())
        count += 1
    if not count:
        raise PipelineError("AUTH_BLOCKED", "LOCAL_MODEL_EMPTY")
    return digest.hexdigest()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_directory")
    print(tree_sha256(parser.parse_args().model_directory))
