from hashlib import sha256
from unittest.mock import Mock
import pytest
import requests
from im19.contracts import PipelineError
from im19.knowledge_mining.dropbox_discovery import (
    DropboxClient,
    DropboxDiscovery,
    content_hash,
    validate_path,
    BLOCK_SIZE,
)


class Secrets:
    def get(self, name):
        return {
            "DROPBOX_APP_KEY": "app-key",
            "DROPBOX_APP_SECRET": "secret-value",
            "DROPBOX_REFRESH_TOKEN": "refresh-secret",
        }.get(name, "")


class Response:
    def __init__(self, status=200, body=None, headers=None, data=b""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.body = body
        self.headers = headers or {}
        self.data = data
        self.closed = False

    def json(self):
        return self.body

    def close(self):
        self.closed = True

    def iter_content(self, size):
        for i in range(0, len(self.data), size):
            yield self.data[i : i + size]


def client(responses, **kwargs):
    http = Mock()
    http.post.side_effect = responses
    return DropboxClient(
        Secrets(),
        session=http,
        sleep=lambda _: None,
        jitter=lambda: 0,
        clock=lambda: 100,
        **kwargs,
    ), http


def token():
    return Response(
        body={
            "access_token": "access-secret",
            "expires_in": 1000,
            "scope": "files.metadata.read files.content.read",
        }
    )


def entry(data=b"hello", rev="123abc"):
    return {
        ".tag": "file",
        "id": "id:file-1",
        "path_lower": "/book.pdf",
        "path_display": "/Book.pdf",
        "name": "Book.pdf",
        "size": len(data),
        "content_hash": content_hash(data),
        "rev": rev,
        "server_modified": "2026-10-25T00:00:00Z",
    }


@pytest.mark.parametrize("data", [b"", b"hello", b"x" * (BLOCK_SIZE + 7)])
def test_dropbox_block_hash(data):
    expected = sha256(
        b"".join(
            sha256(data[i : i + BLOCK_SIZE]).digest()
            for i in range(0, len(data), BLOCK_SIZE)
        )
    ).hexdigest()
    assert content_hash(data) == expected


def test_401_refreshes_once_then_succeeds_without_logging_secrets(capsys):
    c, http = client(
        [Response(401), token(), Response(body=entry())], legacy_token="expired"
    )
    assert c.metadata("/Book.pdf")["id"] == "id:file-1"
    assert http.post.call_count == 3
    assert http.post.call_args_list[1].args[0].endswith("/oauth2/token")
    assert "secret" not in capsys.readouterr().out


def test_second_401_auth_blocked_not_notfound():
    c, http = client([Response(401), token(), Response(401)], legacy_token="expired")
    with pytest.raises(PipelineError, match="AUTH_BLOCKED:DROPBOX_UNAUTHORIZED"):
        c.metadata("/Book.pdf")
    assert http.post.call_count == 3


def test_revoked_refresh_is_auth_blocked_and_body_not_exposed():
    c, _ = client([Response(401, {"error": "contains refresh-secret"})])
    with pytest.raises(PipelineError) as e:
        c.metadata("/Book.pdf")
    assert e.value.status == "AUTH_BLOCKED" and "secret" not in str(e.value)


def test_retry_after_and_timeout_are_bounded():
    sleeps = []
    c, http = client(
        [Response(429, headers={"Retry-After": "2"}), Response(body=entry())],
        legacy_token="ok",
    )
    c.sleep = sleeps.append
    assert c.metadata("/Book.pdf")["name"] == "Book.pdf" and sleeps == [2]
    c, http = client([requests.Timeout()] * 4, legacy_token="ok")
    with pytest.raises(PipelineError, match="RETRY_PENDING"):
        c.metadata("/Book.pdf")
    assert http.post.call_count == 4


def test_download_pins_revision_and_checks_hash_and_size():
    data = b"%PDF-valid sample"
    c, http = client([Response(data=data)], legacy_token="ok")
    assert c.download(entry(data)) == data
    assert "rev:123abc" in http.post.call_args.kwargs["headers"]["Dropbox-API-Arg"]
    c, _ = client([Response(data=data + b"x")], legacy_token="ok")
    with pytest.raises(PipelineError, match="QUARANTINED"):
        c.download(entry(data))
    c, _ = client([Response(data=b"x" * len(data))], legacy_token="ok")
    with pytest.raises(PipelineError, match="SOURCE_HASH"):
        c.download(entry(data))


def test_download_quota_and_write_route_are_rejected_before_network():
    c, http = client([], legacy_token="ok")
    with pytest.raises(PipelineError):
        c.download(entry(b"x" * 10), max_bytes=5)
    with pytest.raises(ValueError):
        c._request("files/delete_v2", {})
    assert not http.post.called


@pytest.mark.parametrize(
    "path", ["../../etc/passwd", "//root.pdf", "/a/../x", "/a\\x", "/a\x00.pdf"]
)
def test_unsafe_paths(path):
    with pytest.raises(ValueError):
        validate_path(path)


def test_cursor_reset_is_not_silently_advanced():
    c, _ = client([Response(409, {"error": {".tag": "reset"}})], legacy_token="ok")
    with pytest.raises(PipelineError, match="CURSOR_RESET_REQUIRES_RECONCILIATION"):
        c.list_page("", "old")


def test_pagination_commits_entries_and_cursor_atomically():
    c, _ = client(
        [
            Response(body={"entries": [entry()], "cursor": "c1", "has_more": True}),
            Response(
                body={
                    "entries": [{".tag": "deleted", "path_lower": "/book.pdf"}],
                    "cursor": "c2",
                    "has_more": False,
                }
            ),
        ],
        legacy_token="ok",
    )
    store = Mock()
    store.source_connection.return_value = {
        "root_path": "",
        "access_scope": "app_folder",
        "cursor": None,
    }
    result = DropboxDiscovery(c, store).run("connection")
    assert result["entries"] == 2 and store.commit_discovery_page.call_count == 2
    assert store.commit_discovery_page.call_args_list[1].args[:3] == (
        "connection",
        "c1",
        "c2",
    )


def test_commit_failure_does_not_advance_to_next_page():
    c, http = client(
        [Response(body={"entries": [entry()], "cursor": "c1", "has_more": True})],
        legacy_token="ok",
    )
    store = Mock()
    store.source_connection.return_value = {
        "root_path": "",
        "access_scope": "app_folder",
        "cursor": None,
    }
    store.commit_discovery_page.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        DropboxDiscovery(c, store).run("connection")
    assert http.post.call_count == 1
