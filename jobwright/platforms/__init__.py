"""Platform adapter registry.

Maps ``platform.kind`` -> adapter class. Kept import-light (stdlib only) so the
``deploy_safety`` hook can ``from jobwright.platforms import destructive_patterns_for``
to resolve a platform's guarded-command patterns without importing ``yaml``/``typer``.

Adding a platform = drop a module under ``jobwright/platforms/`` with a
``JobPlatformAdapter`` subclass and register it here.
"""

from __future__ import annotations

from .airflow import AirflowAdapter
from .base import JobPlatformAdapter, ManualFallback  # noqa: F401  (re-exported)
from .databricks import DatabricksAdapter
from .dbt import DbtAdapter
from .snowflake_tasks import SnowflakeTasksAdapter

_REGISTRY: dict[str, type[JobPlatformAdapter]] = {}


def register(adapter_cls: type[JobPlatformAdapter]) -> type[JobPlatformAdapter]:
    if not adapter_cls.kind:
        raise ValueError(f"{adapter_cls.__name__} must set a non-empty `kind`")
    _REGISTRY[adapter_cls.kind] = adapter_cls
    return adapter_cls


register(DatabricksAdapter)
register(AirflowAdapter)
register(SnowflakeTasksAdapter)
register(DbtAdapter)


def adapter_kinds() -> list[str]:
    return sorted(_REGISTRY)


def get_adapter_class(kind: str) -> type[JobPlatformAdapter]:
    try:
        return _REGISTRY[kind]
    except KeyError:
        raise KeyError(
            f"no jobwright adapter registered for platform '{kind}'. "
            f"Available: {adapter_kinds()}."
        ) from None


def get_adapter(kind: str, profile: str = "", config=None) -> JobPlatformAdapter:
    return get_adapter_class(kind)(profile=profile, config=config)


def destructive_patterns_for(kind: str) -> list[dict[str, str]]:
    """The guarded-command patterns a platform declares. Returns [] for an unknown
    kind so the hook can fall back to its built-in defaults (fail-open)."""
    cls = _REGISTRY.get(kind)
    return list(cls.destructive_patterns) if cls else []
