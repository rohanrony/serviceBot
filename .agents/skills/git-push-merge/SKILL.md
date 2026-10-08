---
name: git-push-merge
description: Automated workflow to commit work, push to a new feature/dev branch, safely fast-forward merge into main without checking out main (protecting .env and avoiding sandbox locks), and push to remote origin.
---

# Git Push & Fast-Merge Workflow

Use this skill whenever you need to push ongoing work or completed commits to a branch, merge cleanly into `main`, and push the result to GitHub (`origin`).

Trigger phrases: `/git-push-merge`, "push to branch and merge with main", "merge to main and push", "deploy to main".

---

## ⚡ The Quick One-Liner

Run the automated workflow script:

```bash
bash scripts/git_push_merge.sh -b <branch_name> -m "<commit_message>"
```

### Common Variations

- **Push current branch and merge with main:**
  ```bash
  bash scripts/git_push_merge.sh -m "feat(telephony): add callback slot validation"
  ```

- **Create a new branch, commit, push, and merge:**
  ```bash
  bash scripts/git_push_merge.sh -b dev-v0.8.4-feature-name -m "feat: implement feature"
  ```

- **Fast push skipping tests (e.g. documentation or spec updates):**
  ```bash
  bash scripts/git_push_merge.sh -b docs-update -m "docs: update constitution" --skip-tests
  ```

- **Dry-run simulation:**
  ```bash
  bash scripts/git_push_merge.sh -b dev-v0.8.4 -m "test run" --dry-run
  ```

---

## 🛡️ Sandbox & Safety Rules

1. **Never run `git checkout main`**:
   Checking out `main` in the IDE sandbox can trigger file-permission errors, unstage tracked work, or attempt to overwrite local `.env` files.
   Instead, the workflow uses:
   ```bash
   git update-ref refs/heads/main <BRANCH_SHA>
   ```
   This updates local `main` directly at the git ref level in 1 millisecond with zero working-tree disruption.

2. **Network Sandbox Access (`BypassSandbox: true`)**:
   `git push` contacts GitHub (`github.com`), which requires outbound network access. Inside the agent, execute `bash scripts/git_push_merge.sh ...` with `BypassSandbox: true` so git can authenticate and push to remote origin.

3. **Global GitConfig Isolation**:
   The script automatically exports `GIT_CONFIG_GLOBAL=/dev/null` to prevent sandbox permission errors when accessing `~/.gitconfig`. Local author configurations (`user.name=rohanrony`, `user.email=rohanrony@gmail.com`) in `.git/config` are preserved and used automatically.

---

## 📋 Execution Protocol Steps

When invoked manually or by the agent:

1. **Status Inspection**: Verify `git status` and test suite readiness via `./run_tests.sh`.
2. **Branch Setup**: Create or checkout the target branch (`-b <branch_name>`).
3. **Commit**: Stage and commit all pending modifications (`-m "<message>"`).
4. **Push Branch**: `git push -u origin <branch_name>`.
5. **Safe Fast-Forward**: Verify `git merge-base main <branch_name>` and fast-forward local `main` pointer via `git update-ref refs/heads/main <branch_name>`.
6. **Push Main to Remote**: `git push origin main`.
7. **Verify & Report**: Display the commit hash, remote status, and active branch state.
