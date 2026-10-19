"""Offline syntax checks for application, tests and publication infrastructure."""

import ast
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    paths = []
    for scope in ("serviceBot", "tests", "e2e", "live_simulations", "scripts"):
        paths.extend((root / scope).rglob("*.py"))
    for path in paths:
        ast.parse(path.read_bytes(), filename=str(path.relative_to(root)))
    shells = [*root.glob("*.sh"), *(root / "scripts").rglob("*.sh")]
    hook = root / ".githooks/pre-push"
    if hook.exists():
        shells.append(hook)
    for path in shells:
        subprocess.run(["bash", "-n", str(path)], check=True)
    script = root / "serviceBot/static/app.js"
    if script.exists():
        subprocess.run(["node", "--check", str(script)], check=True)
    print(f"Static checks passed: {len(paths)} Python files, {len(shells)} shell files, application JavaScript")
    return 0


if __name__ == "__main__":
    sys.exit(main())
