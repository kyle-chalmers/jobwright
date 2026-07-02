---
description: Deprecated v1 alias — the gate now runs inside /start-job and /safe-deploy. Will be removed in 1.0.
---

# /validate-job (folded into /start-job and /safe-deploy in the v2 UX release)

The validation gate runs automatically in `/start-job` (before shipping) and `/safe-deploy`
(before any deploy). For a standalone check, run the CLI directly:

```bash
jobwright validate-job $ARGUMENTS
```
