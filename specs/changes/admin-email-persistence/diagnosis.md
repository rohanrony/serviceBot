# Deployed admin email diagnosis — 2026-10-25

## Authorized scope and environment

The user confirmed the ADS Render workspace for the initial read-only diagnosis.
Subsequently the user provided the intended admin address and explicitly
authorized one production save with immediate read-back. That check completed at
19:17 UTC, as recorded below. No deployment, explicit restart, or test email was
performed.

- Workspace: `tea-d1qjmc7fte5s73dekhcg` (ADS).
- Service: `srv-d98r46ucjfls73f5lsgg` (`serviceBot`).
- Origin: `https://servicebot-w6hm.onrender.com`.
- Service metadata: Free compute plan, one instance, cache profile `no-cache`,
  branch `main`, start command `uvicorn serviceBot.main:app --host 0.0.0.0 --port $PORT`.
- Live deploy: `dep-dbdrch8u01pc73drb69g`, commit
  `c04d72c8b237820ef72e7c5da2c5bf747327b54f`; finished 2026-10-23 19:35:14 UTC.
  The local token-refresh fix remains uncommitted and is not in that deployment.
- Observation time: 2026-10-25 17:53 UTC; the live deploy was rechecked at 17:57
  UTC and remained `dep-dbdrch8u01pc73drb69g` / `c04d72c8...`.
  Times below are Render log timestamps;
  buffered application output may be captured later than the underlying operation.

## Bounded queries

All log queries selected this service, `type=app`, forward order, and limit 100.
All retained responses reported `hasMore=false`; no remaining page was indicated.

1. 16:00–17:10 UTC, literal text `gmail-config`: four entries.
2. 16:00–17:10 UTC, literal text `Google OAuth2`: zero entries. This is absence
   of retained matching logs, not proof that no token operation occurred.
3. 16:37:50–16:39:20 UTC, all application logs: 37 entries. One initial query
   with limit 150 was rejected by connector validation and was replaced with
   this successful limit-100 query. Unrelated content was omitted from this record.
4. 16:00–17:10 UTC, literal text `Started server process`: one entry.
5. 16:00–17:10 UTC, literal text `Shutting down`: two entries.

The latest eight deploys were inspected. The current deploy was still the October
23 commit; no later deployment was shown in this bounded result. The current
service metadata was read independently.

## Observed timeline

| UTC | Eastern time | Observation | Render log entry ID |
| --- | --- | --- | --- |
| 16:09:06 | 12:09:06 PM | Earlier instance `…-xqcr6` shut down | `3f723d2a-6051-4667-bb1a-d153e47cf0a1` |
| 16:37:23 | 12:37:23 PM | Instance `…-rbhhl` started server process 40 | `492b7695-74a9-4759-b828-f69ce5cd8d9b` |
| 16:37:59 | 12:37:59 PM | Application startup completed | `358e86c2-b14d-483e-86d5-77e59580d3cb` |
| 16:38:11 | 12:38:11 PM | Gmail settings GET returned 200 | `3cdbe087-2287-47d8-83a2-92f4a01b86ec` |
| 16:38:30 | 12:38:30 PM | Gmail settings POST returned 200 | `b2516725-78a8-4e14-ae46-5a9597b72b92` |
| 16:38:31 | 12:38:31 PM | Following Gmail settings GET returned 200 | `3364abf3-fc76-41c0-b183-415041cecf1d` |
| 16:41:47 | 12:41:47 PM | Later Gmail settings GET returned 200 | `bfdcf8a3-7590-4ca0-90bb-d89d4b4fba22` |
| 17:05:40 | 1:05:40 PM | Instance `…-rbhhl` shut down | `dafa5348-4fcb-45f9-a157-4ea18925b726` |

The save and following read used the same full instance ID:
`srv-d98r46ucjfls73f5lsgg-rbhhl`. The complete 90-second incident query contained
no other settings-write HTTP request. Its other relevant entries included staff
Google Calendar token refreshes before the save; those update staff credentials
and are distinct from the system Gmail configuration refresh reproduced offline.
No configuration-file error was found among those 37 retained entries.

These are log-entry IDs, not provider IDs or HTTP request IDs. The logs do not
retain the submitted recipient or response bodies. A status of 200 therefore
does not establish which email was submitted or returned in that immediate GET.
The earlier read-only browser/API inspection showed the previous recipient,
but it did not capture the original POST body.

## Findings and limits

