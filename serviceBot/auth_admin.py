"""Operator-only provisioning and reset commands for the single admin account."""

import argparse
import getpass
import sys
import warnings

from serviceBot.services.admin_auth import create_admin, reset_admin_password


def _read_password() -> str:
    # getpass falls back to visible stdin when there is no controlling TTY or
    # echo control. Treat that warning as an error so secrets are never typed
    # into an echoed prompt or captured input stream.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Password confirmation does not match")
    return password


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m serviceBot.auth_admin")
    parser.add_argument("command", choices=("create-admin", "reset-password"))
    args = parser.parse_args(argv)
    try:
        if args.command == "create-admin":
            email = input("Admin email: ")
            create_admin(email, _read_password())
            print("Admin account created.")
        else:
            reset_admin_password(_read_password())
            print("Admin password reset; existing sessions revoked.")
        return 0
    except Exception as exc:
        # DB errors may contain SQL parameters. Never print exception text here.
        print("Admin credential operation failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
