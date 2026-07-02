"""jobwright — an AI layer for governing data-orchestration jobs.

Intentionally import-light: this module is imported by the stdlib-only
``deploy_safety`` hook to resolve a platform's destructive-command patterns, so
it must not pull in ``yaml`` / ``typer`` / other heavy deps at import time.
"""

__version__ = "0.1.0"
