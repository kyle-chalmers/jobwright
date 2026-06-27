"""Databricks Jobs adapter — the reference implementation of the verb contract.

Deploy model is ``api-reset``: a job definition is pushed to the workspace via the
API, so the *live* definition can drift from the repo JSON. That is exactly the
condition behind the production incident this kit exists to prevent — a
``databricks jobs reset`` from a stale repo JSON silently overwrote correct live
state and broke jobs. So ``get_live_definition`` + ``diff_live_vs_repo`` are
first-class here, and ``databricks jobs reset`` is a guarded command.

Stdlib-only (subprocess + json). Shells out to the ``databricks`` CLI.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from .base import (
    ActiveRun,
    DiffResult,
    JobDefinition,
    JobPlatformAdapter,
    JobRef,
    ManualFallback,
    RunInfo,
    RunOutput,
    run_cli,
)

# Keys that are pure runtime/identity metadata (assigned by the platform), not part
# of the authored definition. Dropped from both sides before diffing so a diff reflects
# real config drift. NOTE: `run_as` is authored config (execution identity) and is
# deliberately NOT dropped — a silent run_as change is exactly the drift we must catch.
_VOLATILE_KEYS = {
    "job_id",
    "created_time",
    "creator_user_name",
    "effective_budget_policy_id",
    "settings",  # unwrapped before diffing (see _normalize)
}

# Lists whose order is not semantically meaningful — keyed by a stable id. Canonicalized
# (sorted by that key) before diffing so reordering doesn't read as false drift.
_KEYED_LISTS = {"tasks": "task_key", "job_clusters": "job_cluster_key"}


class DatabricksAdapter(JobPlatformAdapter):
    kind = "databricks"
    deploy_model = "api-reset"
    destructive_patterns = [
        {
            "pattern": r"databricks\s+jobs\s+reset\b",
            "reason": (
                "`databricks jobs reset` is a FULL REPLACE of the live job definition from "
                "the file you pass. Repo job JSONs can be STALE (jobs are sometimes edited in "
                "the Databricks UI). Pull the live definition and run `jobwright diff-job` first "
                "— a reset from a stale JSON has previously overwritten correct live state and "
                "broke multiple production jobs. Confirm the diff is intentional before resetting."
            ),
        },
        {
            "pattern": r"databricks\s+jobs\s+delete\b",
            "reason": "`databricks jobs delete` permanently removes a job. Confirm the target job_id and that it is intended.",
        },
        {
            "pattern": r"databricks\s+jobs\s+update\b",
            "reason": "`databricks jobs update` mutates the live job definition. Run `jobwright diff-job` first so the change is intentional, not applied from a stale repo JSON.",
        },
        {
            "pattern": r"databricks\s+jobs\s+(run-now|submit)\b",
            "reason": (
                "Triggering a production run can have downstream side-effects (file delivery, "
                "emails, partner uploads). Check for already-active runs first "
                "(`databricks jobs list-runs --active-only`) and confirm the side-effects are intended."
            ),
        },
    ]

    # ----- internal helpers --------------------------------------------------
    def _cli(self, *args: str, timeout: int = 60):
        cmd = ["databricks", *args]
        if self.profile:
            cmd += ["--profile", self.profile]
        return run_cli(cmd, timeout=timeout)

    def _cli_json(self, *args: str, timeout: int = 60):
        cmd = ["databricks", *args, "-o", "json"]
        if self.profile:
            cmd += ["--profile", self.profile]
        proc = run_cli(cmd, timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError(
                f"databricks {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()[:400]}"
            )
        try:
            return json.loads(proc.stdout or "null")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"databricks {' '.join(args)}: non-JSON output: {exc}") from exc

    def _job_def_dirs(self) -> list[Path]:
        """Configured job-definition dirs, prod first — so an ambiguous match prefers
        the prod definition rather than comparing live prod to a dev JSON."""
        dirs: list[Path] = []
        if self.config is not None:
            items = self.config.platform.job_def_dirs or {}
            for env in (["prod"] + [e for e in items if e != "prod"]):
                if env in items:
                    dirs.append(Path(items[env]))
        return dirs

    def _find_repo_def_file(self, ref: str) -> Path | None:
        """Resolve a repo job-definition JSON by name, filename stem, or ticket key."""
        ref_l = ref.lower()
        ticket = ref.split("_", 1)[0].lower()  # e.g. "BI-813" from "BI-813_Remitter"
        candidates: list[Path] = []
        for d in self._job_def_dirs():
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.json")):
                stem = f.stem.lower()
                if stem in (ref_l, ticket) or stem.startswith(ticket + "_"):
                    candidates.append(f)
                    continue
                try:
                    name = (json.loads(f.read_text()) or {}).get("name", "")
                except (OSError, json.JSONDecodeError):
                    name = ""
                if name and name.lower() == ref_l:
                    candidates.append(f)
        # _job_def_dirs() yields prod first, so the first candidate is the prod match.
        return candidates[0] if candidates else None

    @staticmethod
    def _normalize(spec: dict) -> dict:
        """Return the authored settings: unwrap `settings`, drop volatile keys, and
        canonicalize keyed lists (tasks/job_clusters) so reordering isn't false drift."""
        if isinstance(spec.get("settings"), dict):
            spec = spec["settings"]
        out = {k: v for k, v in spec.items() if k not in _VOLATILE_KEYS}
        for key, id_field in _KEYED_LISTS.items():
            val = out.get(key)
            if isinstance(val, list):
                out[key] = sorted(
                    val,
                    key=lambda item: (item.get(id_field, "") if isinstance(item, dict) else str(item)),
                )
        return out

    # ----- discovery / recall ------------------------------------------------
    def list_jobs(self) -> list[JobRef]:
        data = self._cli_json("jobs", "list")
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        out: list[JobRef] = []
        for j in jobs or []:
            settings = j.get("settings", j)
            sched = (settings.get("schedule") or {}).get("quartz_cron_expression")
            paused = (settings.get("schedule") or {}).get("pause_status")
            out.append(
                JobRef(
                    job_id=str(j.get("job_id", "")),
                    name=settings.get("name", ""),
                    paused=(paused == "PAUSED") if paused else None,
                    schedule=sched,
                )
            )
        return out

    def get_job_definition(self, ref: str) -> JobDefinition:
        f = self._find_repo_def_file(ref)
        if not f:
            raise FileNotFoundError(
                f"no repo job definition found for {ref!r} in {[str(d) for d in self._job_def_dirs()]}"
            )
        spec = json.loads(f.read_text())
        return JobDefinition(name=spec.get("name", ref), spec=spec, source="repo")

    # ----- drift / deploy-safety --------------------------------------------
    def _resolve_job_id(self, ref: str) -> str:
        if ref.isdigit():
            return ref
        # ref may be a ticket/folder; map via repo def name, then match the live list.
        name = ref
        f = self._find_repo_def_file(ref)
        if f:
            with contextlib.suppress(OSError, json.JSONDecodeError):
                name = (json.loads(f.read_text()) or {}).get("name", ref)
        matches = [jr.job_id for jr in self.list_jobs() if jr.name == name]
        if len(matches) > 1:
            raise LookupError(
                f"multiple live Databricks jobs named {name!r} ({matches}); pass an explicit job_id to disambiguate."
            )
        if matches:
            return matches[0]
        raise LookupError(f"no live Databricks job named {name!r} (resolved from {ref!r})")

    def get_live_definition(self, ref: str) -> JobDefinition:
        job_id = self._resolve_job_id(ref)
        data = self._cli_json("jobs", "get", job_id)
        settings = data.get("settings", data)
        return JobDefinition(name=settings.get("name", ref), spec=data, source="live")

    def diff_live_vs_repo(self, ref: str, repo_path: str | None = None) -> DiffResult:
        if repo_path:
            repo_spec = json.loads(Path(repo_path).read_text())
        else:
            repo_spec = self.get_job_definition(ref).spec
        live_spec = self.get_live_definition(ref).spec

        repo = _flatten(self._normalize(repo_spec))
        live = _flatten(self._normalize(live_spec))
        repo_keys, live_keys = set(repo), set(live)
        added = tuple(sorted(live_keys - repo_keys))     # live has it, repo doesn't
        removed = tuple(sorted(repo_keys - live_keys))   # repo has it, live doesn't
        changed = tuple(sorted(k for k in (repo_keys & live_keys) if repo[k] != live[k]))
        detail = {
            **{k: {"live": live[k], "repo": "<absent>"} for k in added},
            **{k: {"live": "<absent>", "repo": repo[k]} for k in removed},
            **{k: {"live": live[k], "repo": repo[k]} for k in changed},
        }
        return DiffResult(
            drift=bool(added or removed or changed),
            added=added,
            removed=removed,
            changed=changed,
            detail=detail,
        )

    def list_active_runs(self, ref: str) -> list[ActiveRun]:
        job_id = self._resolve_job_id(ref)
        data = self._cli_json("jobs", "list-runs", "--job-id", job_id, "--active-only")
        runs = data.get("runs", data) if isinstance(data, dict) else data
        out: list[ActiveRun] = []
        for r in runs or []:
            state = (r.get("state") or {}).get("life_cycle_state", "UNKNOWN")
            out.append(ActiveRun(run_id=str(r.get("run_id", "")), state=state, started=str(r.get("start_time", ""))))
        return out

    def deploy(self, def_path: str, env: str, ref: str | None = None) -> dict:
        # Deploy is intentionally not a blind one-shot here. The safe-deploy skill
        # drives the guarded flow (diff -> confirm -> reset/update); the guard hook
        # backstops any raw `databricks jobs reset`.
        raise ManualFallback(
            "Use the /safe-deploy skill (or run `jobwright diff-job` then a confirmed "
            "`databricks jobs reset`). Direct programmatic deploy is withheld so a stale-JSON "
            "reset can never happen unattended."
        )

    # ----- execution / operate ----------------------------------------------
    def trigger_run(self, ref: str, params: dict | None = None, env: str = "prod") -> str:
        active = self.list_active_runs(ref)
        if active:
            raise RuntimeError(
                f"{len(active)} run(s) already active for {ref!r} ({[a.run_id for a in active]}); "
                "not triggering to avoid a duplicate. Wait or cancel first."
            )
        job_id = self._resolve_job_id(ref)
        args = ["jobs", "run-now", job_id]
        if params:
            args += ["--json", json.dumps({"job_parameters": params})]
        data = self._cli_json(*args)
        return str(data.get("run_id", ""))

    def get_run(self, run_id: str) -> RunInfo:
        data = self._cli_json("jobs", "get-run", run_id)
        state = data.get("state") or {}
        return RunInfo(
            run_id=run_id,
            state=state.get("life_cycle_state", "UNKNOWN"),
            result_state=state.get("result_state"),
            tasks=tuple(data.get("tasks", []) or ()),
        )

    def get_run_output(self, run_id: str, task: str | None = None) -> RunOutput:
        data = self._cli_json("jobs", "get-run-output", run_id)
        text = data.get("logs") or data.get("error") or json.dumps(data)[:4000]
        return RunOutput(text=text, truncated=bool(data.get("logs_truncated")))


def _flatten(d: dict, prefix: str = "") -> dict[str, str]:
    """Flatten a nested dict to dotted paths -> JSON-serialized scalar/list values.

    Lists are compared as whole values (stable JSON) rather than per-element, which
    keeps the diff readable without false churn from reordering within scalars.
    """
    out: dict[str, str] = {}
    for k, v in d.items():
        path = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(_flatten(v, path))
        else:
            out[path] = json.dumps(v, sort_keys=True, default=str)
    return out
