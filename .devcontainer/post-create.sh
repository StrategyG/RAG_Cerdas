#!/usr/bin/env bash
set -euo pipefail

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-test.txt

# Do not copy .env.example to .env: its placeholder key could falsely appear configured.
# Use GitHub Codespaces Secrets, or create an ignored local .env with real credentials.
python scripts/preflight.py || status=$?
if [[ "${status:-0}" -eq 2 ]]; then
  echo "Codespace dependencies installed; configure required Codespaces Secrets, restart, then rerun preflight."
elif [[ "${status:-0}" -eq 1 ]]; then
  echo "Codespace dependencies installed; add source PDFs or configure Dropbox read access before ingestion."
else
  echo "Codespaces bootstrap complete."
fi
