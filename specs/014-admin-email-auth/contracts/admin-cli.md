# Operator CLI Contract: Admin account provisioning

Use `python -m serviceBot.auth_admin create-admin` to create the single account and `python -m serviceBot.auth_admin reset-password` for operator recovery.

- Read email and password through interactive prompts; password input is hidden and confirmed without echo.
- Enforce email validation/normalization and the 12-character minimum password policy.
- Hash passwords with Argon2id before database writes.
- `create-admin` succeeds only when no admin exists; it must not overwrite an existing account or sessions.
- `reset-password` updates the existing hash and revokes all sessions in one transaction.
- Print only a redacted success/failure result. Never include credentials in logs, command arguments, SQL diagnostics, or output.
- Use the configured application PostgreSQL connection and apply the migration prerequisites before provisioning.
