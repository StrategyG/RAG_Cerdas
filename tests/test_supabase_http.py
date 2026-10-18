from scripts.supabase_http import build_supabase_headers


def test_new_secret_key_is_sent_only_as_apikey():
    headers = build_supabase_headers("sb_secret_example-not-real")
    assert headers["apikey"] == "sb_secret_example-not-real"
    assert "Authorization" not in headers


def test_legacy_jwt_key_is_sent_as_apikey_and_bearer():
    legacy_key = "eyJhbGciOiJIUzI1NiJ9.payload.signature"
    headers = build_supabase_headers(legacy_key)
    assert headers["apikey"] == legacy_key
    assert headers["Authorization"] == f"Bearer {legacy_key}"


def test_empty_key_is_rejected():
    try:
        build_supabase_headers("   ")
    except ValueError as exc:
        assert "empty" in str(exc).lower()
    else:
        raise AssertionError("empty API key must be rejected")
