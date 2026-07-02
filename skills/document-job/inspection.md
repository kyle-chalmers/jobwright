# /document-job — inspection mode

How to draft each field from the code. Every claim must have a line of code behind it; when the
evidence is ambiguous, write the draft anyway and flag it `(unconfirmed)` for the user pass.

| Field | Where the evidence lives |
|---|---|
| **Purpose** | what the final writes/exports actually produce; the notebook's own comments |
| **Schedule** | the job-definition file's schedule/cron block; a paused stub means "not yet scheduled" |
| **Business Owner** | notification/error-email addresses, code comments, git authorship — usually needs user confirmation |
| **Data Sources** | every table/view read: `FROM`/`JOIN` targets, read calls in the notebook |
| **Data Outputs** | every write: `INSERT`/`MERGE`/`CREATE` targets, files written, tables saved |
| **External Integrations** | outbound calls: mail/SFTP/object-storage/spreadsheet clients, webhooks — or "none" |
| **Architecture Compliance** | run `jobwright check architecture <job-folder>`; record the layer and any flagged references |
| **Notebook header (JOB / TICKET / PURPOSE / STATUS)** | folder name carries ticket + job name; STATUS from the definition (paused/active) |

Rules:

- Quote or cite the evidence when presenting the draft (e.g. "reads `ANALYTICS.VW_X` — cell 3"),
  so the user reviews claims, not prose.
- Mark genuine unknowns `TODO(user):` and ask them all in **one** consolidated question.
- Never invent an owner, schedule, or integration. An explicit "UNKNOWN" that the gate flags is
  better than a plausible guess that ships.
