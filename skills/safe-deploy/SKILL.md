---
name: safe-deploy
description: Deploy a job change safely — diff live-vs-repo, check for active runs, and confirm before any destructive deploy. Use before pushing a job definition to the platform.
argument-hint: "<job>"
allowed-tools: [Bash, Read]
---

# safe-deploy

The point of this flow is that a definition change is **never** applied from a possibly-stale repo file without a human confirming the diff. The deploy-safety guard backstops you, but run the flow deliberately.

## Steps

1. **Diff first.** Compare the live definition against the repo definition:
   ```bash
   jobwright diff-job <job>
   ```
   - On `git-sync` platforms there is no live drift — use `git diff` and skip to step 4.
   - If `diff-job` reports **drift**, STOP. The repo does not match live. Reconcile (update the repo from live, or confirm the change is intended) before deploying — deploying now would overwrite live state. Surface the diff to the user.
2. **Check for active runs** before any trigger, to avoid duplicate runs and clobbering in-flight work.
3. **Confirm side-effects.** Note any downstream effects (file delivery, emails, partner uploads) and get explicit approval.
4. **Deploy.** Run the platform's deploy/update command. The deploy-safety hook will ask for confirmation — answer only after steps 1–3 are satisfied.
5. **Verify** the deploy landed (re-run `jobwright diff-job <job>` → expect no drift).

## Done when

The change is live, `jobwright diff-job <job>` shows no drift, and side-effects were confirmed beforehand.
