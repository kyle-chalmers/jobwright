---
name: safe-deploy
description: Deploy a job change safely — validate the job first (always), diff live-vs-repo, check for active runs, and confirm before anything destructive. The only sanctioned way to deploy.
argument-hint: "<job>"
allowed-tools: [Bash, Read]
---

# /safe-deploy

Two rules make this flow safe: a job that fails validation **never deploys**, and a definition
change is **never** applied from a possibly-stale repo file without a human confirming the diff.
The deploy-safety guard backstops you at the command level, but run the flow deliberately.

## Steps

1. **Validate first — no exceptions.**
   ```bash
   jobwright validate-job <job-folder>
   ```
   On FAIL, stop here: fix the findings (or hand back to `/start-job`) and re-run until PASS.
   Deploying an unvalidated job is the exact bypass this step closes.
2. **Diff live-vs-repo.**
   ```bash
   jobwright diff-job <job>
   ```
   - If the platform deploys straight from git, `diff-job` says so — review `git diff` instead
     and skip to step 5.
   - If it reports **drift**, STOP. The repo does not match live; deploying now would overwrite
     live state. Surface the diff and reconcile (update the repo from live, or confirm the change
     is intended) before going further.
3. **Check for active runs** before any trigger, to avoid duplicate runs and clobbering in-flight
   work.
4. **Confirm side-effects.** Name any downstream effects (file delivery, emails, partner uploads)
   and get explicit approval.
5. **Deploy.** Run the platform's deploy/update command. The deploy-safety guard prompts before
   known destructive commands (reset/update/delete/drop/replace and destructive SQL) — but treat
   steps 1–4 as the real gate, not the prompt, since the guard covers known patterns rather than
   every possible command.
6. **Verify** the deploy landed: re-run `jobwright diff-job <job>` → expect no drift.

## Done when

The job validated PASS before deploying, the change is live, `jobwright diff-job <job>` shows no
drift, and side-effects were confirmed beforehand.
