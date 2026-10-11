---
name: architecture-audit
description: Scan job code for deprecated-schema references and layer-referencing violations to drive a schema migration. Use when planning or tracking a data-layer migration, or auditing a job's compliance.
argument-hint: "<path> (a job folder, the whole jobs dir, or specific files)"
allowed-tools: [Bash, Read]
---

# architecture-audit

Finds every reference to a schema your team is retiring, and every job reading from a layer it
should not, so a migration can be ticketed job by job. It reads code only, against the
`architecture` rules in the config: no database connection, nothing written. Narrate as you go
([../_shared/narrate.md](../_shared/narrate.md)); terms are in [concepts](../../docs/concepts.md).

## Steps

1. Scan the target path (a job folder, the whole jobs directory, or specific files):
   ```bash
   jobwright check architecture <path> --format md
   ```
   Use `--format json` to feed results into a tracker or summary.
2. Read the findings and report them as counts per kind and per job before any detail. Two kinds:
   - **deprecated** (migration debt): a reference to a schema being retired. It does not fail
     the gate; it is work to schedule. Includes the replacement when the config names one.
   - **layer-violation**: a job that declares its layer reads from a layer it is not allowed
     to. This is a real compliance break and fails `validate-job`, so list these first.
3. For a migration sweep, also consult `<jobs_dir>/OBJECTS.md` (`jobwright jobs-index --check`
   first; regenerate if stale) to see every job that touches a given object before changing it.
   Why: a schema swap in one job can break a job downstream that reads what it writes.
4. Propose fixes that replace deprecated references with the configured target objects. Do not
   edit business logic beyond the reference swap without confirming: a migration ticket is
   reviewed as a rename, and a logic change hidden inside it gets missed.

## Done when

The scan is clean, or the remaining findings are captured as migration follow-ups with their target replacements identified.

## Next

One ticket per affected job (or one migration ticket listing them): `/start-job <ticket>` plans the reference swap against that job's code and gates it; `/safe-deploy <job>` ships it. `/setup` also reports this debt count on adoption.
