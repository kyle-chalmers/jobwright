---
name: scaffold-job
description: Create a new governed job folder from a ticket — claude.md, notebook header, and a paused job-definition stub. Use when starting a brand-new job.
argument-hint: "<ticket> \"<job name>\""
allowed-tools: [Bash, Read, Edit]
---

# scaffold-job

## Steps

1. Scaffold the folder:
   ```bash
   jobwright new-job <ticket> "<job name>"
   ```
   This creates `<jobs_dir>/<ticket>_<Name>/` with a `claude.md`, a notebook carrying the required header, and (on deploy-from-repo platforms) a **paused** job-definition stub.
2. Fill in every `TODO` in the generated `claude.md` and notebook header — purpose, schedule, owner, data sources, outputs, integrations, architecture-compliance.
3. Implement the job logic in the notebook.
4. Gate it before shipping:
   ```bash
   jobwright validate-job <jobs_dir>/<ticket>_<Name>
   ```

## Done when

`jobwright validate-job` passes (PASS) and no `TODO` placeholders remain in the docs.
