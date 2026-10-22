from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = (ROOT / "supabase/functions/whatsapp-gateway/index.ts").read_text(encoding="utf-8")
MIGRATION = (ROOT / "supabase/migrations/20261020130000_whatsapp_inbox.sql").read_text(encoding="utf-8")


def test_webhook_verification_and_signature_validation_are_present():
    assert "hub.verify_token" in GATEWAY
    assert "x-hub-signature-256" in GATEWAY
    assert 'name: "HMAC", hash: "SHA-256"' in GATEWAY
    assert 'return json({ error: "Invalid webhook signature" }, 401)' in GATEWAY


def test_inbound_message_upsert_is_idempotent():
    assert "on_conflict=provider_message_id" in GATEWAY
    assert "resolution=ignore-duplicates,return=minimal" in GATEWAY
    assert "provider_message_id text not null unique" in MIGRATION


def test_outbound_reply_requires_explicit_operator_secret_and_approved_text():
    assert 'req.headers.get("x-approval-secret")' in GATEWAY
    assert 'body.approved_reply' in GATEWAY
    assert 'path.endsWith("/approve")' in GATEWAY
    assert "WHATSAPP_ACCESS_TOKEN" in GATEWAY


def test_send_path_claims_message_before_calling_meta():
    assert 'status=in.(needs_review,draft_ready)' in GATEWAY
    assert '{ status: "sending" }' in GATEWAY
    assert 'status=eq.sending' in GATEWAY
    assert "'sending'" in MIGRATION


def test_no_secret_values_are_committed_in_template_code():
    for marker in ("META_APP_SECRET", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_APPROVAL_SECRET"):
        assert marker in GATEWAY
    assert "Bearer EAA" not in GATEWAY
    assert "sb_secret_" not in GATEWAY
