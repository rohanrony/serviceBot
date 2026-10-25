# Review Handoff: Voice Agent Prompt and Catalogue Sync

## Follow-up execution record — 2026-10-25

- **Branch:** `dev-v0.19.3-prompt-and-catalogue-sync`.
- **Base commit:** `33e08f753b81df255dbdee43cd1f4b82d067b9b8`. The fixes and regression tests include uncommitted working-tree changes; the results below do not describe that commit alone. No immutable snapshot of the host-tested working tree was supplied.
- **Latest correction:** added the missing `asyncio` and `contextmanager` imports in `tests/test_prompt_and_catalogue_sync.py`. Both imports were independently confirmed present in the current checkout. This follow-up changes only this review document.
- **Host execution reported by the implementer:** disposable PostgreSQL (`postgresql@18`, `127.0.0.1:5432`), using:

  ```sh
  ./run_tests.sh --file tests/test_prompt_and_catalogue_sync.py
  ```

- **Reported result:** 16 passed, 0 failed, 1 warning in 5.35 seconds. This host execution was not independently rerun by the reviewer.
- **Coverage boundary:** focused offline regression coverage. Provider requests are mocked, and the locking regression uses synthetic database resources. Availability of PostgreSQL to the test harness does not establish real cross-process PostgreSQL locking. Live ElevenLabs synchronization and deployed behavior remain unverified; no live/paid provider calls or provider configuration changes were made as part of this review.
- **Scoped disposition:** the reported missing-import failures are resolved. No additional implementation work is indicated by the supplied execution results. No production-code, infrastructure, or root-test-harness changes are requested by this follow-up.

## Original review brief — historical baseline

The observations and line references below describe the original target checkout, before the follow-up fixes. They are retained as the review brief, not as current unresolved findings. Its read-only instructions applied to the original source review; the later documentation update above was requested separately.

**Prepared:** 2026-10-25  
**Target checkout:** branch `feat/business-neutral-portal-20261021`, commit `c04d72c8b237820ef72e7c5da2c5bf747327b54f`  
**Review type:** read-only source and behavior review

## Request

Please verify whether business configuration and service catalogue changes reach the voice agent reliably. Focus on the distinction between updating the agent's system prompt and updating data the agent retrieves through backend tools.

Report findings with severity, source locations, observable impact, and the smallest recommended correction. Do not edit files, commit, deploy, change provider configuration, or make live/paid provider calls as part of this review.

## Current source-path observations

### Business configuration and prompt

- `POST /api/v1/portal/config` merges submitted values with the saved configuration (`serviceBot/api/portal.py:576-610`).
- When hours are submitted, it runs `update_prompt_business_hours` using the configured opening/closing hours, days, and timezone; it also applies configured booking lead-time buffers, saves the resulting prompt, and calls the ElevenLabs sync function (`serviceBot/api/portal.py:663-686`; `serviceBot/services/prompt_service.py:163-250`).
- The business-profile editor sets `regenerate_business_prompt: true`; the work-hours form submits hours and days without that flag (`serviceBot/static/app.js:306-323`, `3173-3206`). The hours updater therefore modifies recognized schedule sections in the existing prompt rather than rebuilding the whole prompt.
- The provider sync attempts a PATCH for configured development and production agent IDs and reports `synced`, `failed`, or `unavailable` (`serviceBot/api/portal.py:426-516`). The config endpoint still returns `success: true` and `saved: true` when `provider_sync` is failed or unavailable (`serviceBot/api/portal.py:682-714`).
- The work-hours form checks only the HTTP response and displays a success toast; it does not inspect `provider_sync` (`serviceBot/static/app.js:3195-3209`). The provider code treats HTTP 200 as synced; no provider read-back comparison is visible in this path.

### Service catalogue

- Service create, update, and delete operations write to the `services` table and schedule `sync_services_to_kb` as a background task (`serviceBot/api/portal.py:778-856`).
- That task rebuilds `auto_services_catalog.txt` from service name, description, price, and duration, then replaces its searchable RAG chunks (`serviceBot/api/portal.py:394-424`; `serviceBot/services/rag.py:190-199`).
- Runtime service-field lookup queries the current `services` table (`serviceBot/db/queries.py:1328-1348`). FAQ lookup also prepends a current catalogue read from that table to retrieved context (`serviceBot/services/rag.py:74-117`; called from `serviceBot/api/telephony.py:2449-2456`).
- Catalogue mutations do not call `sync_prompt_to_elevenlabs`. The prompt tells the agent to use catalogue and knowledge-base tools; catalogue values are retrieved at runtime rather than embedded in the main agent prompt.

## Questions for the reviewer

1. Does the business-hours path update every prompt section that can influence what the agent says or books, including supported custom prompts and timezone changes?
2. Is the provider sync result enough to claim the hosted agent has the new prompt, or should sync include a read-back/equivalent verification and persisted retry state?
3. Should the API or UI distinguish “saved locally” from “synced to every configured agent”? What should happen when one target agent succeeds and another fails?
4. Is the asynchronous catalogue refresh observable and recoverable if it fails? Can stale RAG chunks conflict with the live database catalogue presented to the agent?
5. Are the existing runtime database lookups sufficient for catalogue freshness, including service fields and price/duration, or are there tool paths that can return stale catalogue data?

## Evidence requested

Please validate these behaviors from source and, if appropriate, isolated automated tests. Do not use production data or live provider calls.

- Change business hours in an isolated config/test environment. Verify the saved prompt contains the new schedule in all applicable sections and the response clearly reports provider sync success, failure, or unavailability.
- Simulate a provider rejection and missing credentials. Verify the user-facing status does not imply the hosted prompt is synced.
- Create, edit, and delete a service in an isolated database. Verify `get_service_fields` and FAQ lookup reflect the current record, and verify the catalogue RAG refresh removes obsolete catalogue content after completion.
- Confirm that a catalogue edit does not needlessly rewrite the main prompt, while changes to prompt-backed business-profile values are handled as intended.

## Review boundary

This brief records source observations on the target checkout. It does not establish current deployed behavior or live ElevenLabs state. No tests, provider calls, or deployment checks were run while preparing it.
