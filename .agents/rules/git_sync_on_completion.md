# Rule: Proactive Git Synchronization on Verified Milestone Completion

1. **Mandatory Post-Verification Sync**: Whenever an implementation task, feature, bug fix, or architectural upgrade is completed, verified with passing tests, and documented:
   - The agent MUST proactively stage all modified and newly created repository files.
   - The agent MUST craft a structured conventional commit message (e.g., `feat(module): ...`, `fix(module): ...`, `test(module): ...`).
   - The agent MUST immediately push the commit to the active remote branch (`git push origin main`).
2. **Zero User Reminders Required**: The agent must never leave verified, clean code uncommitted or unpushed, waiting for the user to ask for a Git push. Pushing to remote is an integral definition-of-done step for every development milestone.
3. **Repository Scope & Sanity**:
   - Always run `git status` to ensure secrets (`.env`) or temporary test files are never inadvertently committed.
   - Ensure the repository documentation (`chats.md` and walkthroughs) is synchronized with the latest entries before committing.
