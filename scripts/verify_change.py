"""Verify an immutable candidate and validate its complete offline evidence."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET


class VerificationError(Exception):
    """Evidence is absent, incomplete or belongs to another candidate."""


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True).encode()
    return hashlib.sha256(value).hexdigest()


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
    return result.stdout


def resolve(root, ref):
    require(not ref.startswith("-"), "Invalid revision")
    return git(root, "rev-parse", "--verify", ref + "^{commit}").decode().strip()


def identities(root, head, base):
    tree = git(root, "ls-tree", "-rz", head)
    files = git(root, "ls-tree", "-r", "--name-only", "-z", head).decode().split("\0")
    dependencies = {}
    for name in files:
        if name and ("requirements" in Path(name).name or Path(name).name in {
            "pyproject.toml", "uv.lock", "poetry.lock", "package-lock.json", "package.json"}):
            dependencies[name] = digest(git(root, "show", f"{head}:{name}"))
    changed = git(root, "diff", "--name-only", "-z", base, head).decode().split("\0")
    return {"source": digest(tree), "dependencies": digest(dependencies)}, dependencies, sorted(filter(None, changed))


def load_json(path):
    require(path.is_file(), f"Missing report: {path.name}")
    return json.loads(path.read_text())


def suite_result(output, run_dir, suite, run_id):
    collected = load_json(run_dir / f"{suite}-collection.json")
    executed = load_json(run_dir / f"{suite}-execution.json")
    for record, mode in ((collected, "collection"), (executed, "execution")):
        require(record.get("schema") == 1 and record.get("run_id") == run_id and
                record.get("suite") == suite and record.get("mode") == mode and
                record.get("complete") is True, f"Stale or incomplete {suite} {mode}")
        require(record.get("exit_code") == 0, f"{suite} {mode} did not succeed")
        require(not record.get("deselected") and not record.get("collection_errors"),
                f"{suite} was filtered or has collection errors")
    items = collected["items"]
    ids = [item["id"] for item in items]
    require(ids and len(set(ids)) == len(ids), f"{suite} has empty/duplicate collection")
    require(executed["items"] == items, f"{suite} execution differs from independent collection")
    reports = executed["reports"]
    require(set(reports) == set(ids), f"{suite} did not execute every collected test")
    counts = Counter()
    layers = {}
    browser = Counter()
    for item in items:
        phases = reports[item["id"]]
        require([phase["phase"] for phase in phases] == ["setup", "call", "teardown"],
                f"Incomplete test phases: {item['id']}")
        require(all(phase["outcome"] == "passed" and not phase["wasxfail"] for phase in phases),
                f"Non-passing, skipped or expected-failure test: {item['id']}")
        counts["passed"] += 1
        layers.setdefault(item["layer"], Counter())["passed"] += 1
        if item["browser"]:
            browser["passed"] += 1
    junit_path = run_dir / ("unit-results.xml" if suite == "tests" else "e2e-results.xml")
    require(junit_path.is_file(), f"Missing {suite} JUnit report")
    junit = ET.parse(junit_path).getroot()
    cases = junit.findall(".//testcase")
    require(len(cases) == len(ids), f"{suite} JUnit count differs from execution")
    junit_ids = []
    for case in cases:
        properties = {prop.get("name"): prop.get("value") for prop in case.findall("./properties/property")}
        require(properties.get("verification_run_id") == run_id, f"Stale {suite} JUnit report")
        junit_ids.append(properties.get("verification_node_id"))
    require(sorted(junit_ids) == sorted(ids), f"{suite} JUnit identities differ from execution")
    require(not any(case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped")),
            f"{suite} JUnit contains failures/errors/skips")
    if suite == "e2e":
        require(browser["passed"] > 0, "No browser tests executed within E2E")
    zeroes = {key: 0 for key in ("passed", "failed", "errors", "skipped", "xfail", "xpass")}
    return {"counts": {**zeroes, **counts},
            "layers": {name: {**zeroes, **values} for name, values in layers.items()},
            "browser": {**zeroes, **browser}, "collected_ids": ids,
            "executed_ids": ids, "browser_ids": [item["id"] for item in items if item["browser"]]}


def observed_result(run_dir, suite):
    """Retain failure outcomes too; invalid runs never become usable receipts."""
    path = run_dir / f"{suite}-execution.json"
    if not path.is_file():
        return {"counts": {}, "incomplete": True}
    record = load_json(path)
    counts = Counter()
    layers = {}
    browser = Counter()
    for item in record.get("items", []):
        phases = record.get("reports", {}).get(item["id"], [])
        if any(p["wasxfail"] for p in phases):
            state = "xfail" if any(p["outcome"] == "skipped" for p in phases) else "xpass"
        elif any(p["outcome"] == "failed" and p["phase"] != "call" for p in phases):
            state = "errors"
        elif any(p["outcome"] == "failed" for p in phases):
            state = "failed"
        elif any(p["outcome"] == "skipped" for p in phases):
            state = "skipped"
        elif len(phases) == 3:
            state = "passed"
        else:
            state = "not_executed"
        counts[state] += 1
        layers.setdefault(item["layer"], Counter())[state] += 1
        if item["browser"]:
            browser[state] += 1
    return {"counts": dict(counts), "layers": layers, "browser": dict(browser),
            "executed_ids": sorted(record.get("reports", {}))}


def validate_receipt(root, output, head, base):
    receipt = load_json(output / "receipt.json")
    require(receipt.get("schema") == 1 and receipt.get("status") == "passed", "No passing verification receipt")
    require(receipt.get("head_sha") == head and receipt.get("base_sha") == base, "Receipt head/base SHA mismatch")
    fingerprints, dependencies, changed = identities(root, head, base)
    require(all(receipt["fingerprints"].get(key) == value for key, value in fingerprints.items()),
            "Source or dependency fingerprint mismatch")
    require(receipt.get("dependency_files") == dependencies and receipt.get("changed_files") == changed,
            "Receipt input inventory mismatch")
    require(receipt.get("commands") and all(c["exit_code"] == 0 for c in receipt["commands"]),
            "Mandatory commands did not pass")
    required_commands = {"snapshot", "checkout", "static", "collect-tests", "collect-e2e", "verify", "dependencies"}
    require({c["name"] for c in receipt["commands"]} == required_commands, "Missing mandatory command evidence")
    for name, expected in receipt.get("artifacts", {}).items():
        artifact = (output / name).resolve()
        require(artifact.is_relative_to(output.resolve()) and artifact.is_file(), "Missing/unsafe artifact path")
        require(digest(artifact.read_bytes()) == expected, f"Changed artifact: {name}")
    run_dir = output / "runs" / receipt["run_id"]
    suites = {suite: suite_result(output, run_dir, suite, receipt["run_id"]) for suite in ("tests", "e2e")}
    require(receipt.get("suites") == suites, "Receipt summary differs from reports")
    require(receipt["fingerprints"].get("test_manifest") == digest({s: r["collected_ids"] for s, r in suites.items()}),
            "Test manifest fingerprint mismatch")
    required = [f"{s}-{m}.json" for s in ("tests", "e2e") for m in ("collection", "execution")]
    required += ["unit-results.xml", "e2e-results.xml", "snapshot.log", "checkout.log", "verify.log", "static.log", "dependencies.log", "collect-tests.log", "collect-e2e.log"]
    require(all(str((run_dir / name).relative_to(output)) in receipt["artifacts"] for name in required),
            "Missing mandatory artifact digest")
    return receipt


def sanitized_environment(root, checkout, run_dir):
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        require(not os.environ.get(key), f"Unset {key}: inherited test controls are forbidden")
    home = run_dir / "home"
    home.mkdir()
    browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(Path.home() / (
        "Library/Caches/ms-playwright" if sys.platform == "darwin" else ".cache/ms-playwright"))
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "LANG", "LC_ALL", "TMPDIR") if key in os.environ}
    env.update(HOME=str(home), TZ="UTC", PYTHONPATH=str(checkout), PYTHON_DOTENV_DISABLED="1",
               PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PLAYWRIGHT_BROWSERS_PATH=browser_path, LOG_FILE=str(run_dir / "application.log"),
               TEST_ARTIFACTS_DIR=str(run_dir / "runtime"), VERIFY_EVIDENCE_DIR=str(run_dir),
               VERIFY_RUN_ID=run_dir.name, TEST_DATABASE_URL=os.environ.get("TEST_DATABASE_URL", "postgresql://127.0.0.1/voice_service_test"))
    env.update(OPENAI_API_KEY="synthetic-offline-key", ELEVENLABS_API_KEY="synthetic-offline-key",
               ENCRYPTION_KEY="synthetic-offline-encryption-key", TWILIO_ACCOUNT_SID="AC" + "0" * 32,
               TWILIO_AUTH_TOKEN="synthetic-offline-token", CRON_SECRET="synthetic-offline-cron")
    return env


def database_environment(env):
    """Read only local server metadata; fixtures own database creation/deletion."""
    import psycopg2
    from psycopg2.extensions import make_dsn, parse_dsn

    params = parse_dsn(env["TEST_DATABASE_URL"])
    host = params.get("host", "localhost")
    require(host in {"127.0.0.1", "localhost", "::1"} and params.get("dbname", "").endswith("_test"),
            "Use a loopback TEST_DATABASE_URL with database name ending in _test")
    params.update(host=host, hostaddr="127.0.0.1" if host == "localhost" else host,
                  dbname="postgres", connect_timeout="3")
    params.pop("service", None)
    params.pop("options", None)
    try:
        connection = psycopg2.connect(make_dsn(**params))
    except psycopg2.Error as error:
        raise VerificationError("Local PostgreSQL is unavailable; configure disposable UTF8 PostgreSQL with CREATEDB") from error
    try:
        with connection.cursor() as cursor:
            values = {}
            for key in ("server_version", "server_encoding", "TimeZone"):
                cursor.execute("SHOW " + key)
                values[key] = cursor.fetchone()[0]
        require(values["server_encoding"] == "UTF8", "Offline PostgreSQL must use UTF8 encoding")
        return values
    finally:
        connection.close()


def coverage_requirements(checkout, changed):
    """Validate changed matrices; human review judges sufficiency of assertions."""
    matrices = [name for name in changed if name.startswith("specs/") and name.endswith("/test-coverage.yaml")]
    behavioral = any(name.startswith(("serviceBot/", "live_simulations/")) for name in changed)
    require(not behavioral or matrices, "Application/provider changes require an updated feature test-coverage.yaml")
    require(not behavioral or any(name.startswith(("tests/", "e2e/")) and name.endswith(".py") for name in changed),
            "Behavioral changes require updated tests")
    live = []
    layers = {"unit", "database", "http", "browser", "provider_contract", "composed", "migration", "targeted"}
    if matrices:
        import yaml
        for name in matrices:
            data = yaml.safe_load((checkout / name).read_text())
            require(isinstance(data, dict) and data.get("schema") == 1 and data.get("acceptance"), f"Empty/invalid acceptance matrix: {name}")
            used = set()
            for row in data["acceptance"]:
                for field in ("id", "behavior", "preconditions", "success", "failure", "invariants", "tests", "layer", "live_acceptance"):
                    require(field in row and row[field] not in (None, "", []), f"Missing {field} in {name}")
                require(isinstance(row["tests"], list) and all(isinstance(test, str) and "::" in test for test in row["tests"]),
                        f"Use real pytest node identifiers in {name}")
                require(isinstance(row["layer"], list) and set(row["layer"]) <= layers, f"Unknown test layer in {name}")
                used.update(row["layer"])
                requirement = row["live_acceptance"]
                require(isinstance(requirement, dict) and requirement.get("status") in {"pending", "verified", "not_required"}
                        and requirement.get("reason"), f"Record explicit live status/reason in {name}")
                live.append({"acceptance": row["id"], "requirement": row["live_acceptance"]})
            omitted = data.get("omitted_layers", {})
            require(isinstance(omitted, dict) and layers - used <= set(omitted)
                    and all(isinstance(reason, str) and reason.strip() for reason in omitted.values()),
                    f"Document every omitted layer and reason in {name}")
    return live


def validate_coverage_ids(checkout, changed, suites):
    matrices = [name for name in changed if name.startswith("specs/") and name.endswith("/test-coverage.yaml")]
    if not matrices:
        return
    import yaml
    ids = {node for result in suites.values() for node in result["collected_ids"]}
    for name in matrices:
        for row in yaml.safe_load((checkout / name).read_text())["acceptance"]:
            for test in row["tests"]:
                require(test in ids or any(node.startswith(test + "[") for node in ids),
                        f"Coverage test was not collected: {test}")


def run_verification(root, output, head, base):
    output.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    run_dir = output / "runs" / run_id
    run_dir.mkdir(parents=True)
    fingerprints, dependencies, changed = identities(root, head, base)
    receipt = {"schema": 1, "status": "failed", "run_id": run_id, "head_sha": head,
               "base_sha": base, "started_at": utcnow(), "fingerprints": fingerprints,
               "dependency_files": dependencies, "changed_files": changed, "commands": [],
               "tools": {"python": sys.version, "platform": platform.platform()}, "suites": {},
               "live_acceptance": [], "artifacts": {}}
    receipt_path = output / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")

    def run(name, args, cwd, env):
        log = run_dir / f"{name}.log"
        started = utcnow()
        with log.open("w") as stream:
            result = subprocess.run(args, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
        receipt["commands"].append({"name": name, "argv": [str(a) for a in args],
                                    "started_at": started, "finished_at": utcnow(), "exit_code": result.returncode})
        print(f"{name}: exit {result.returncode}; {log}", flush=True)
        return result.returncode

    try:
        subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", base, head], check=True)
        with tempfile.TemporaryDirectory(prefix="voice-verify-") as temporary:
            checkout = Path(temporary) / "checkout"
            env = sanitized_environment(root, checkout, run_dir)
            receipt["tools"]["runtime_timezone"] = env["TZ"]
            env["VERIFY_HEAD_SHA"] = head
            git_env = {**env, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
            require(run("snapshot", ["git", "-c", "core.hooksPath=/dev/null", "clone", "--shared", "--no-checkout", "--quiet",
                                     str(root), str(checkout)], root, git_env) == 0, "Isolated clone failed")
            require(run("checkout", ["git", "-C", str(checkout), "-c", "core.hooksPath=/dev/null", "-c", "core.autocrlf=false",
                                     "checkout", "--quiet", "--detach", head], root, git_env) == 0, "Exact-candidate checkout failed")
            require(not (checkout / ".env").exists(), "Candidate must not contain a tracked .env")
            venv = root / ".venv"
            require((venv / "bin/python").exists() and (venv / "bin/pytest").exists(), "Install .venv dependencies before verification")
            require(not (checkout / ".venv").exists(), "Candidate must not contain a tracked virtualenv")
            (checkout / ".venv").symlink_to(venv.resolve(), target_is_directory=True)
            # Legacy imports parse .env directly; never copy the workspace file.
            (checkout / ".env").write_text("ELEVENLABS_API_KEY=synthetic-offline-key\nOPENAI_API_KEY=synthetic-offline-key\n")
            if (checkout / "serviceBot/db/connection.py").is_file():
                receipt["tools"]["postgresql"] = database_environment(env)
            receipt["live_acceptance"] = coverage_requirements(checkout, changed)
            receipt["tools"]["git"] = git(root, "--version").decode().strip()
            for tool, args in (("node", ["node", "--version"]), ("pytest", [str(venv / "bin/python"), "-m", "pytest", "--version"]),
                               ("playwright", [str(venv / "bin/python"), "-m", "playwright", "--version"])):
                version = subprocess.run(args, env=env, capture_output=True, text=True)
                receipt["tools"][tool] = version.stdout.strip() if version.returncode == 0 else "unavailable"
            run("dependencies", [str(venv / "bin/python"), "-m", "pip", "freeze", "--all"], checkout, env)
            receipt["fingerprints"]["installed_dependencies"] = digest((run_dir / "dependencies.log").read_bytes())
            run("static", [str(venv / "bin/python"), "scripts/check_static.py"], checkout, env)
            for suite in ("tests", "e2e"):
                run(f"collect-{suite}", [str(venv / "bin/python"), "-m", "pytest", "-p", "anyio.pytest_plugin", "-p", "scripts.verification_plugin",
                    suite + "/", "--collect-only", "-q"], checkout, {**env, "VERIFY_SUITE": suite})
            # The canonical runner still executes both suites even if the first fails.
            run("verify", ["./run_tests.sh", "--verify"], checkout, env)
            for suite, filename in (("tests", "unit-results.xml"), ("e2e", "e2e-results.xml")):
                report = checkout / "scratch" / filename
                if report.exists():
                    (run_dir / filename).write_bytes(report.read_bytes())
            receipt["suites"] = {suite: observed_result(run_dir, suite) for suite in ("tests", "e2e")}
            suites = {suite: suite_result(output, run_dir, suite, run_id) for suite in ("tests", "e2e")}
            receipt["suites"] = suites
            validate_coverage_ids(checkout, changed, suites)
            receipt["fingerprints"]["test_manifest"] = digest({s: r["collected_ids"] for s, r in suites.items()})
            require(all(c["exit_code"] == 0 for c in receipt["commands"]), "A required command failed; inspect logs")
            receipt["status"] = "passed"
    except (VerificationError, subprocess.SubprocessError, OSError, ValueError, ET.ParseError, KeyError, ImportError) as error:
        receipt["error"] = str(error)
        print(f"Verification failed: {error}", file=sys.stderr)
    finally:
        receipt["finished_at"] = utcnow()
        receipt["artifacts"] = {str(p.relative_to(output)): digest(p.read_bytes()) for p in sorted(run_dir.rglob("*")) if p.is_file()}
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"Receipt ({receipt['status']}): {receipt_path}", flush=True)
    if receipt["status"] == "passed":
        validate_receipt(root, output, head, base)
        return 0
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true", help="Validate existing exact-candidate evidence without running tests")
    args = parser.parse_args()
    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
    head, base = resolve(root, args.head), resolve(root, args.base)
    output = (args.output or root / "scratch/verification" / f"{head}-{base}").resolve()
    if args.check:
        validate_receipt(root, output, head, base)
        print(f"Valid offline evidence: {head} against {base}")
        return 0
    return run_verification(root, output, head, base)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (VerificationError, subprocess.SubprocessError, OSError, ValueError, KeyError) as error:
        print(f"Verification rejected: {error}", file=sys.stderr)
        sys.exit(1)
