"""Opt-in, single-owner native AutoAgent execution resources.

Trusted callers own paths, stores and cleanup. This is not an authority grant.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


async def finish_cleanup(awaitable):
    """Cancellation waits for owned cleanup before it crosses the boundary."""
    task = asyncio.ensure_future(awaitable)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    try:
        result = task.result()
    finally:
        if cancelled:
            raise asyncio.CancelledError
    return result


@dataclass
class AutoAgentRunResources:
    workspace_dir: Path
    log_directory: Path
    nexus_call_proxy: Any = None
    blob_storage: Any = None
    redis_store: Any = None
    artifact_prefix: str = "artifacts"
    config_overrides: Mapping[str, Any] = field(default_factory=dict)
    cleanup: Callable[[], Awaitable[None]] | None = None
    _owner: Any = field(default=None, init=False, repr=False)
    _close_task: Any = field(default=None, init=False, repr=False)

    def __post_init__(self):
        self.workspace_dir = Path(self.workspace_dir).absolute()
        self.log_directory = Path(self.log_directory).absolute()
        if (
            self.workspace_dir == self.log_directory
            or self.log_directory.is_relative_to(self.workspace_dir)
            or self.workspace_dir.is_relative_to(self.log_directory)
        ):
            raise ValueError("Workspace and runtime logs must be separate")
        self.config_overrides = deepcopy(dict(self.config_overrides))

    def claim(self, owner):
        if self._owner is not None or self._close_task is not None:
            raise RuntimeError("Run resources already belong to an agent lifetime")
        self._owner = owner

    def config(self, base):
        return {**base, **self.config_overrides, "log_directory": str(self.log_directory)}

    async def _close(self):
        try:
            close = getattr(self.nexus_call_proxy, "aclose", None)
            if close is not None:
                await close()
        finally:
            if self.cleanup is not None:
                await self.cleanup()

    async def aclose(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await finish_cleanup(self._close_task)


_private_log_handler = ContextVar("autoagent_private_log_handler", default=None)
_log_factory_lock = threading.Lock()
_log_factory_installed = False


@contextmanager
def using_private_logs(handler: logging.Handler):
    """Keep native message/exception bodies in a trusted task-local log sink.

    Native log extras contain only role/turn routing metadata. Callers must not
    attach source data using arbitrary logging ``extra`` fields.
    """
    if not isinstance(handler, logging.Handler):
        raise TypeError("A trusted private logging handler is required")
    global _log_factory_installed
    with _log_factory_lock:
        if not _log_factory_installed:
            previous_factory = logging.getLogRecordFactory()

            def factory(*args, **kwargs):
                record = previous_factory(*args, **kwargs)
                sink = _private_log_handler.get()
                if sink is None:
                    return record
                sink.handle(record)
                return logging.LogRecord(
                    record.name,
                    record.levelno,
                    record.pathname,
                    record.lineno,
                    "Private execution log retained",
                    (),
                    None,
                    record.funcName,
                )

            logging.setLogRecordFactory(factory)
            _log_factory_installed = True
    token = _private_log_handler.set(handler)
    try:
        yield handler
    finally:
        _private_log_handler.reset(token)
