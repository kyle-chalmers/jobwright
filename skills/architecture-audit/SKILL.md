---
name: architecture-audit
description: Scan job code for deprecated-schema references and layer-referencing violations to drive a schema migration. Use when planning or tracking a data-layer migration, or auditing a job's compliance.
argument-hint: "<path> (a job folder, the whole jobs dir, or specific files)"
allowed-tools: [Bash, Read]
---

# architecture-audit

Static compliance scan driven by the `architecture` config block. No database connection.

## Steps

1. Scan the target path (a job folder, the whole jobs directory, or specific files):
   ```bash
   jobwright check architecture <path> --format md
   ```
   Use `--format json` to feed results into a tracker or summary.
2. Read the findings. Two kinds:
   - **deprecated** — a reference to a schema being migrated away from. Migration debt; includes a replacement hint when configured.
   - **layer-violation** — a job that declares its layer references a schema its layer is not allowed to. This is a real compliance break.
3. For a migration sweep, also consult `jobs/OBJECTS.md` (run `jobwright jobs-index` first) to see every job that touches a given object before changing it.
4. Propose fixes that replace deprecated references with the configured target objects. Do not edit business logic beyond the reference swap without confirming.

## Done when

The scan is clean, or the remaining findings are captured as migration follow-ups with their target replacements identified.
