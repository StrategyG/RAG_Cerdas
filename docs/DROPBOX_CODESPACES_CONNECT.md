# Dropbox ↔ GitHub Codespaces: Connection and Verification

## Purpose

Verify Dropbox access from the actual GitHub Codespaces environment used by the Institutional RAG pipeline. A working Dropbox connection in ChatGPT does **not** prove that Codespaces has Dropbox credentials.

Repository: `StrategyG/RAG_Cerdas`  
Target branch: `codespaces-institutional-rag`

## Safety rules

- Never print or commit access tokens, refresh tokens, app secrets, or service-role keys.
- Store credentials in GitHub Codespaces Secrets and expose them to the active Codespace as environment variables.
- Do not ingest the entire corpus, delete records, run migrations, or modify production data during the connectivity check.
- Start with read-only checks and one small, known PDF.
- Do not report success until authentication and a file download have both been verified from Codespaces.

## Step 1 — Inspect the current workspace

Run in the Codespaces terminal:

```bash
pwd
git branch --show-current
git status --short
git log -1 --oneline
```

Confirm the current branch is `codespaces-institutional-rag`. Review the existing Dropbox client and project configuration before creating new files or duplicating functionality.

## Step 2 — Check whether the token is present

This check reveals only whether the variable exists; it never prints the secret:

```bash
if [ -n "${DROPBOX_ACCESS_TOKEN:-}" ]; then
  echo "DROPBOX_ACCESS_TOKEN_PRESENT"
else
  echo "DROPBOX_ACCESS_TOKEN_MISSING"
fi
```

If missing, add the required credential using GitHub repository Settings → Secrets and variables → Codespaces. Do not paste secrets into chat, source code, shell history, or committed `.env` files. Restart or rebuild the Codespace if required for updated secrets to become available.

For a persistent integration, prefer an OAuth refresh-token flow using appropriately scoped Dropbox app credentials, following the project's existing auth design. Do not assume App Folder access can read files elsewhere in Dropbox; verify the app's access type and granted permissions.

## Step 3 — Test Dropbox API authentication

Only run this after the token is available:

```bash
set +x
if [ -z "${DROPBOX_ACCESS_TOKEN:-}" ]; then
  echo "DROPBOX_TOKEN_MISSING"
  exit 2
fi

http_code=$(curl --silent --show-error \
  --output /tmp/dropbox_account_check.json \
  --write-out '%{http_code}' \
  --request POST 'https://api.dropboxapi.com/2/users/get_current_account' \
  --header "Authorization: Bearer ${DROPBOX_ACCESS_TOKEN}")

echo "DROPBOX_API_HTTP_STATUS=${http_code}"
rm -f /tmp/dropbox_account_check.json
```

Interpretation:
- `200`: authentication succeeded.
- `401`: token invalid, revoked, or expired.
- `403`: access or policy restriction; inspect permissions.
- `000`: likely network, DNS, TLS, or connection failure.

Do not print the response body because account metadata is not needed for this check.

## Step 4 — Verify one known file

Use the existing Dropbox client or a reviewed script already present in the repository. List metadata first, then download exactly one small PDF whose path is confirmed to exist and that the authorized Dropbox account can read. Validate that the downloaded file is non-empty and begins with a PDF signature; remove the temporary file afterward.

Do not invent a path. Do not dump document contents or credentials into logs. Treat path errors, permission errors, rate limits, and network failures separately.

## Step 5 — Integrate only after the smoke test passes

- Reuse the repository's existing Dropbox client and configuration where possible.
- Add retries only for transient errors, with bounded attempts and backoff.
- Keep secrets out of logs and exceptions.
- Preserve source path, file metadata, and content hash for idempotent ingestion.
- Do not run full-corpus ingestion or change Supabase records until the single-file test passes and the proposed change has been reviewed.
- Run the project's relevant unit tests and report exact results.

## Acceptance criteria

Mark the integration `CONNECTED` only when both of the following have been proven from the active Codespace:
1. Dropbox API authentication succeeds.
2. Metadata access and download of one known, authorized PDF succeed.

Otherwise report `PARTIALLY_CONNECTED`, `NOT_CONNECTED`, or `BLOCKED` with the observed error and next action. A saved secret, successful CI run, or ChatGPT's Dropbox connector alone is not proof of a working Codespaces connection.

## Final report template

- Branch and latest commit:
- Environment variable status (presence only):
- Dropbox API HTTP status:
- Metadata test:
- One-file download and PDF validation:
- Tests run and results:
- Files changed:
- Remaining blockers:
