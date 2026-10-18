from scripts import preflight


def test_missing_credentials_block_without_network(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("DROPBOX_ACCESS_TOKEN", raising=False)

    result = preflight.main()
    output = capsys.readouterr().out

    assert result == 2
    assert "SUPABASE_URL: missing or placeholder" in output
    assert "SUPABASE_SERVICE_ROLE_KEY: missing or placeholder" in output


def test_connectivity_success_is_reported_without_secret_values(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", "https://example-ref.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "not-a-real-but-present-test-value")
    monkeypatch.setenv("DROPBOX_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr(preflight, "check_supabase", lambda: (True, "read-only worker RPC reachable"))
    monkeypatch.setattr(preflight, "check_dropbox", lambda: (True, "read-only PDF download verified (100 bytes)"))

    result = preflight.main()
    output = capsys.readouterr().out

    assert result == 0
    assert "Supabase connectivity: OK" in output
    assert "Dropbox connectivity: OK" in output
    assert "test-token" not in output
    assert "not-a-real-but-present-test-value" not in output
