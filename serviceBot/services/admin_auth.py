"""Database-backed, single-admin authentication primitives."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import threading
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from serviceBot.db.connection import get_db_connection

PASSWORD_MIN_LENGTH = 12
SESSION_TTL = timedelta(hours=8)
LOGIN_WINDOW = timedelta(minutes=15)
MAX_FAILED_LOGINS = 5
# Argon2's default memory cost is 64 MiB per operation. Two concurrent
# operations bound this process to roughly 128 MiB for password work.
MAX_PASSWORD_WORKERS = 2
_HASH_WORK = threading.BoundedSemaphore(MAX_PASSWORD_WORKERS)
_HASHER = PasswordHasher()
_DUMMY_HASH = _HASHER.hash("dummy-auth-value-never-used-for-login")


def normalize_email(email: str) -> str:
    if not isinstance(email, str):
        raise ValueError("Invalid email")
    normalized = email.strip().casefold()
    if len(normalized) > 320 or normalized.count("@") != 1:
        raise ValueError("Invalid email")
    local, domain = normalized.split("@", 1)
    if not local or not domain or "." not in domain or any(ch.isspace() for ch in normalized):
        raise ValueError("Invalid email")
    return normalized


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError("Password must contain at least 12 characters")
    with _HASH_WORK:
        return _HASHER.hash(password)


def verify_password(encoded_hash: str, password: str) -> bool:
    try:
        with _HASH_WORK:
            valid = _HASHER.verify(encoded_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError, ValueError):
        return False
    return bool(valid)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _csrf_for_token(token: str) -> str:
    return hmac.new(token.encode("utf-8"), b"admin-session-csrf-v1", hashlib.sha256).hexdigest()


def create_admin(email: str, password: str) -> None:
    normalized = normalize_email(email)
    encoded = hash_password(password)
    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO public.admin_accounts (id, email, password_hash) VALUES (1, %s, %s)",
            (normalized, encoded),
        )


def reset_admin_password(password: str) -> None:
    encoded = hash_password(password)
    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE public.admin_accounts SET password_hash=%s, updated_at=CURRENT_TIMESTAMP WHERE id=1",
            (encoded,),
        )
        if cursor.rowcount != 1:
            raise LookupError("Admin account does not exist")
        cursor.execute("UPDATE public.admin_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE revoked_at IS NULL")


def _get_admin(email: str):
    from serviceBot.db.connection import dict_cursor

    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute("SELECT email, password_hash FROM public.admin_accounts WHERE id=1 AND email=%s", (email,))
        return cursor.fetchone()


def authenticate(email: str, password: str, client_ip: str):
    """Return (email, token, csrf) on success, or None for a generic denial."""
    try:
        normalized = normalize_email(email)
        normalized_ip = str(ipaddress.ip_address(client_ip))
    except (ValueError, TypeError):
        return None

    from serviceBot.db.connection import dict_cursor

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Serialize decisions for this client so concurrent requests cannot
            # pass the threshold check together after the fifth recorded failure.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (normalized_ip,))
            cursor.execute("DELETE FROM public.admin_login_attempts WHERE attempted_at < CURRENT_TIMESTAMP - INTERVAL '15 minutes'")
            cursor.execute(
                "SELECT COUNT(*) AS failed FROM public.admin_login_attempts WHERE client_ip=%s AND attempted_at >= CURRENT_TIMESTAMP - INTERVAL '15 minutes'",
                (normalized_ip,),
            )
            if cursor.fetchone()["failed"] >= MAX_FAILED_LOGINS:
                return None
            cursor.execute("SELECT email, password_hash FROM public.admin_accounts WHERE id=1 AND email=%s", (normalized,))
            account = cursor.fetchone()
            candidate_hash = account["password_hash"] if account else _DUMMY_HASH
            valid = verify_password(candidate_hash, password if isinstance(password, str) else "")
            if not account or not valid:
                cursor.execute("INSERT INTO public.admin_login_attempts (client_ip) VALUES (%s)", (normalized_ip,))
                return None
            # Lock and recheck after the expensive hash verification. Password
            # changes/resets update this row and revoke sessions in one
            # transaction, so a stale verification cannot insert afterward.
            cursor.execute("SELECT email, password_hash FROM public.admin_accounts WHERE id=1 FOR UPDATE")
            current_account = cursor.fetchone()
            if not current_account or current_account["email"] != normalized or current_account["password_hash"] != candidate_hash:
                cursor.execute("INSERT INTO public.admin_login_attempts (client_ip) VALUES (%s)", (normalized_ip,))
                return None
            account = current_account
            if _HASHER.check_needs_rehash(candidate_hash):
                cursor.execute(
                    "UPDATE public.admin_accounts SET password_hash=%s, updated_at=CURRENT_TIMESTAMP WHERE id=1",
                    (hash_password(password),),
                )
            token = secrets.token_urlsafe(32)
            csrf = _csrf_for_token(token)
            cursor.execute(
                "INSERT INTO public.admin_sessions (token_hash, csrf_token_hash, expires_at) VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL '8 hours')",
                (_digest(token), _digest(csrf)),
            )
            return account["email"], token, csrf


def get_session(token: str):
    if not token or len(token) > 512:
        return None
    from serviceBot.db.connection import dict_cursor

    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute(
            """SELECT a.email, s.csrf_token_hash
               FROM public.admin_sessions s CROSS JOIN public.admin_accounts a
               WHERE s.token_hash=%s AND s.revoked_at IS NULL
                 AND s.expires_at > CURRENT_TIMESTAMP AND a.id=1""",
            (_digest(token),),
        )
        row = cursor.fetchone()
    if not row:
        return None
    csrf = _csrf_for_token(token)
    if not hmac.compare_digest(row["csrf_token_hash"], _digest(csrf)):
        return None
    return {"email": row["email"], "csrf_token": csrf}


def revoke_session(token: str) -> None:
    if not token:
        return
    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute("UPDATE public.admin_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE token_hash=%s AND revoked_at IS NULL", (_digest(token),))


def csrf_is_valid(token: str, csrf: str) -> bool:
    if not token or not csrf:
        return False
    session = get_session(token)
    return bool(session and hmac.compare_digest(session["csrf_token"], csrf))


def change_password(current_password: str, new_password: str) -> bool:
    try:
        encoded = hash_password(new_password)
    except ValueError:
        return False
    with get_db_connection() as conn:
        from serviceBot.db.connection import dict_cursor

        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT password_hash FROM public.admin_accounts WHERE id=1 FOR UPDATE")
            row = cursor.fetchone()
            if not row or not verify_password(row["password_hash"], current_password):
                return False
            cursor.execute("UPDATE public.admin_accounts SET password_hash=%s, updated_at=CURRENT_TIMESTAMP WHERE id=1", (encoded,))
            cursor.execute("UPDATE public.admin_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE revoked_at IS NULL")
    return True
