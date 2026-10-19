#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
CURRENT="$(git config --get core.hooksPath || true)"
[[ -z "$CURRENT" || "$CURRENT" == .githooks ]] || { echo "Existing hooksPath $CURRENT must be integrated manually." >&2; exit 1; }
HOOKS="$(git rev-parse --git-path hooks)"
[[ ! -f "$HOOKS/pre-push" || "$CURRENT" == .githooks ]] || { echo "Existing pre-push hook must be integrated manually." >&2; exit 1; }
git config --local core.hooksPath .githooks
echo "Installed local pre-push evidence validation (.githooks)."
