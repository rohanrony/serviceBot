"""The aggregate check accepts only successful mandatory jobs and complete evidence."""

import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-result", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.offline_result != "success":
        print(f"Required offline job did not succeed: {args.offline_result}", file=sys.stderr)
        return 1
    return subprocess.call([sys.executable, str(Path(__file__).with_name("verify_change.py")),
                            "--check", "--base", args.base, "--head", args.head, "--output", args.output])


if __name__ == "__main__":
    sys.exit(main())
