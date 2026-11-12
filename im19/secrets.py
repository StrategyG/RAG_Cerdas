"""Secret-manager adapters. Secret values are never serialized into checkpoints."""

from __future__ import annotations
import os
from pathlib import Path
from typing import Protocol


class SecretStore(Protocol):
    def get(self, name: str) -> str: ...


class MountedSecrets:
    """Read secrets mounted by Docker/Kubernetes/Vault; environment holds paths only."""

    def __init__(self, root: str = "/run/secrets"):
        self.root = Path(root).resolve()

    def get(self, name: str) -> str:
        if not name.replace("_", "").isalnum():
            raise ValueError("Invalid secret name")
        path = (self.root / name.lower()).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Secret path outside mount")
        try:
            value = path.read_text().strip()
        except OSError:
            return ""
        return value


class ColabSecrets:
    def get(self, name: str) -> str:
        from google.colab import userdata

        try:
            return str(userdata.get(name) or "").strip()
        except userdata.SecretNotFoundError:
            return ""


class LegacyEnvironmentSecrets:
    """Compatibility only for old CLI; prefer injected secret-manager adapters."""

    def get(self, name: str) -> str:
        return os.getenv(name, "").strip()
