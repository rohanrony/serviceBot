# Audit and decisions

- `run_tests.sh --verify` already runs both roots separately and runs E2E after unit failure.
- E2E automatically marks tests using `page` as browser; browser is a subset, never a third suite.
- Both harnesses create owned loopback PostgreSQL databases; E2E saves failure artifacts.
- Existing push helper runs the default suite only for dirty work, before switching branches,
  stages all files by default, supports skip-tests and updates main (including on divergence).
- Existing generated template passes `assert True`.
- Live GitHub audit on 2026-10-19: main protection endpoint returned 404 Branch not protected;
  repository rulesets returned an empty list. Settings are proposed, not changed.
- Graph indexing and coverage are unavailable: server rejected this checkout's allowed root.
  Direct source reads were used; no graph completeness claim is made.
- GitHub docs confirm required checks can accept skipped/neutral conclusions, strict checks
  require an updated base, and merge queues need merge_group workflows. See docs/MERGE_READINESS.md.
- Use an isolated local clone rather than the dirty checkout or its Git worktree registry.
  The initial archive prototype failed simulation-runtime tests that require Git metadata.
  Keep the existing active Spec-Kit feature pointer intact; use scoped environment overrides.
- Full validation exposed model-download dependencies in legacy unit API tests. Stub only
  the model encoder, retaining actual FAQ/chunking and Chroma operations. Fixtures own TESTING
  flags; a global override hid the credential-error contract and was removed.
- Require UTF8 PostgreSQL. An initial disposable SQL_ASCII cluster caused emoji notification
  writes to fail; diagnostic rerun established the encoding cause and the UTF8 E2E rerun passed.
