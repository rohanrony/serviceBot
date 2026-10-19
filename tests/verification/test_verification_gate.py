"""Exercise publication gates through real Git, shell and pytest boundaries."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def command(cwd, *args, env=None):
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)


def ok(cwd, *args):
    result = command(cwd, *args)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


@pytest.fixture
def sample(tmp_path):
    repo = tmp_path / "sample"
    repo.mkdir()
    ok(repo, "git", "init", "-b", "feature")
    ok(repo, "git", "config", "user.email", "offline@example.invalid")
    ok(repo, "git", "config", "user.name", "Offline test")
    for name in ("verify_change.sh", "verify_change.py", "verification_plugin.py",
                 "check_static.py", "check_ci_evidence.py", "git_push_merge.sh", "pre_push.py", "install_git_hooks.sh"):
        source = ROOT / "scripts" / name
        assert source.is_file(), f"Missing implementation: {source.name}"
        target = repo / "scripts" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(ROOT / "run_tests.sh", repo)
    shutil.copytree(ROOT / ".githooks", repo / ".githooks")
    (repo / ".venv").symlink_to(ROOT / ".venv", target_is_directory=True)
    (repo / ".gitignore").write_text(".venv\n.env\nscratch/\n__pycache__/\n")
    (repo / "pytest.ini").write_text("[pytest]\nmarkers =\n    browser: browser journey\n")
    (repo / "tests").mkdir()
    (repo / "e2e").mkdir()
    (repo / "e2e/conftest.py").write_text(
        "def pytest_addoption(parser):\n    parser.addoption('--e2e-artifacts')\n"
    )
    (repo / "tests/test_rule.py").write_text("def test_rule():\n    assert 2 + 2 == 4\n")
    (repo / "e2e/test_journey.py").write_text(
        "import pytest\n@pytest.mark.browser\ndef test_journey():\n    assert 'saved'.upper() == 'SAVED'\n"
    )
    (repo / "docs").mkdir()
    (repo / "docs/guide.md").write_text("Sample feature\n")
    ok(repo, "git", "add", ".")
    ok(repo, "git", "commit", "-qm", "sample baseline")
    base = ok(repo, "git", "rev-parse", "HEAD")
    ok(repo, "git", "branch", "main")
    (repo / "docs/guide.md").write_text("Sample feature with revised instructions\n")
    ok(repo, "git", "add", "docs/guide.md")
    ok(repo, "git", "commit", "-qm", "sample feature")
    return repo, base


def verify(repo, base, *extra, env=None):
    return command(repo, sys.executable, "scripts/verify_change.py", "--base", base,
                   "--head", "HEAD", *extra, env=env)


def receipt_for(repo, base):
    head = ok(repo, "git", "rev-parse", "HEAD")
    path = repo / "scratch/verification" / f"{head}-{base}" / "receipt.json"
    return path, json.loads(path.read_text())


def test_exact_commit_receipt_preserves_dirty_and_staged_work(sample):
    repo, base = sample
    (repo / "tests/test_rule.py").write_text("def test_rule():\n    assert False\n")
    (repo / "unrelated.txt").write_text("keep my staged work\n")
    ok(repo, "git", "add", "unrelated.txt")
    before = ok(repo, "git", "status", "--porcelain")
    result = verify(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr
    assert ok(repo, "git", "status", "--porcelain") == before
    _, receipt = receipt_for(repo, base)
    assert receipt["head_sha"] == ok(repo, "git", "rev-parse", "HEAD")
    assert receipt["base_sha"] == base
    assert receipt["status"] == "passed"
    assert receipt["suites"]["tests"]["counts"]["passed"] == 1
    assert receipt["suites"]["e2e"]["counts"]["passed"] == 1
    assert receipt["suites"]["e2e"]["browser"]["passed"] == 1
    assert receipt["fingerprints"]["test_manifest"]
    assert receipt["artifacts"] and receipt["commands"] and receipt["tools"]
    assert verify(repo, base, "--check").returncode == 0


@pytest.mark.parametrize("fault", ["failure", "setup_error", "teardown_error", "skip", "xfail",
                                        "xpass", "no_browser", "filter", "no_junit", "stale_junit", "no_execution", "static_failure"])
def test_incomplete_or_nonpassing_suites_cannot_issue_valid_evidence(sample, fault):
    repo, base = sample
    if fault in {"failure", "skip", "xfail", "xpass"}:
        decorator = {"failure": "", "skip": "@pytest.mark.skip(reason='required')\n",
                     "xfail": "@pytest.mark.xfail(reason='required')\n",
                     "xpass": "@pytest.mark.xfail(reason='required')\n"}[fault]
        assertion = "False" if fault in {"failure", "xfail"} else "True"
        (repo / "tests/test_rule.py").write_text(
            f"import pytest\n{decorator}def test_rule():\n    assert {assertion}\n")
    elif fault in {"setup_error", "teardown_error"}:
        body = "    yield\n    raise RuntimeError('teardown')\n" if fault == "teardown_error" else "    raise RuntimeError('setup')\n    yield\n"
        (repo / "tests/conftest.py").write_text("import pytest\n@pytest.fixture(autouse=True)\ndef broken():\n" + body)
    elif fault == "no_browser":
        (repo / "e2e/test_journey.py").write_text("def test_http_only():\n    assert True\n")
    elif fault == "filter":
        (repo / "pytest.ini").write_text("[pytest]\naddopts = -k nothing\nmarkers =\n    browser: journey\n")
    elif fault == "static_failure":
        (repo / "scripts/check_static.py").write_text("raise SystemExit('static check rejected candidate')\n")
    else:
        runner = repo / "run_tests.sh"
        value = runner.read_text()
        if fault in {"no_junit", "stale_junit"}:
            value = value.replace('--junitxml="$SCRATCH_DIR/unit-results.xml"', "")
            if fault == "stale_junit":
                (repo / "scratch").mkdir(exist_ok=True)
                (repo / "scratch/unit-results.xml").write_text('<testsuites><testsuite tests="1"><testcase name="test_rule"/></testsuite></testsuites>')
                ok(repo, "git", "add", "-f", "scratch/unit-results.xml")
        else:
            value = value.replace('"$WORKSPACE_DIR/run_tests.sh" --all', '"$WORKSPACE_DIR/run_tests.sh" --all --collect-only')
        runner.write_text(value)
    ok(repo, "git", "add", ".")
    ok(repo, "git", "commit", "-qm", "fault injection")
    result = verify(repo, base)
    assert result.returncode != 0, result.stdout
    assert verify(repo, base, "--check").returncode != 0


def test_both_suites_execute_when_unit_fails(sample):
    repo, base = sample
    (repo / "tests/test_rule.py").write_text("def test_rule():\n    assert False\n")
    ok(repo, "git", "add", ".")
    ok(repo, "git", "commit", "-qm", "unit failure")
    assert verify(repo, base).returncode != 0
    _, receipt = receipt_for(repo, base)
    assert receipt["suites"]["tests"]["counts"]["failed"] == 1
    assert receipt["suites"]["e2e"]["counts"]["passed"] == 1


def test_receipt_rejects_changed_head_base_and_tampered_artifact(sample):
    repo, base = sample
    assert verify(repo, base).returncode == 0
    path, receipt = receipt_for(repo, base)
    artifact = path.parent / next(iter(receipt["artifacts"]))
    original = artifact.read_bytes()
    artifact.write_bytes(original + b"tampered")
    assert verify(repo, base, "--check").returncode != 0
    artifact.write_bytes(original)
    assert verify(repo, base, "--check").returncode == 0
    receipt["head_sha"] = base
    path.write_text(json.dumps(receipt))
    assert verify(repo, base, "--check").returncode != 0
    assert verify(repo, base).returncode == 0
    assert verify(repo, "HEAD", "--check").returncode != 0
    (repo / "docs/guide.md").write_text("another revision\n")
    ok(repo, "git", "add", ".")
    ok(repo, "git", "commit", "-qm", "new candidate")
    assert verify(repo, base, "--check").returncode != 0


@pytest.mark.parametrize("key", ["PYTEST_ADDOPTS", "PYTEST_PLUGINS"])
def test_inherited_pytest_controls_are_rejected(sample, key):
    repo, base = sample
    env = {**os.environ, key: "-k nothing"}
    assert verify(repo, base, env=env).returncode != 0


def test_pre_push_blocks_missing_receipt_and_direct_main(sample, tmp_path):
    repo, base = sample
    remote = tmp_path / "remote.git"
    ok(repo, "git", "init", "--bare", str(remote))
    ok(repo, "git", "remote", "add", "origin", str(remote))
    ok(repo, "git", "push", "origin", "main")
    ok(repo, "bash", "scripts/install_git_hooks.sh")
    blocked = command(repo, "git", "push", "origin", "HEAD:refs/heads/unverified")
    assert blocked.returncode != 0
    assert not ok(repo, "git", "ls-remote", "origin", "refs/heads/unverified")
    assert verify(repo, base).returncode == 0
    ok(repo, "git", "push", "origin", "HEAD:refs/heads/verified")
    blocked = command(repo, "git", "push", "origin", "HEAD:refs/heads/main")
    assert blocked.returncode != 0
    assert ok(repo, "git", "ls-remote", "origin", "refs/heads/main").split()[0] == base


def test_helper_verifies_already_committed_work_and_preserves_main(sample, tmp_path):
    repo, base = sample
    remote = tmp_path / "remote.git"
    ok(repo, "git", "init", "--bare", str(remote))
    ok(repo, "git", "remote", "add", "origin", str(remote))
    ok(repo, "git", "push", "origin", "main")
    result = command(repo, "bash", "scripts/git_push_merge.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    _, receipt = receipt_for(repo, base)
    head = ok(repo, "git", "rev-parse", "HEAD")
    assert receipt["head_sha"] == head
    assert ok(repo, "git", "ls-remote", "origin", "refs/heads/feature").split()[0] == head
    assert ok(repo, "git", "ls-remote", "origin", "refs/heads/main").split()[0] == base


def test_helper_and_installed_hook_share_the_selected_target(sample, tmp_path):
    repo, _ = sample
    remote = tmp_path / "remote.git"
    ok(repo, "git", "init", "--bare", str(remote))
    ok(repo, "git", "remote", "add", "origin", str(remote))
    ok(repo, "git", "push", "origin", "main:refs/heads/develop")
    ok(repo, "bash", "scripts/install_git_hooks.sh")
    result = command(repo, "bash", "scripts/git_push_merge.sh", "--target", "develop")
    assert result.returncode == 0, result.stdout + result.stderr
    assert ok(repo, "git", "ls-remote", "origin", "refs/heads/feature")


def test_helper_commits_only_selected_files_after_branch_selection(sample, tmp_path):
    repo, base = sample
    remote = tmp_path / "remote.git"
    ok(repo, "git", "init", "--bare", str(remote))
    ok(repo, "git", "remote", "add", "origin", str(remote))
    ok(repo, "git", "push", "origin", "main")
    (repo / "docs/guide.md").write_text("selected change\n")
    (repo / "unrelated.txt").write_text("unrelated staged work\n")
    ok(repo, "git", "add", "unrelated.txt")
    result = command(repo, "bash", "scripts/git_push_merge.sh", "--branch", "selected",
                     "--message", "docs: selected", "--files", "docs/guide.md")
    assert result.returncode == 0, result.stdout + result.stderr
    assert ok(repo, "git", "branch", "--show-current") == "selected"
    assert ok(repo, "git", "diff", "--cached", "--name-only") == "unrelated.txt"
    assert ok(repo, "git", "show", "--format=", "--name-only", "HEAD") == "docs/guide.md"
    _, receipt = receipt_for(repo, base)
    assert receipt["head_sha"] == ok(repo, "git", "rev-parse", "HEAD")


def test_template_fails_until_real_assertions_are_written(sample):
    repo, _ = sample
    ok(repo, "bash", "run_tests.sh", "--create", "new_contract")
    result = command(repo, str(repo / ".venv/bin/python"), "-m", "pytest", "tests/test_new_contract.py", "-q")
    assert result.returncode == 1
    assert "Implement acceptance assertions" in result.stdout


def test_bypass_flags_and_implicit_commit_selection_are_rejected(sample):
    repo, _ = sample
    for args in (("--skip-tests",), ("--message", "feat: implicit")):
        result = command(repo, "bash", "scripts/git_push_merge.sh", *args)
        assert result.returncode != 0


def add_matrix(repo, **overrides):
    import yaml
    folder = repo / "specs/sample"
    folder.mkdir(parents=True, exist_ok=True)
    row = {"id": "AC1", "behavior": "A sample rule", "preconditions": ["isolated state"],
           "success": ["rule passes"], "failure": ["bad state rejected"], "invariants": ["no unrelated effects"],
           "tests": ["tests/test_rule.py::test_rule"], "layer": ["unit"],
           "live_acceptance": {"status": "not_required", "reason": "No provider behavior changed"}, **overrides}
    data = {"schema": 1, "acceptance": [row], "omitted_layers": {layer: "Sample has no such boundary"
            for layer in ("database", "http", "browser", "provider_contract", "composed", "migration", "targeted")}}
    (folder / "test-coverage.yaml").write_text(yaml.safe_dump(data))


@pytest.mark.parametrize("fault", ["missing_matrix", "missing_field", "uncollected_id", "omitted_layer", "valid"])
def test_behavior_changes_require_real_test_mapping(sample, fault):
    repo, base = sample
    (repo / "serviceBot").mkdir()
    (repo / "serviceBot/rule.py").write_text("VALUE = 4\n")
    (repo / "tests/test_rule.py").write_text("from serviceBot.rule import VALUE\ndef test_rule():\n    assert VALUE == 4\n")
    if fault != "missing_matrix":
        add_matrix(repo, **({"failure": []} if fault == "missing_field" else
                            {"tests": ["tests/test_rule.py::test_missing"]} if fault == "uncollected_id" else {}))
    if fault == "omitted_layer":
        import yaml
        path = repo / "specs/sample/test-coverage.yaml"
        data = yaml.safe_load(path.read_text())
        del data["omitted_layers"]["browser"]
        path.write_text(yaml.safe_dump(data))
    ok(repo, "git", "add", ".")
    ok(repo, "git", "commit", "-qm", "sample behavioral change")
    result = verify(repo, base)
    assert (result.returncode == 0) == (fault == "valid"), result.stdout + result.stderr


@pytest.mark.parametrize("job_result", ["skipped", "failure", "cancelled", "success"])
def test_ci_aggregate_requires_success_and_complete_exact_candidate_evidence(sample, job_result):
    repo, base = sample
    assert verify(repo, base).returncode == 0
    path, _ = receipt_for(repo, base)
    result = command(repo, sys.executable, "scripts/check_ci_evidence.py", "--offline-result", job_result,
                     "--base", base, "--head", "HEAD", "--output", str(path.parent))
    assert (result.returncode == 0) == (job_result == "success")
    path.unlink()
    result = command(repo, sys.executable, "scripts/check_ci_evidence.py", "--offline-result", "success",
                     "--base", base, "--head", "HEAD", "--output", str(path.parent))
    assert result.returncode != 0


def test_hook_rejects_changed_target_and_multiple_unverified_refs(sample, tmp_path):
    repo, base = sample
    remote = tmp_path / "remote.git"
    ok(repo, "git", "init", "--bare", str(remote))
    ok(repo, "git", "remote", "add", "origin", str(remote))
    ok(repo, "git", "push", "origin", "main")
    assert verify(repo, base).returncode == 0
    ok(repo, "bash", "scripts/install_git_hooks.sh")
    blocked = command(repo, "git", "push", "origin", "HEAD:refs/heads/verified", "main:refs/heads/unverified")
    assert blocked.returncode != 0
    assert not ok(repo, "git", "ls-remote", "origin", "refs/heads/verified")
    ok(repo, "git", "push", "origin", "HEAD:refs/heads/verified")
    # A remote target advance invalidates receipts even if the feature SHA is unchanged.
    head = ok(repo, "git", "rev-parse", "HEAD")
    ok(repo, "git", "--git-dir", str(remote), "update-ref", "refs/heads/main", head)
    blocked = command(repo, "git", "push", "origin", "HEAD:refs/heads/after-target-advance")
    assert blocked.returncode != 0
    blocked = command(repo, "git", "push", "origin", ":refs/heads/main")
    assert blocked.returncode != 0


def test_legacy_dotenv_readers_receive_only_synthetic_runtime_credentials(sample):
    repo, base = sample
    sentinel = "developer-sentinel-must-never-enter-candidate"
    (repo / ".env").write_text("ELEVENLABS_API_KEY=" + sentinel)
    (repo / "tests/test_rule.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "def test_rule():\n"
        "    assert os.environ['ELEVENLABS_API_KEY'] == 'synthetic-offline-key'\n"
        "    assert 'ELEVENLABS_API_KEY=synthetic-offline-key' in Path('.env').read_text()\n"
        f"    assert {sentinel!r} not in Path('.env').read_text()\n"
    )
    ok(repo, "git", "add", ".")
    ok(repo, "git", "commit", "-qm", "legacy credential boundary test")
    env = {**os.environ, "ELEVENLABS_API_KEY": sentinel}
    result = verify(repo, base, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert sentinel in (repo / ".env").read_text()


def test_external_dns_is_blocked_during_collection_before_application_fixtures(sample):
    repo, base = sample
    (repo / "tests/test_rule.py").write_text(
        "import socket\nimport pytest\n"
        "with pytest.raises(AssertionError, match='external DNS'):\n"
        "    socket.getaddrinfo('provider.invalid', 443)\n"
        "def test_rule():\n    assert socket.getaddrinfo('127.0.0.1', 5432)\n"
    )
    ok(repo, "git", "add", ".")
    ok(repo, "git", "commit", "-qm", "offline import network contract")
    result = verify(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr


def test_checkout_has_the_verified_git_revision_and_fixture_controls_test_mode(sample):
    repo, base = sample
    (repo / "tests/test_rule.py").write_text(
        "import os\nimport subprocess\n"
        "def test_rule():\n"
        "    assert subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip() == os.environ['VERIFY_HEAD_SHA']\n"
        "    assert 'TESTING' not in os.environ\n"
    )
    ok(repo, "git", "add", ".")
    ok(repo, "git", "commit", "-qm", "Git metadata and test mode boundary")
    result = verify(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["utf8", "ascii", "remote"])
def test_database_preflight_rejects_nonlocal_or_incompatible_servers(monkeypatch, mode):
    import psycopg2
    from scripts.verify_change import VerificationError, database_environment

    calls = []
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, statement): self.statement = statement
        def fetchone(self):
            return [{"SHOW server_version": "18", "SHOW server_encoding": "SQL_ASCII" if mode == "ascii" else "UTF8",
                     "SHOW TimeZone": "UTC"}[self.statement]]
    class Connection:
        def cursor(self): return Cursor()
        def close(self): calls.append("closed")
    def connect(dsn):
        calls.append(dsn)
        return Connection()
    monkeypatch.setattr(psycopg2, "connect", connect)
    url = "postgresql://" + ("provider.invalid" if mode == "remote" else "127.0.0.1") + "/voice_service_test"
    if mode == "utf8":
        assert database_environment({"TEST_DATABASE_URL": url})["server_encoding"] == "UTF8"
        assert calls[-1] == "closed"
    else:
        with pytest.raises(VerificationError):
            database_environment({"TEST_DATABASE_URL": url})
        assert (not calls) if mode == "remote" else calls[-1] == "closed"
