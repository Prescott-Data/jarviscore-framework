"""Best-effort metadata for persistent JarvisCore browser profiles."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

_METADATA = ".jarviscore-profile.json"


def decorate_profile(
    user_data_dir: str | os.PathLike[str],
    profile_name: str | None = None,
    profile_color: str | None = None,
) -> None:
    """Persist profile display metadata without changing Chromium preferences."""
    directory = Path(user_data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / _METADATA
    metadata: dict = {}
    if target.is_file():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                metadata = loaded
        except (OSError, json.JSONDecodeError):
            metadata = {}
    if profile_name:
        metadata["name"] = profile_name
    if profile_color:
        metadata["color"] = profile_color
    if not metadata:
        return
    descriptor, temporary = tempfile.mkstemp(prefix=f"{_METADATA}.", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
