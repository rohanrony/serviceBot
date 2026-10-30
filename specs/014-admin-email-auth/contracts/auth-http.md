# HTTP Contract: Admin authentication

All JSON endpoints are same-origin under `/api/v1/auth`. Request and response bodies contain no password hash, raw session token, or database identifiers. Auth responses use `Cache-Control: no-store`.

## `POST /api/v1/auth/login`

Request: `{ "email": string, "password": string }`.

Success: `200`, set the HttpOnly session cookie, return the normalized email and per-session CSRF token. Failure: generic `401`; throttling uses the same body and does not reveal account existence. Require an `Origin` header matching the request's trusted public origin. Reject after five failures from the ASGI-resolved client IP in the rolling 15-minute window, before Argon2 verification. The cookie expires server-side after eight hours.

## `GET /api/v1/auth/session`

Requires a valid session cookie. Return `{ "authenticated": true, "email": string, "csrf_token": string }`. Without a valid session return `401` and clear an expired/revoked cookie.

## `POST /api/v1/auth/logout`

Requires a valid session and CSRF header. Revoke that session, clear the cookie, and return `204`.

## `POST /api/v1/auth/password`

Requires a valid session and CSRF header. Request: `{ "current_password": string, "new_password": string, "new_password_confirmation": string }`. Require current-password verification, a 12-character minimum, and matching confirmation. On success store a new Argon2id hash, revoke every session, clear the cookie, and return `204`; the admin signs in again.

## Protected surface and exclusions

- `/portal/`, `/portal/index.html`, and every non-authenticated admin route under `/api/v1/portal/*` require the session dependency. Admin API failures are `401` JSON; unauthenticated dashboard HTML requests redirect to `/`. Authenticated HTML and API responses use `Cache-Control: no-store`.
- `/api/v1/portal/gmail/oauth/callback` remains public and is authorized by its existing OAuth `state` validation.
- `/api/v1/portal/internal/*` retains the existing route-specific bearer-token checks and does not accept a browser session as a substitute.
- Telephony, voice tools, cron, health, and Render log ingestion retain their current route contracts.
- Unsafe cookie-authenticated requests, including logout and password change, require an `Origin` header matching the request's trusted public origin and `X-CSRF-Token` equal to the authenticated session's synchronizer token.