1. **Confirmed deployment durability gap.** The email and system Google settings
   are stored in application-local `serviceBot/config.json`. Render documents
   that a Free web service loses local filesystem changes whenever it redeploys,
   restarts, or spins down, and cannot attach a persistent disk. This service's
   observed shutdown/startup events make this an applicable persistence defect,
   not merely a hypothetical deployment concern. It explains why a saved value
   cannot be relied on across those lifecycle events. It does not establish that
   a lifecycle event occurred between the recorded save and its immediate read.
   Source: [Render Free filesystem behavior](https://render.com/docs/free#local-files-lost-on-redeploy).
2. **Confirmed local token-refresh lost update, not correlated to this incident.**
   The existing offline reproduction and fix remain valid. No system Gmail refresh
   log was found in the queried window, so that race is not a confirmed explanation
   for this particular deployed save. The patch also does not repair restart/spin-down
   durability.
3. **Original immediate reversion was not reproduced in the controlled check.** The known original save and following read
   succeeded on the same instance less than one second apart. The new intended
   email was initially unknown, and the original submitted value was not captured.
   The user subsequently designated the intended recipient, and the controlled
   browser save/read-back below succeeded. The original immediate failure's
   specific cause is still unconfirmed.

## Controlled check — completed with explicit authorization

The user supplied the intended recipient and explicitly authorized one production
save. Before the check, the service had spun down and the browser displayed
Render's startup page. Render then logged a new server process at
19:09:28.646526827 UTC on instance `…-wwkv2` (log entry
`7e370467-ef95-43c2-90bb-098a67ce71b4`).

After startup, the form showed a different recipient from the user-designated
address. This differs from the earlier 16:41 read, which had already shown the
address the user later designated. Calling that earlier value the "old" address
before the user supplied their intent was premature; the current check uses the
explicitly designated value as its acceptance criterion.

A terminal helper was prepared but remained pending. Its executable path was
disabled and an exclusive directory interlock blocked its mandatory pre-POST
receipt path before switching to the browser, preventing a duplicate submission.
No terminal POST was made.

In the deployed browser, only the email input was edited and Save was clicked
once at 19:17:21.582 UTC. The existing form submitted its other current values
unchanged. The page displayed its Gmail configuration success message.

| UTC | Observed result | Render log entry ID |
| --- | --- | --- |
| 19:17:22.612 | POST `/api/v1/portal/gmail-config` returned 200 | `a6f22ec6-688f-4930-b788-d2237d18e763` |
| 19:17:22.997 | Automatic settings read returned 200 | `61554363-417c-47fa-8819-22e8cf1aebe1` |
| 19:17:31.909 | Settings read after a full page reload returned 200 | `d4bca9bb-e6c4-48ec-b6d3-fd05b8bdd0e7` |

At 19:17:32.330 UTC the reloaded form displayed the designated recipient.
All three notification/selection checkboxes, the admin phone value, and the
Google connection status matched their pre-save UI values. All three requests
above used instance `srv-d98r46ucjfls73f5lsgg-wwkv2`. The filtered app-log query
covered 19:16:50–19:18:00 UTC and returned these three entries with
`hasMore=false` as observed at 19:17:41 UTC; no claim is made about later events.

Redacted evidence is retained in
`scratch/admin-email-controlled-browser-save-20261025.json`. Screenshot export
was blocked by automatic approval review because the verification image contains
contact information; text and server-log evidence were retained instead. The
verified settings tab was kept available. No test email, test SMS, reconnect,
manual restart, or deployment action was invoked.

Live application save/reload: verified for the current deployed commit and this
designated recipient. This does not establish restart durability, provider
delivery, or the undeployed token-refresh fix's live behavior.

Durable settings storage still requires a separate design/migration decision; the
in-process token-refresh patch alone is not a complete resolution of the deployed
notification-settings persistence problem.

## Concurrent workspace change and validation

During this read-only diagnosis, a separate workflow moved the checkout to
`dev-v0.19.3-prompt-and-catalogue-sync` and created
`33e08f753b81df255dbdee43cd1f4b82d067b9b8`. That commit includes the shared portal
configuration lock/merge helper. The Gmail refresh change and its regression
tests remain uncommitted; the complete fix is not deployed. Those changes and
the other workflow's work were preserved.

The prior 2,488-unit/integration and 716-E2E pass remains historical evidence for
the recorded working tree based on `c04d72c8...`. It is not an exact-candidate
verification of the new HEAD; publication verification must be refreshed after
the complete candidate and target are selected. This diagnostic turn changed
only documentation and coverage evidence, which received YAML/reference and
scoped whitespace validation. No application suite was rerun for those document
edits.
