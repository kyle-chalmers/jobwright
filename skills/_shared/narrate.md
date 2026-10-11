# Talk to the user while you work

The person running a jobwright skill may be new to the repo, to the orchestrator, or to
jobwright itself. They trust what they can follow, so say plainly what you are about to do and
why. Every skill follows these rules.

- **Open each phase with one line**: what it does, and whether it will ask anything.
  ("Recall: reading the catalog for prior work on these tables. Nothing is written, no
  questions.")
- **Before each action, one line of what and why. After it, one line with the result.**
  Read-only actions that need no approval are narrated too: a silent check reads as a skipped
  check.
- **Define a jobwright term the first time you use it**, in a few plain words, then use it
  freely. [docs/concepts.md](../../docs/concepts.md) has the short definitions; borrow them
  rather than inventing new ones.
- **Every question says what it decides and what each answer changes.** A detected value is
  offered as the recommended answer, with where it came from.
- **Report results as counts and the next move, not as raw output.** "Validation: 4 of 5
  checks pass; documentation is missing Business Owner" beats pasting the table. Show the raw
  output when the user asks or when a step failed and the detail is the fix.
- **Close each phase with what got done and what is next.** The last thing a skill says is its
  `## Next` command.
- **Plain words, no walls of text.** One line per step is the default; a failure or a decision
  earns more.
