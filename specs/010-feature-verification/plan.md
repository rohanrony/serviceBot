# Implementation Plan: Feature verification

**Date**: 2026-10-19 | **Spec**: [spec.md](spec.md)

## Summary

Use one Python orchestrator behind `scripts/verify_change.sh`. Clone and check out the exact
Git revision in a temporary directory, reuse the installed venv for dependencies, sanitize
the child environment, collect each suite separately, then run `./run_tests.sh --verify`.
A pytest plugin records node IDs, markers, deselection and setup/call/teardown outcomes.
Require complete matching manifests, fresh JUnit and zero non-passing outcomes. Hash all
retained artifacts and bind the receipt to head/base/tree/dependencies/manifests.

## Technical Context

Python 3.13, pytest, PostgreSQL, Chromium/Playwright, Bash, Node syntax checks, PyYAML.
JSON receipts on local disk; no new service or state database. `tests/verification/`
exercises disposable Git repos and actual pytest processes without application fixtures.
The standard suite also discovers these tests. Existing browser fixtures remain authoritative.

## Constitution Check

One verification owner; external boundary blocking and synthetic secrets; no production
state, provider calls or paid runs; TDD for the gate; no application schema changes.
No changed application browser journey, so no new product browser journey is needed;
the gate must still prove the complete existing browser subset executed.

## Project Structure

`scripts/{verify_change.sh,verify_change.py,verification_plugin.py,check_static.py}`;
`scripts/{git_push_merge.sh,install_git_hooks.sh,pre_push.py}`; `.githooks/pre-push`;
`.github/workflows/verify-change.yml`; coverage template; workflow docs/skills;
`tests/verification/test_verification_gate.py` and this feature's artifacts.

Preserve Git metadata for offline simulation runtime tests. Let fixtures control TESTING
flags, and replace only the unit suite's downloadable embedding encoder. The pre-existing
date-stability edit in `tests/test_staff_calendars.py` is reused as a validation prerequisite
without editing or claiming ownership of it.

## Failure analysis and gates

An untested commit was published because clean work skipped tests: always select SHA first.
A filtered/aborted run looked green: compare independent collection with every test phase
and JUnit, reject skips/xfail, check all mandatory artifacts. Old artifacts were reused:
unique run nonce, fresh directories, artifact digests, exact head/base and source identities.
Unrelated edits were committed: require explicit paths and use path-limited commits.
CI skipped a mandatory job: always-running aggregate checks explicit results and receipt.
Owners: verifier for evidence, helper/hook for publication, GitHub rules for merge enforcement.
