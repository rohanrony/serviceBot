# Published token-refresh overwrite fix

- Branch: `fix/admin-email-refresh-overwrite-20261025`
- Commit: [`8768e05`](https://github.com/rohanrony/serviceBot/commit/8768e0505b87a99d8570452c61114f3f52caa789)
- Target at publication: `c04d72c8b237820ef72e7c5da2c5bf747327b54f` (`main`).
- Offline: verified with the complete exact-candidate gate: 2,481 unit/integration,
  714 E2E, including 134 browser journeys. Zero failures, errors, skips, xfails,
  or xpasses. The receipt was revalidated before push, the installed pre-push hook
  rechecked the live target, and GitHub read-back confirmed the exact branch SHA.
- Live provider: not required; provider request/delivery behavior is unchanged.
- Merged: no. Deployed: no. The user reserved the merge.

The independent commit includes the shared portal lock/merge helper, token-only
Gmail refresh update, API/browser regressions, coverage/engineering notes, and
an existing three-line deterministic booking-clock fixture correction. That
fixture correction preserves all duplicate-notification and future-reminder
assertions and is identical to the one already in the parallel change.

Restart/spin-down durability remains unimplemented. This publication does not
claim a complete fix for that hosting-lifecycle problem.

Verification receipt: `/Users/rohanroy/Coding/voiceService/scratch/verification/8768e0505b87a99d8570452c61114f3f52caa789-c04d72c8b237820ef72e7c5da2c5bf747327b54f/receipt.json`.
Isolated publication checkout: `/private/tmp/voice-admin-email-publish-20261025`.
The other working checkout and its pending application changes were preserved.
This local publication record supplements the immutable commit's pre-publication
coverage state; the receipt is the authoritative final execution evidence.
