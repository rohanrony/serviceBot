# Verification, publication and merge readiness

Run `./scripts/verify_change.sh --base <target-ref> --head <commit-sha>` before publishing.
Fetch the target first and integrate its latest commit into the candidate. A changed head
or target needs new evidence. The command exports the exact committed tree to a disposable
Git checkout and preserves local staged/unstaged/untracked work. Install application requirements
and `e2e/requirements.txt` into `.venv`, install Chromium with
`.venv/bin/python -m playwright install chromium`, and provide a loopback PostgreSQL server
whose user can create databases. PostgreSQL must use UTF8 encoding; server version, encoding
and timezone are recorded in the receipt. `TEST_DATABASE_URL` must name a database ending in `_test`;
fixtures create/drop only their own random databases. The URL is connection configuration,
not a database to reset. The isolated application/browser runtime uses UTC across hosts and records that setting;
business-clock tests provide explicit deterministic clocks. The developer `.env` and production credentials are never copied.
Legacy imports that parse `.env` directly receive a generated file containing synthetic keys
inside the disposable checkout. No paid provider calls are used.

## Evidence contract

The gate runs configured static checks in `scripts/check_static.py`, independently collects
`tests/` and `e2e/`, and runs the canonical `./run_tests.sh --verify`. Browser journeys are
reported **within E2E**, never added to totals again. Syntax checks cover Python, shell and
application JavaScript. AnyIO is loaded explicitly; unrelated installed pytest plugins are
disabled. Configured pytest addopts/filtering and inherited pytest controls are rejected.
Skipped, xfailed and xpassed required tests block the gate, as do setup/teardown errors,
missing manifests/JUnit, collection errors, incomplete phases, or mismatched test identities.

The receipt is at `scratch/verification/<head>-<base>/receipt.json`; unique run directories
retain command logs, JUnit, collection/execution node IDs, per-layer results, installed
dependency inventory, browser traces/screenshots and isolated runtime files. Receipts include
head/base, Git source tree, dependency-file and test-manifest fingerprints, command exit codes,
tool versions and timestamps. `--check` revalidates exact source identity and artifact bytes.
A failed/interrupted run leaves a failed receipt; it cannot reuse old passing reports.
Installed dependency versions are recorded, since existing dependency declarations are not
locked. An isolated local clone retains exact Git revision metadata for runtime tests. Its
checkout disables global Git configuration and hooks. Test fixtures own test-mode flags;
the gate does not force application mock branches. Unit tests replace the downloadable
embedding encoder with deterministic vectors while retaining real FAQ/Chroma storage behavior.

Legacy tests without explicit `@pytest.mark.test_layer(...)` retain honest combined
`unit_integration` or `http_workflow` labels; new tests should identify their appropriate layer.
Human review must judge assertion quality, fixture realism, omitted layers, test removals and
weakened assertions. Receipts and counts cannot establish behavioral sufficiency by themselves.
Local receipts are editable developer artifacts, not signed attestations; hooks support
the workflow while protected GitHub checks and review enforce merging.

## Publication

Install the local gate once with `./scripts/install_git_hooks.sh`. It refuses to replace
an existing custom hook configuration. The hook validates each outgoing branch SHA against
the live remote main SHA; fetch and reverify if the target changed. Branch deletions need no
test evidence. Direct main/master updates and tag publication are outside this helper.
The helper passes `--target <branch>` to its installed hook for the same push. For direct
Git pushes to another integration branch, configure `git config verification.targetBranch <branch>`;
main is the default.

The compatibility script `scripts/git_push_merge.sh` now publishes a verified feature branch:

```sh
# Already committed work, including a clean workspace:
./scripts/git_push_merge.sh
# Select a branch and commit only named paths, preserving unrelated staged files:
./scripts/git_push_merge.sh --branch feature/example --message 'feat: example' --files tests/test_example.py serviceBot/example.py specs/feature/test-coverage.yaml
```

It chooses the branch and commit first, fetches the target, verifies that exact SHA, checks
the current remote target again, then pushes a pinned SHA refspec. There is no skip-tests
flag, implicit stage-all, ref rewrite of main, or automatic merge. Other Git clients can
bypass a local hook, so server rules are required. Pure documentation changes may receive a
reviewed exemption under maintainer policy; this implementation always runs the full gate
and provides no automatic documentation bypass. Configuration, prompts, migrations,
workflows and test infrastructure receive full verification and appropriate targeted tests.

## CI and proposed remote rules

`.github/workflows/verify-change.yml` handles pull requests and merge groups. It verifies the
GitHub integration candidate with disposable PostgreSQL, installed Chromium, isolated files
and synthetic credentials. It references no production secrets. The `Merge readiness`
aggregate runs after the mandatory offline job, requires its result to be exactly `success`,
downloads the evidence and validates the same head/base, reports and digests. Missing
artifacts, skipped/failed/canceled jobs or incomplete reports cannot produce a passing aggregate.
If another mandatory job is added, add it to `needs` and explicitly evaluate its result too.

Live audit on 2026-10-19: GitHub returned `Branch not protected` for main and `[]` for
repository rulesets. No remote setting was changed. Propose the following for main:

- Require PRs, one approving review, stale-approval dismissal, approval of the latest push
  by someone other than its author, and resolved review conversations.
- Require the unique **Merge readiness** check from GitHub Actions, with strict up-to-date
  branches (or merge queue); prevent direct pushes, force pushes, deletion and admin bypass.
- Enable the merge queue only with the existing `merge_group` trigger active.

GitHub allows successful, skipped or neutral required checks, which is why the aggregate
must explicitly evaluate mandatory execution and reports. See
[protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
and [required status-check troubleshooting](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks).
Settings require maintainer approval and a published check before selecting its exact context.

## Live acceptance and reporting

Every route must update or add a feature-local `test-coverage.yaml` row for each changed
acceptance contract, naming real collected automated test IDs and relevant live scenario IDs
with definition paths (or empty scenarios and a concrete `not_required` reason). When provider
behavior changes, update the actual scenario definition, recipients/calendars/permissions,
expected external and prohibited effects, independent read-back, prerequisites, cleanup/recovery,
credit/cost estimates with units/basis, spending ceiling and unknown-charge handling in the matrix
and live brief. Reuse only applicable retained evidence; changed assertions invalidate affected
evidence. Coverage maintenance is required offline work. Live execution requires separate
authorization and never runs from this gate, pre-push or PR verification. Offline/mock passes
cannot prove provider delivery.

Report **Offline** and **Live** independently as `verified`, `pending` or `not_required`, with
reasons and evidence, then report Merged and Deployed separately. Follow the
[workflow status definitions](SPECKIT_WORKFLOW.md#handoff-record); missing authorization or
prerequisites means Live pending, not not_required. Missing/stale coverage definitions remain
development gaps even when live execution is pending.
A feature is merge-ready only when acceptance tests are meaningful, current-candidate full
suites and CI pass, review findings are resolved and live obligations are explicit.
