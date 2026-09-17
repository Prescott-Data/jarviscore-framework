"""Shared deadline configuration for the two public InternetSearch clients."""

import math
import os


def search_deadline(value: float | None, env_name: str, default: float) -> float:
    """Resolve constructor override before environment; reject unbounded waits."""
    raw = value if value is not None else os.environ.get(env_name, default)
    try:
        resolved = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{env_name} must be a positive finite number of seconds") from None
    if isinstance(raw, bool) or not math.isfinite(resolved) or resolved <= 0:
        raise ValueError(f"{env_name} must be a positive finite number of seconds")
    return resolved