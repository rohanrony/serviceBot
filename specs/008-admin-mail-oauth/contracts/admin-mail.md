# Admin mail contract

GET /api/v1/portal/gmail-config returns gmail_auth_type=oauth2, current preferences, Google client ID, has_client_secret and is_connected. No SMTP fields or has_password are exposed.

POST /api/v1/portal/gmail-config accepts existing enabled/selection/sender/recipient/admin-phone/Google-client fields and optional gmail_auth_type=oauth2. Unsupported selectors or any unknown/SMTP fields return 422 without mutation. On success retain Google tokens, preserve stored sender for blank input, and remove old SMTP configuration.

POST /api/v1/portal/gmail-config/test uses the same validation, requires the system Google refresh token, and sends using the existing system Google helper. Missing connection is 400, failed sends are 500, success is {success:true}. There are no writes or staff fallback in this explicit system connection test.

Admin Mail always shows Google status, connect/reconnect, help, notification preferences and existing unrelated admin SMS controls. No authentication choice, SMTP fields or editable sender is shown. Save/test payloads select oauth2 and preserve the existing sender through loaded state.

Booking delivery retains staff-first Google sending and uses system Google on fallback. Admin delivery attempts system Google and retains the existing connected staff-account fallback after failure. Disabled or missing-address cases return false without sending. SMTP is never called.
