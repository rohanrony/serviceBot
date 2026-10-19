---
name: git-push-merge
description: Publish an explicitly selected feature commit only after complete offline exact-candidate verification; merge through separately authorized PR review and CI.
---

# Verified feature publication

The compatibility script name remains `scripts/git_push_merge.sh`; it no longer merges main.
Use only with explicit user publication authorization. Inspect existing dirty/staged work,
select the intended branch and explicit file paths, then use:

```sh
./scripts/git_push_merge.sh --branch feature/name --message 'feat: description' --files path/to/change specs/feature/test-coverage.yaml tests/test_feature.py
# Already committed work (including a clean checkout) is still verified:
./scripts/git_push_merge.sh
```

The helper selects/commits first, fetches the target, runs
`./scripts/verify_change.sh --base <current-target-sha> --head <outgoing-sha>`, validates
current remote target evidence and pushes the pinned feature SHA. It preserves unrelated
staged paths. No skip-tests, implicit stage-all, direct main update or automatic merge.
Install the local supporting hook with `./scripts/install_git_hooks.sh`; preserve custom hooks.

Follow `docs/SPECKIT_WORKFLOW.md` and `docs/MERGE_READINESS.md`: require the coverage matrix,
meaningful tests, full tests/ and e2e/ execution including the browser subset, and exact
head/base evidence. Merge only with separate authorization, current aggregate CI, required
review and resolved findings. Remote rules require explicit approval to change.
Report local commit, pushed SHA, offline evidence, live requirements, merge and deployment
separately. Never run live simulations as part of publication without separate authorization.
