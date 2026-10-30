# Security Requirements Quality Checklist: Single-admin email and password authentication

**Purpose**: Confirm the security requirements are complete and specific enough to guide implementation and offline validation.
**Created**: 2026-10-29
**Feature**: [spec.md](../spec.md)
**Review Ownership**: Root reviewer; checked markers mean requirements quality was reviewed, not that code is complete.

## Account lifecycle and credentials

- [x] CHK001 Does the spec say who creates the first admin account and where credentials are shared?
- [x] CHK002 Does it define the one-account limit, prohibit public signup/recovery, and define operator reset behavior?
- [x] CHK003 Does it specify hash type, minimum password length, first-login behavior, and self-service change requirements?
- [x] CHK004 Does it prevent password material from appearing in CLI arguments/output/logs or plaintext database fields?

## Sessions and request boundaries

- [x] CHK005 Does it define opaque database-backed sessions, fixed expiry, revocation, cookie attributes, CSRF, and same-origin checks?
- [x] CHK006 Does it identify trusted proxy metadata for public scheme/client IP and prohibit raw client-supplied forwarding headers as identity?
- [x] CHK007 Does it specify generic login failures, throttling before hash work, bounded hash concurrency, and fail-closed storage errors?
- [x] CHK008 Does it distinguish protected admin routes from OAuth state callbacks, bearer-token routes, and existing service ingress?
- [x] CHK009 Does it require safe config serialization, no-store for authenticated content, and no credential disclosure?

## Verification and operations

- [x] CHK010 Does the migration plan require verification, least privilege/RLS review, and rollback on a disposable database?
- [x] CHK011 Does the acceptance matrix map changed contracts to collected automated IDs and explain omitted layers?
- [x] CHK012 Does it distinguish offline verification from live provider acceptance and explain why live acceptance is not required?

## Reviewer decision

Requirements-level security review complete. The user choices and security boundaries are explicit enough to implement. Independent validation and root code review are still required before feature completion.
