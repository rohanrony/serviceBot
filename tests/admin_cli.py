"""Invoke the real operator CLI entry point with controlled prompt responses."""

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch


def run_admin_cli(command, responses, env=None, timeout=20):
    """Run ``main`` in-process so it uses pytest's disposable database pool.

    Prompt values are delivered through the same input/getpass functions used
    by the CLI. They are never placed in process arguments or printed output.
    """
    del timeout  # Retained for compatibility with callers of the old helper.
    import serviceBot.auth_admin as auth_admin

    answers = iter(responses)
    stdout = io.StringIO()
    stderr = io.StringIO()
    environ = dict(env or {})
    with (
        patch.dict(os.environ, environ),
        patch("builtins.input", side_effect=lambda _prompt="": next(answers)),
        patch.object(auth_admin.getpass, "getpass", side_effect=lambda _prompt="": next(answers)),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        returncode = auth_admin.main([command])
    return SimpleNamespace(returncode=returncode, stdout=stdout.getvalue(), stderr=stderr.getvalue())
