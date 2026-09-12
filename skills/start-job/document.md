# /start-job — documenting a job from its code

Documentation is drafted *from the code*, not collected from the user field by field. Every
claim needs a line of code behind it; when the evidence is ambiguous, write the draft anyway and
flag it `(unconfirmed)` for the user pass. Check what is missing first with
`jobwright check docs <folder>`; re-run it after applying until clean.

| Field | Where the evidence lives |
|---|---|
| **Purpose** | what the final writes/exports actually produce; the notebook's own comments |
| **Schedule** | the job-definition file's schedule/cron block; a paused stub means "not yet scheduled" |
| **Business Owner** | notification/error-email addresses, code comments, git authorship — usually needs user confirmation |
| **Data Sources** | every table/view read: `FROM`/`JOIN` targets, read calls in the notebook |
| **Data Outputs** | every write: `INSERT`/`MERGE`/`CREATE` targets, files written, tables saved |
| **External Integrations** | outbound calls: mail/SFTP/object-storage/spreadsheet clients, webhooks — or "none" |
| **Architecture Compliance** | `jobwright check architecture <folder>`; record the layer and any flagged references |
| **Notebook header (JOB / TICKET / PURPOSE / STATUS)** | folder name carries ticket + job name; STATUS from the definition (paused/active) |

Rules:

- Quote or cite the evidence when presenting the draft (e.g. "reads `ANALYTICS.VW_X` — cell 3").
- Mark genuine unknowns `TODO(user):` and ask them all in **one** consolidated question — the
  same question that approves the plan.
- Never invent an owner, schedule, or integration. An explicit "UNKNOWN" that the gate flags is
  better than a plausible guess that ships.
