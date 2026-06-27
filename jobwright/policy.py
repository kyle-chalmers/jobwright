"""ArchitecturePolicy — the warehouse-schema rules, built from the ``architecture``
config block and consumed by the ``schema_compliance`` check.

This is jobwright's analog of streamsnow's ``SchemaPolicy``, generalized from a
flat allow/deny list to two rule kinds:

* **deprecated-schema denylist** — references to a schema being migrated away from
  (e.g. ``DATA_STORE`` / ``CRON_STORE``) are flagged as migration debt, with an
  optional replacement hint.
* **layer-referencing rules** — a job declaring a ``# LAYER:`` may only reference
  the schemas its layer is allowed to (forbid upstream refs). Jobs that don't
  declare a layer skip this check (best-effort, never a false positive).

Pure policy: no database connection, stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Qualified SQL object refs. Keyword-anchored for precision: matches
# `FROM schema.obj` / `JOIN db.schema.obj` even inside a SQL string in a .py file,
# but not `os.path.join` / `df.merge` (no FROM/JOIN/... keyword precedes them).
# Identifier parts may be bare, "double-quoted" (Snowflake/ANSI), or `backticked`
# (BigQuery); quotes are stripped before evaluation.
SQL_OBJECT = re.compile(
    r'(?i)\b(?:from|join|into|update|merge\s+into|delete\s+from|table|view)\s+'
    r'([`"]?[A-Za-z_]\w*[`"]?(?:\.[`"]?[A-Za-z_]\w*[`"]?){1,2})'
)
PY_IMPORT = re.compile(r"^\s*(?:from\s+\S+\s+import\b|import\s)")


def _strip_quotes(ref: str) -> str:
    return ref.replace("`", "").replace('"', "")
LAYER_DECL = re.compile(r"^\s*#\s*LAYER\s*[:=]\s*([A-Za-z_][A-Za-z0-9_$]*)", re.MULTILINE)


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    ref: str           # the qualified reference as written
    schema: str        # the offending schema part (upper-cased)
    kind: str          # "deprecated" | "layer-violation"
    message: str

    def as_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "ref": self.ref,
            "schema": self.schema,
            "kind": self.kind,
            "message": self.message,
        }


class ArchitecturePolicy:
    def __init__(
        self,
        deprecated_deny=(),
        read_exceptions=(),
        replace_hints=None,
        layer_rules=None,
    ) -> None:
        self.deny = {s.upper() for s in deprecated_deny}
        self.read_exceptions = {s.upper() for s in read_exceptions}
        self.replace_hints = {k.upper(): v for k, v in (replace_hints or {}).items()}
        self.layer_rules = {k.upper(): {x.upper() for x in v} for k, v in (layer_rules or {}).items()}

    @classmethod
    def from_config(cls, cfg) -> ArchitecturePolicy:
        a = cfg.architecture
        return cls(a.deprecated_schema_deny, a.read_exceptions, a.replace_hints, a.layer_rules)

    def _hint(self, ref: str, schema: str) -> str:
        return self.replace_hints.get(ref.upper()) or self.replace_hints.get(schema) or ""

    def scan_text(self, text: str, filename: str) -> list[Finding]:
        findings: list[Finding] = []
        layer_m = LAYER_DECL.search(text)
        layer = layer_m.group(1).upper() if layer_m else None
        allowed = self.layer_rules.get(layer) if layer else None

        for lineno, line in enumerate(text.splitlines(), start=1):
            if PY_IMPORT.match(line):
                continue
            for raw_ref in SQL_OBJECT.findall(line):
                ref = _strip_quotes(raw_ref)
                if ref.upper() in self.read_exceptions:
                    continue
                parts = [p.upper() for p in ref.split(".")]
                # deprecated-schema: any part of the ref is on the denylist
                deprecated = next((p for p in parts if p in self.deny), None)
                if deprecated:
                    hint = self._hint(ref, deprecated)
                    msg = f"references deprecated schema {deprecated}" + (f" — migrate to {hint}" if hint else "")
                    findings.append(Finding(filename, lineno, ref, deprecated, "deprecated", msg))
                    continue
                # layer-referencing: only when the job declares its layer
                if allowed is not None and len(parts) >= 2:
                    schema = parts[-2]  # schema part of schema.obj or db.schema.obj
                    if schema != layer and schema not in allowed:
                        findings.append(Finding(
                            filename, lineno, ref, schema, "layer-violation",
                            f"layer {layer} may not reference {schema} (allowed: {sorted(allowed) or 'none'})",
                        ))
        return findings
