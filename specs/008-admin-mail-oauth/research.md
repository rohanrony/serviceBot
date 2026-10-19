# Research

- Decision: remove SMTP throughout the admin mail configuration and its shared notification delivery.
  Rationale: both notification functions and the test endpoint currently branch to the same legacy helper; hiding the selector alone would leave it executable.
  Alternatives: UI-only hiding rejected because it leaves legacy API and transport behavior.
- Decision: retain existing Google routing and staff-account fallback, ignore stored legacy selector for delivery, and remove obsolete fields on explicit settings save.
  Rationale: preserves existing OAuth credentials and avoids startup rewrites. Old app-password-only installations need to connect Google before sending.
- Decision: reject unsupported selectors and extra SMTP payload fields with validation errors; omitted selector defaults to oauth2.
  Rationale: old clients receive explicit failure with zero writes/sends instead of silent fallback.
- Existing stack and provider boundaries are retained. No unresolved research questions or external documentation dependency.
