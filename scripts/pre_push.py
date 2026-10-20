"""Validate all outgoing commits against the current remote target."""

import argparse
from pathlib import Path
import subprocess
import sys

from verify_change import VerificationError, require, resolve, validate_receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("remote")
    parser.add_argument("url")
    parser.add_argument("--target")
    args = parser.parse_args()
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    if args.target is None:
        configured = subprocess.run(["git", "config", "--get", "verification.targetBranch"], capture_output=True, text=True)
        args.target = configured.stdout.strip() or "main"
    subprocess.run(["git", "check-ref-format", f"refs/heads/{args.target}"], check=True)
    updates = [line.split() for line in sys.stdin if line.strip()]
    require(all(len(update) == 4 for update in updates), "Malformed pre-push update")
    for _, _, remote_ref, _ in updates:
        require(remote_ref.startswith("refs/heads/"), "Only verified branch publication is supported")
        require(remote_ref not in {"refs/heads/main", "refs/heads/master", f"refs/heads/{args.target}"},
                "Direct target publication is blocked; use reviewed PR merge")
    updates = [update for update in updates if set(update[1]) != {"0"}]
    if not updates:
        return 0
    remote = subprocess.check_output(["git", "ls-remote", "--exit-code", args.remote, f"refs/heads/{args.target}"], text=True)
    base = remote.split()[0]
    require(resolve(root, base) == base, "Fetch the current target commit before pushing")
    for _, head, _, _ in updates:
        require(resolve(root, head) == head, "Outgoing object must be a commit")
        output = root / "scratch/verification" / f"{head}-{base}"
        validate_receipt(root, output, head, base)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (VerificationError, subprocess.SubprocessError, OSError, ValueError, KeyError, IndexError) as error:
        print(f"Pre-push blocked: {error}\nFetch the target and run ./scripts/verify_change.sh --base <target> --head <outgoing-sha>.", file=sys.stderr)
        sys.exit(1)
