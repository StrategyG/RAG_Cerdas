"""Metadata-first Dropbox connector with bounded retries and atomic cursor checkpoints.

Only read endpoints are reachable. A stale/revoked token is AUTH_BLOCKED, never 404.
Dropbox content_hash is a block hash, distinct from the whole-file SHA-256.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import PurePosixPath
import random
import re
import time

import requests
from im19.contracts import PipelineError
from im19.secrets import SecretStore

READ_SCOPES = frozenset({"files.metadata.read", "files.content.read"})
READ_ROUTES = frozenset(
    {"files/list_folder", "files/list_folder/continue", "files/get_metadata"}
)
BLOCK_SIZE = 4 * 1024 * 1024


def content_hash(data: bytes) -> str:
    blocks = b"".join(
        hashlib.sha256(data[i : i + BLOCK_SIZE]).digest()
        for i in range(0, len(data), BLOCK_SIZE)
    )
    return hashlib.sha256(blocks).hexdigest()


def validate_path(path: str, *, root: bool = False) -> str:
    if root and path == "":
        return path
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise ValueError("One absolute Dropbox path required")
    if (
        "\\" in path
        or any(ord(c) < 32 for c in path)
        or ".." in PurePosixPath(path).parts
    ):
        raise ValueError("Unsafe Dropbox path")
    return path


class DropboxClient:
    def __init__(
        self,
        secrets: SecretStore,
        *,
        session=None,
        sleep=time.sleep,
        clock=time.monotonic,
        jitter=random.random,
        max_attempts: int = 4,
        legacy_token: str = "",
    ):
        if not 1 <= max_attempts <= 6:
            raise ValueError("max_attempts must be 1..6")
        self.secrets, self.http = secrets, session or requests.Session()
        self.sleep, self.clock, self.jitter = sleep, clock, jitter
        self.max_attempts = max_attempts
        self._token, self._expires = legacy_token, 0.0
        self._legacy = bool(legacy_token)

    def _refresh(self):
        refresh = self.secrets.get("DROPBOX_REFRESH_TOKEN")
        key = self.secrets.get("DROPBOX_APP_KEY")
        secret = self.secrets.get("DROPBOX_APP_SECRET")
        if not refresh or not key or not secret:
            raise PipelineError("AUTH_BLOCKED", "OAUTH_REFRESH_SECRETS_MISSING")
        for attempt in range(self.max_attempts):
            try:
                response = self.http.post(
                    "https://api.dropboxapi.com/oauth2/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh,
                        "client_id": key,
                        "client_secret": secret,
                        "scope": " ".join(sorted(READ_SCOPES)),
                    },
                    timeout=(10, 30),
                    allow_redirects=False,
                )
            except requests.RequestException:
                if attempt + 1 == self.max_attempts:
                    raise PipelineError("RETRY_PENDING", "OAUTH_TIMEOUT") from None
                self._backoff(attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                self._backoff(attempt, response)
                continue
            if not response.ok:
                raise PipelineError("AUTH_BLOCKED", "OAUTH_REFRESH_REJECTED")
            try:
                body = response.json()
                token, expires = body["access_token"], int(body["expires_in"])
                scopes = set(str(body.get("scope", " ".join(READ_SCOPES))).split())
                if not token or expires < 1 or not scopes.issubset(READ_SCOPES):
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise PipelineError("AUTH_BLOCKED", "OAUTH_RESPONSE_INVALID") from None
            self._token, self._expires, self._legacy = (
                token,
                self.clock() + expires,
                False,
            )
            return
        raise PipelineError("RETRY_PENDING", "OAUTH_RETRY_EXHAUSTED")

    def _backoff(self, attempt, response=None):
        retry_after = 0.0
        if response is not None:
            try:
                retry_after = float(response.headers.get("Retry-After", "0"))
            except (TypeError, ValueError):
                pass
        if retry_after > 120:
            raise PipelineError("RETRY_PENDING", "RATE_LIMIT_DEFERRED")
        self.sleep(max(retry_after, min(30, 2**attempt) + self.jitter()))

    def _request(self, route: str, body: dict, *, download=False):
        if route not in READ_ROUTES and not (download and route == "files/download"):
            raise ValueError("Dropbox route is not read-only allowlisted")
        refreshed = False
        for attempt in range(self.max_attempts + 1):
            if not self._token or (
                not self._legacy and self.clock() >= self._expires - 30
            ):
                self._refresh()
            headers = {"Authorization": f"Bearer {self._token}"}
            if download:
                headers["Dropbox-API-Arg"] = json.dumps(
                    body, ensure_ascii=True, separators=(",", ":")
                )
                kwargs = {"stream": True}
                host = "content.dropboxapi.com"
            else:
                kwargs = {"json": body}
                host = "api.dropboxapi.com"
            try:
                response = self.http.post(
                    f"https://{host}/2/{route}",
                    headers=headers,
                    timeout=(10, 60),
                    allow_redirects=False,
                    **kwargs,
                )
            except requests.RequestException:
                if attempt >= self.max_attempts - 1:
                    raise PipelineError("RETRY_PENDING", "DROPBOX_TIMEOUT") from None
                self._backoff(attempt)
                continue
            if response.status_code == 401:
                response.close()
                if refreshed:
                    raise PipelineError("AUTH_BLOCKED", "DROPBOX_UNAUTHORIZED")
                self._refresh()
                refreshed = True
                continue
            if response.status_code == 429 or response.status_code >= 500:
                try:
                    if attempt >= self.max_attempts - 1:
                        raise PipelineError("RETRY_PENDING", "DROPBOX_RETRY_EXHAUSTED")
                    self._backoff(attempt, response)
                finally:
                    response.close()
                continue
            if not response.ok:
                code = "DROPBOX_HTTP_" + str(response.status_code)
                if response.status_code == 409 and route.endswith("continue"):
                    try:
                        if response.json().get("error", {}).get(".tag") == "reset":
                            code = "CURSOR_RESET_REQUIRES_RECONCILIATION"
                    except (ValueError, AttributeError):
                        pass
                response.close()
                status = (
                    "AUTH_BLOCKED"
                    if response.status_code == 403
                    else "NEEDS_HUMAN_REVIEW"
                )
                raise PipelineError(status, code)
            return response
        raise PipelineError("AUTH_BLOCKED", "DROPBOX_UNAUTHORIZED")

    def metadata(self, path: str) -> dict:
        validate_path(path)
        response = self._request("files/get_metadata", {"path": path})
        try:
            return response.json()
        finally:
            response.close()

    def list_page(self, root: str, cursor: str | None) -> dict:
        validate_path(root, root=True)
        body = (
            {"cursor": cursor}
            if cursor
            else {
                "path": root,
                "recursive": True,
                "include_deleted": True,
                "limit": 200,
            }
        )
        route = "files/list_folder/continue" if cursor else "files/list_folder"
        response = self._request(route, body)
        try:
            result = response.json()
            if (
                not isinstance(result.get("entries"), list)
                or not result.get("cursor")
                or type(result.get("has_more")) is not bool
            ):
                raise PipelineError("FAILED", "DROPBOX_LIST_SHAPE")
            return result
        finally:
            response.close()

    def download(self, metadata: dict, max_bytes: int = 64 * 1024 * 1024) -> bytes:
        size = metadata.get("size")
        if type(size) is not int or not 0 < size <= max_bytes:
            raise PipelineError("NEEDS_HUMAN_REVIEW", "FILE_SIZE_QUOTA")
        rev = metadata.get("rev", "")
        if not re.fullmatch(r"[0-9a-fA-F]{5,128}", rev):
            raise PipelineError("QUARANTINED", "REVISION_MISSING")
        response = self._request(
            "files/download", {"path": "rev:" + rev}, download=True
        )
        try:
            payload = bytearray()
            for block in response.iter_content(64 * 1024):
                payload.extend(block)
                if len(payload) > max_bytes or len(payload) > size:
                    raise PipelineError("QUARANTINED", "DOWNLOAD_SIZE_EXCEEDED")
            data = bytes(payload)
        except requests.RequestException:
            raise PipelineError("RETRY_PENDING", "DOWNLOAD_INTERRUPTED") from None
        finally:
            response.close()
        if len(data) != size or content_hash(data) != metadata.get("content_hash"):
            raise PipelineError("QUARANTINED", "SOURCE_HASH_OR_SIZE_MISMATCH")
        return data


def normalize_entry(entry: dict, access_scope: str) -> dict:
    tag = entry.get(".tag")
    path = validate_path(entry.get("path_lower") or entry.get("path_display") or "")
    if tag == "deleted":
        return {"deleted": True, "path": path}
    if tag == "folder":
        return {"folder": True, "path": path}
    if tag != "file" or type(entry.get("size")) is not int or entry["size"] < 0:
        raise PipelineError("QUARANTINED", "INVALID_METADATA")
    if not re.fullmatch(r"[a-f0-9]{64}", str(entry.get("content_hash", ""))):
        raise PipelineError("QUARANTINED", "CONTENT_HASH_MISSING")
    if not str(entry.get("id", "")).startswith("id:") or not entry.get("rev"):
        raise PipelineError("QUARANTINED", "IDENTITY_MISSING")
    modified = datetime.fromisoformat(entry["server_modified"].replace("Z", "+00:00"))
    if modified.tzinfo is None:
        raise PipelineError("QUARANTINED", "MODIFIED_TIME_INVALID")
    return {
        "source_file_id": entry["id"],
        "path": path,
        "filename": entry["name"],
        "extension": PurePosixPath(entry["name"]).suffix.lower(),
        "size": entry["size"],
        "content_hash": entry["content_hash"],
        "revision": entry["rev"],
        "modified_time": modified.isoformat(),
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "source_uri": "dropbox:" + entry["id"],
        "access_scope": access_scope,
        "download_metadata": entry,
    }


class DropboxDiscovery:
    def __init__(self, client: DropboxClient, store):
        self.client, self.store = client, store

    def run(self, connection_id: str, max_pages: int = 10) -> dict:
        if not 1 <= max_pages <= 100:
            raise ValueError("max_pages must be 1..100")
        connection = self.store.source_connection(connection_id)
        if connection.get("status") == "AUTH_BLOCKED":
            raise PipelineError("AUTH_BLOCKED", "OPERATOR_REAUTH_REQUIRED")
        cursor = connection.get("cursor")
        count = 0
        more = False
        try:
            for _ in range(max_pages):
                page = self.client.list_page(connection["root_path"], cursor)
                entries = [
                    normalize_entry(e, connection["access_scope"])
                    for e in page["entries"]
                ]
                # Optimistic cursor lease and the entire page persist in one transaction.
                self.store.commit_discovery_page(
                    connection_id, cursor, page["cursor"], entries
                )
                cursor, more = page["cursor"], page["has_more"]
                count += len(entries)
                if not more:
                    break
        except PipelineError as exc:
            self.store.block_connection(connection_id, exc.status, exc.code)
            raise
        return {"entries": count, "has_more": more, "status": "CHECKPOINTED"}
