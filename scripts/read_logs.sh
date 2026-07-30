#!/usr/bin/env bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
ROOT="$( cd "$DIR/.." >/dev/null 2>&1 && pwd )"

if [ -f "$ROOT/.venv/bin/python" ]; then
    "$ROOT/.venv/bin/python" "$DIR/read_supabase_logs.py" "$@"
else
    python3 "$DIR/read_supabase_logs.py" "$@"
fi
