#!/usr/bin/env bash
set -euo pipefail
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
if [ -f .env.example ] && [ ! -f .env ]; then cp .env.example .env; fi
echo "Codespaces setup complete. Configure Codespaces Secrets, then run python scripts/preflight.py."
