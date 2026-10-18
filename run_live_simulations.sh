#!/usr/bin/env bash
# One entrypoint for offline previews and guided, opt-in live campaigns.
set -euo pipefail
SIMULATION_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SIMULATION_ROOT"
exec "$SIMULATION_ROOT/.venv/bin/python" -m live_simulations workflow "$@"
