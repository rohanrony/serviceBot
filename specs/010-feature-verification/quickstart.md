# Local verification

Install application and `e2e/requirements.txt` dependencies into `.venv`, install Chromium,
and provide a disposable loopback PostgreSQL server with CREATEDB permission. Then:

```sh
./scripts/install_git_hooks.sh
./scripts/verify_change.sh --base origin/main --head HEAD
./scripts/git_push_merge.sh --branch feature-name --message 'feat: example' --files path/to/change
```

The helper commits only explicitly selected paths, verifies and pushes a pinned feature SHA.
It does not merge. Review and the proposed GitHub rules govern merging. See
`docs/MERGE_READINESS.md` for environment, evidence, CI and server configuration.
