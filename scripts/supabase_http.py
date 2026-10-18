"""Build Supabase REST headers compatible with legacy JWT and new API key formats."""
from __future__ import annotations


def build_supabase_headers(api_key: str) -> dict[str, str]:
    key = (api_key or "").strip()
    if not key:
        raise ValueError("Supabase API key is empty")

    headers = {
        "apikey": key,
        "Content-Type": "application/json",
        "Accept-Profile": "public",
        "Content-Profile": "public",
    }
    # New Supabase sb_* keys are not JWTs; send them on apikey only.
    # Legacy anon/service_role keys are JWTs and require the bearer header.
    if not key.startswith("sb_"):
        headers["Authorization"] = f"Bearer {key}"
    return headers
