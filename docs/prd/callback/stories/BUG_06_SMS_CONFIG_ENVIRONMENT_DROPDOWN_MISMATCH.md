# Bug 06: SMS Config Environment Dropdown Shows Mismatched Initial Value

## Bug Description
When loading the SMS Configuration tab, the Environment Mode dropdown defaults to displaying `PRODUCTION` even though the backend database default environment is `TESTING` / `TEST`.

## Specification Reference
- **Specification**: `docs/specs/sms_system_specification.md` §6 & §7.1
- **Requirement**: Environment configuration option with values `PRODUCTION`, `STAGING`, `TEST`.

## Root Cause Analysis
- In `serviceBot/db/migrations.py` (line 77) or database seed, the `environment` column value is set to `'TESTING'`.
- In `serviceBot/static/index.html` (lines 1010-1015), the select options are:
  ```html
  <select id="sms-config-environment" class="form-control">
    <option value="PRODUCTION">PRODUCTION</option>
    <option value="STAGING">STAGING</option>
    <option value="TEST">TEST</option>
  </select>
  ```
- When `loadSMSConfig()` runs in `app.js`, `data.environment` is `'TESTING'`. Because `'TESTING'` does not match option value `'TEST'`, the DOM `<select>` defaults to showing the first option (`PRODUCTION`).

## Steps to Reproduce
1. Navigate to `http://127.0.0.1:8000/portal/#sms-config`.
2. Observe the **Environment Mode** dropdown on initial page load.
3. Note that it displays `PRODUCTION` instead of `TEST` / `TESTING`.

## Expected Behavior
- Ensure database seed/default and API response normalize `environment` to `'TEST'`.
- Map `'TESTING'` to `'TEST'` in `loadSMSConfig()` in `app.js` so the select element properly selects `TEST`.

## Proposed Remediation Checklist
- [ ] Update `loadSMSConfig()` in `app.js` to normalize `'TESTING'` → `'TEST'`.
- [ ] Normalize default seed value in DB query / migration to `'TEST'`.
