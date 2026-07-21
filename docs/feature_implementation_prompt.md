# Feature Implementation Prompt

Copy and paste this prompt when instructing an AI assistant to implement new features in this codebase. This ensures they update documentation and expand the test suite alongside code changes.

---

```markdown
You are implementing the following feature changes:
<INSERT_FEATURE_DESCRIPTION>

To ensure repository consistency, you must follow these strict rules:

1. CODE: Implement the feature cleanly, adhering to existing architectural patterns.
2. DATABASE: If database schema changes are required:
   - Update the DDL schema in `serviceBot/db/connection.py`.
   - Update `docs/specs/database_spec.md` with new tables/fields.
3. DOCUMENTATION:
   - Update the main `docs/PRD.md` or relevant `docs/specs/` file to match the new behavior.
   - Update API specifications in `docs/specs/api_spec.md` if any endpoint contracts change.
4. TESTING:
   - Write comprehensive unit/integration tests for the new logic under `tests/`.
   - Run the testing suite using `bash run_tests.sh` and verify all tests pass.
   - Follow the guidelines in `TESTING.md` (e.g. using redirected scratch directories).
```
