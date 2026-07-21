#!/usr/bin/env bash
set -e

# Script to safely merge current feature branch into main and push to remote

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
REMOTE_NAME=$(git remote | head -n 1)

if [ -z "$REMOTE_NAME" ]; then
    REMOTE_NAME="origin"
fi

echo "=========================================="
echo " Current Branch : $CURRENT_BRANCH"
echo " Remote Name    : $REMOTE_NAME"
echo " Target Branch  : main"
echo "=========================================="

# Check for uncommitted changes
if [ -n "$(git status --porcelain)" ]; then
    echo "Error: Working directory has uncommitted changes. Please commit or stash them first."
    exit 1
fi

echo "1. Fetching latest remote branches..."
git fetch "$REMOTE_NAME"

echo "2. Switching to main branch..."
git checkout main

echo "3. Pulling latest main branch from $REMOTE_NAME..."
git pull "$REMOTE_NAME" main --rebase || true

echo "4. Merging $CURRENT_BRANCH into main..."
git merge "$CURRENT_BRANCH" -m "merge: release $CURRENT_BRANCH into main"

echo "5. Pushing main to $REMOTE_NAME..."
git push "$REMOTE_NAME" main

echo "6. Returning to original branch $CURRENT_BRANCH..."
git checkout "$CURRENT_BRANCH"

echo "=========================================="
echo " SUCCESS: $CURRENT_BRANCH successfully merged into main and deployed/pushed!"
echo "=========================================="
