"""Generic, platform-agnostic checks — each operates on repo files only (no platform
calls) and is importable plus runnable. Every check exposes ``main(argv) -> int`` with
exit codes 0 (clean) / 1 (findings) / 2 (error), so the CLI, the composite
``validate_job`` gate, and CI all call the same code (the streamsnow "one
implementation, many consumers" rule)."""
