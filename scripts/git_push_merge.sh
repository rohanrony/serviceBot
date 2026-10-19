#!/usr/bin/env bash
# Compatibility name: publish a verified feature branch; merging uses PR review/CI.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
BRANCH=""
MESSAGE=""
REMOTE=origin
TARGET=main
DRY_RUN=false
FILES=()
usage() {
    echo "Usage: $0 [--branch NAME] [--message MSG --files PATH ...] [--remote NAME] [--target BRANCH] [--dry-run]"
    echo "Select branch, optionally commit explicit paths, verify exact SHA, then push feature branch."
    echo "No test bypass and no automatic merge/main push. Already committed work is always verified."
}
while [[ $# -gt 0 ]]; do
    case "$1" in
        -b|--branch|-m|--message|--remote|--target)
            [[ $# -ge 2 && -n "$2" && "$2" != -* ]] || { echo "Missing value: $1" >&2; exit 2; }
            case "$1" in
                -b|--branch) BRANCH="$2" ;;
                -m|--message) MESSAGE="$2" ;;
                --remote) REMOTE="$2" ;;
                --target) TARGET="$2" ;;
            esac
            shift 2 ;;
        -f|--files)
            shift
            while [[ $# -gt 0 && "$1" != -* ]]; do FILES+=("$1"); shift; done ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unsupported option: $1" >&2; usage >&2; exit 2 ;;
    esac
done
CURRENT="$(git branch --show-current)"
[[ -n "$CURRENT" ]] || { echo "Select a named feature branch first." >&2; exit 1; }
BRANCH="${BRANCH:-$CURRENT}"
git check-ref-format --branch "$BRANCH" >/dev/null
git check-ref-format "refs/heads/$TARGET" >/dev/null
[[ "$BRANCH" != main && "$BRANCH" != master && "$BRANCH" != "$TARGET" ]] || { echo "Direct protected-target publication is unsupported." >&2; exit 1; }
if [[ -n "$MESSAGE" || ${#FILES[@]} -gt 0 ]]; then
    [[ -n "$MESSAGE" && ${#FILES[@]} -gt 0 ]] || { echo "Committing requires --message and explicit --files." >&2; exit 2; }
fi
if [[ "$DRY_RUN" == true ]]; then
    echo "Select $BRANCH; commit only explicit files if provided; fetch $REMOTE/$TARGET; verify selected SHA; push that SHA to $BRANCH."
    exit 0
fi
if [[ "$BRANCH" != "$CURRENT" ]]; then
    if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
        [[ -z "$(git status --porcelain)" ]] || { echo "Use a clean checkout to switch to an existing branch." >&2; exit 1; }
        git switch "$BRANCH"
    else
        git switch -c "$BRANCH"
    fi
fi
if [[ -n "$MESSAGE" ]]; then
    # --only excludes unrelated staged paths and leaves their index entries intact.
    git add -- "${FILES[@]}"
    git commit --only -m "$MESSAGE" -- "${FILES[@]}"
fi
git fetch "$REMOTE" "refs/heads/$TARGET:refs/remotes/$REMOTE/$TARGET"
HEAD_SHA="$(git rev-parse HEAD)"
BASE_SHA="$(git rev-parse "refs/remotes/$REMOTE/$TARGET")"
"$ROOT/scripts/verify_change.sh" --base "$BASE_SHA" --head "$HEAD_SHA"
# Validate explicitly too, so hook installation is not a prerequisite for this helper.
printf '%s %s %s %s\n' "refs/heads/$BRANCH" "$HEAD_SHA" "refs/heads/$BRANCH" "0000000000000000000000000000000000000000" |
    "$ROOT/.venv/bin/python" "$ROOT/scripts/pre_push.py" "$REMOTE" "$REMOTE" --target "$TARGET"
git -c "verification.targetBranch=$TARGET" push -u "$REMOTE" "$HEAD_SHA:refs/heads/$BRANCH"
echo "Offline verified and pushed: $HEAD_SHA -> $REMOTE/$BRANCH. Merge and deployment remain separate."
