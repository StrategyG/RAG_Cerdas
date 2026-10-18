#!/usr/bin/env bash
set -euo pipefail

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-test.txt

# Do not copy .env.example to .env: its placeholder key could falsely appear configured.
# Use GitHub Codespaces Secrets, or create an ignored local .env with real credentials.
python scripts/preflight.py || status=$?
case "${status:-0}" in
  0)
    echo "Codespaces bootstrap complete; read-only connectivity checks passed."
    ;;
  1)
    echo "Dependencies installed; Supabase is reachable but no PDF source is configured. Add a local PDF or Dropbox read access."
    ;;
  2)
    echo "Dependencies installed; required Supabase secrets are missing or invalid placeholders. Configure Secrets, restart, and rerun preflight."
    ;;
  3)
    echo "Dependencies installed, but Supabase connectivity/RPC validation failed. Fix the reported error before ingestion."
    ;;
  4)
    echo "Dependencies installed and Supabase reachable, but Dropbox PDF download validation failed. Fix token scope/path before ingestion."
    ;;
  *)
    echo "Preflight exited with unexpected status ${status:-0}; inspect the preflight output before ingestion."
    ;;
esac
