# Data Model: Single-admin email and password authentication

## Admin account

One row represents the application administrator.

- `id`: singleton primary key constrained to the one permitted account.
- `email`: normalized login address with a unique constraint.
- `password_hash`: encoded Argon2id hash only.
- `created_at`, `updated_at`: UTC timestamps.

No plaintext or recoverable password is stored. The operator CLI creates the row once; the reset action updates only its hash and `updated_at`.

## Admin session

Each successful login creates one server-side session.

- `id`: primary key.
- `token_hash`: unique digest of the random opaque cookie token.
- `csrf_token_hash`: digest of the per-session CSRF token.
- `created_at`, `expires_at`: UTC timestamps; expiry is fixed at eight hours.
- `revoked_at`: nullable UTC timestamp.

A request is authorized only when the cookie digest matches a row whose expiry is in the future and which has not been revoked. Logout revokes that row. Password change and operator reset revoke every row.

## Failed login attempt

Store only the ASGI-resolved client IP address and timestamp needed for rate limiting; do not store submitted passwords or attempted email addresses. Keep attempts in a rolling 15-minute window, allow at most five failures per client IP in that window, and remove aged rows during authentication or an explicitly bounded cleanup. Use the address normalized by the trusted ASGI proxy configuration; never parse raw client-supplied forwarding headers in application code. Throttle before running Argon2 verification. The login response is generic whether the email is unknown, the password is wrong, or the IP is throttled.

## Database access

Add the objects using the next numbered migration and a paired `.down.sql` rollback plus `serviceBot/db/migration_verification/` query. Enable row-level security and revoke browser-facing/public roles consistently with existing sensitive-table migrations; application access remains through the server's PostgreSQL connection.
