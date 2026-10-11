"""The explanatory layer, held in place: what a person reads while jobwright works.

Skills narrate (they link the shared narration rules), define their terms (they link the
plain-language concepts page, and every term it promises is there), stay short, and carry no
internal history. The job doc's resume log names the next command. `init` explains each question
before asking it. Prose rules drift silently unless a test reads the prose.
"""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from jobwright.tools.job_doc_lint import log_problem

REPO = Path(__file__).resolve().parents[1]
SKILLS = sorted((REPO / "skills").glob("*/SKILL.md"))
CONCEPTS = REPO / "docs" / "concepts.md"
BODY_CAP = 80  # a SKILL.md is a contract; depth lives in sibling files

# every term the skills, the Setup report or doctor lean on must be defined for a person
GLOSSARY = [
    "Front door",
    "Job folder",
    "Job doc",
    "Catalog",
    "Recall",
    "Validation gate",
    "Live vs repo (drift)",
    "Deploy model",
    "Adapter",
    "Deploy-safety guard",
    "Layer and layer violation",
    "Migration debt",
    "Documentation debt",
    "Doctor: OK, DEGRADED, ERROR",
]


def _body(text: str) -> list[str]:
    parts = text.split("---", 2)
    return parts[2].strip("\n").splitlines() if text.startswith("---") and len(parts) == 3 else text.splitlines()


def test_every_skill_links_the_narration_rules_and_the_concepts_page():
    assert SKILLS, "no skills found"
    for f in SKILLS:
        text = f.read_text()
        assert "](../_shared/narrate.md)" in text, f"{f.parent.name}: no link to the narration rules"
        assert "](../../docs/concepts.md)" in text, f"{f.parent.name}: no link to docs/concepts.md"


def test_every_skill_body_stays_under_the_cap():
    over = {f.parent.name: n for f in SKILLS if (n := len(_body(f.read_text()))) > BODY_CAP}
    assert not over, f"SKILL.md body over {BODY_CAP} lines (move depth to a sibling file): {over}"


def test_no_internal_history_in_user_facing_skill_text():
    # "formerly /x" and "ported from y" are maintainer history; the CHANGELOG keeps it
    leaks = [
        f"{p.relative_to(REPO)}: {m.group(0)!r}"
        for p in (REPO / "skills").rglob("*.md")
        for m in re.finditer(r"\b(formerly|ported from)\b[^.\n]*", p.read_text(), re.IGNORECASE)
    ]
    assert not leaks, leaks


def test_every_relative_link_in_skills_and_concepts_resolves():
    broken = []
    for p in [*(REPO / "skills").rglob("*.md"), CONCEPTS]:
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", p.read_text()):
            if "://" in target:
                continue
            if not (p.parent / target).resolve().exists():
                broken.append(f"{p.relative_to(REPO)} -> {target}")
    assert not broken, broken


def test_concepts_page_defines_every_glossary_term():
    headings = set(re.findall(r"^###\s+(.+?)\s*$", CONCEPTS.read_text(), re.MULTILINE))
    missing = [t for t in GLOSSARY if not any(h.startswith(t) for h in headings)]
    assert not missing, f"docs/concepts.md has no entry for: {missing}"


# --------------------------------------------------------------------------- #
# the resume log in a job doc
# --------------------------------------------------------------------------- #
def test_log_rule_passes_docs_without_a_log_or_with_an_empty_one():
    assert log_problem("# Job: JOB-1 X\n**Purpose**: y\n") is None
    template = (REPO / "jobwright" / "_templates" / "job" / "claude.md.j2").read_text()
    assert "## Log" in template
    assert log_problem(template) is None  # the example line lives in a comment


def test_log_rule_requires_the_last_entry_to_name_the_next_command():
    good = "## Log\n- 2026-10-01: planned (/start-job). Next: /safe-deploy JOB-1\n"
    assert log_problem(good) is None
    no_next = good + "- 2026-10-02: fixed the join (/triage-failure)\n"
    assert "Next:" in (log_problem(no_next) or "")
    not_a_command = good + "- 2026-10-02: fixed the join (/triage-failure). Next: TBD\n"
    assert log_problem(not_a_command)
    # a command quoted in the description is not the handoff
    quoted = "## Log\n- 2026-10-11: dropped the Next: /safe-deploy note (/start-job). Next: TBD\n"
    assert log_problem(quoted)


def test_log_rule_never_reddens_what_jobwright_did_not_write():
    good = "## Log\n- 2026-10-01: planned (/start-job). Next: /safe-deploy JOB-1\n"
    # a later section, a sub-bullet, a subsection and a code fence are not log entries
    assert log_problem(good + "\n## Notes\n- unrelated bullet\n") is None
    assert log_problem(good + "  - a sub-bullet note\n") is None
    assert log_problem(good + "### Older\n- 2025-01-01: old (/start-job)\n") is None
    assert log_problem(good + "```\n- 2026-10-03: example (/start-job)\n```\n") is None
    # a team's own hand-written Log, from before jobwright, stays green
    assert log_problem("## Log\n- moved to the new cluster\n- added retries\n") is None
    assert log_problem(good.replace("\n", "\r\n")) is None
    # a Log shown only as an example, in a fence or a comment, is not the job's Log
    example = "## Log\n- 2026-10-01: x (/start-job)\n"
    assert log_problem(f"```\n{example}```\n") is None
    assert log_problem(f"<!--\n{example}-->\n") is None
    assert log_problem(f"```\n{example}```\n\n{good}") is None


# --------------------------------------------------------------------------- #
# init explains each question before asking it
# --------------------------------------------------------------------------- #
def test_init_explains_every_question_and_where_its_default_came_from(tmp_path, monkeypatch):
    from jobwright import cli as cli_mod

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_mod, "_stdin_is_tty", lambda: True)
    # a git-synced platform: the profile question is skipped, so four questions are asked
    result = CliRunner().invoke(cli_mod.app, ["init"], input="dbt\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert result.output.count("offered:") == 4, result.output
    assert "never used to connect" in result.output  # the warehouse answer's scope is honest
