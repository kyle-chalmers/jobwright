# /triage-failure: turning an error into a cause and a fix

A failed run's error text is written for the platform's engineers, not for whoever is on call.
Translate it before proposing anything. If the platform adapter's playbook
(`adapters/platform/<kind>.md`) lists failure signatures of its own, check those first; the
table below covers the shapes every orchestrator shares.

| Signature in the error or log | Plain cause | Class | What fixes it |
|---|---|---|---|
| permission denied, not authorized, insufficient privileges, access denied | the identity the job runs as lost (or never had) a grant on an object | config | grant the named privilege on the named object to the job's run-as identity; nothing in the job's code changes |
| table, view or object does not exist / not found | an upstream object was renamed, dropped, or not built yet this cycle | upstream-data | check `OBJECTS.md` for who writes it; if it moved, swap the reference (`/architecture-audit` may already list it) |
| zero rows, empty input, no files found | the upstream job has not landed today's data | upstream-data | confirm the upstream run's state; re-trigger once it lands, nothing to change |
| timeout, exceeded max duration, deadline | the job outgrew its time budget, or a dependency hung | transient/infra or code | a one-off after a slow upstream is transient; a steady climb over recent runs is a code or sizing fix |
| out of memory, container killed, executor lost | the data volume outgrew the compute the job was given | transient/infra or config | a one-off spike is transient; repeated → resize the compute in the job definition |
| connection reset, refused, DNS, 5xx from a service | a network or service hiccup outside the job | transient/infra | re-trigger; if it repeats, the external integration in `claude.md` is the suspect |
| duplicate key, unique constraint, merge matched more than once | the job wrote the same rows twice, or the source has duplicates | code or upstream-data | find which: a re-run that was not idempotent, or new duplicates upstream |
| column not found, type mismatch, cannot cast | the source schema changed under the job | upstream-data then code | confirm the upstream change, then update the job's read |
| syntax error, name not defined, import error | the deployed code itself is broken | code bug | `/start-job <job>` plans the fix; `validate-job` catches syntax before the next deploy |

## Report it in this shape

```
Failed at:  <task or step name>, run <run-id>
Cause:      <one plain sentence, naming the real object or service>
Class:      transient/infra | upstream-data | config | code bug
Fix:        <the concrete change, or "none: re-trigger after <condition>">
Data partially written?  yes | no | unknown (and which object)
```

The last line matters: a run that wrote half its output can double-count on re-trigger. Say
`unknown` rather than guess; checking the output object's latest rows settles it.

## When nothing matches

Report the step name and the error verbatim and say the signature is unrecognized. Never guess a
fix you cannot ground in the log. Then record the new signature, cause and fix in the job's
`claude.md` Known Issues once it is found, so the next on-call starts ahead.
