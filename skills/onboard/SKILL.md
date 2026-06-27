---
name: onboard
description: First-time setup for a jobwright repo — install/verify the CLI, create or check the config, and confirm the environment is ready. Use on a fresh checkout or new machine.
argument-hint: "(no arguments)"
allowed-tools: [Bash, Read]
---

# onboard

## Steps

1. Confirm the CLI is installed: `jobwright version` (install with `pip install jobwright` or `uvx jobwright` if missing).
2. If the repo has no config yet, create a starter: `jobwright init`, then edit `jobwright.config.yaml` for this repo (platform, profile, deploy model, job dirs, architecture rules).
3. Verify everything resolves: `jobwright doctor` — it reports the platform, profile, adapter, and whether the platform CLI is on PATH.
4. Generate the catalog: `jobwright jobs-index`.
5. (Optional) Generate the rulebook: `jobwright gen-agents -o AGENTS.md`.

## Done when

`jobwright doctor` is green and `JOBS.md` exists.
