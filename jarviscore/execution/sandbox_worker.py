"""Child runtime for generated code. No provider credential exists in this process."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import json
import os
import socket
import sys
from pathlib import Path

from jarviscore.execution.coder_sandbox import BashExecutor, GitHelper


def _jsonable(value):
    if isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class ParentRPC:
    def __init__(self, fd: int):
        self.socket = socket.socket(fileno=fd)
        self.stream = self.socket.makefile("rwb", buffering=0)
        self.next_id = 0

    def call(self, operation: str, payload: dict):
        self.next_id += 1
        message = {"id": self.next_id, "operation": operation, "payload": payload}
        self.stream.write((json.dumps(message) + "\n").encode())
        response = json.loads(self.stream.readline())
        if response.get("error"):
            error_type = response.get("error_type", "RuntimeError")
            if error_type == "StrategyError":
                from jarviscore.nexus.strategy import StrategyError
                raise StrategyError(response["error"])
            if error_type == "HostNotAllowed":
                from jarviscore.nexus.hosts import HostNotAllowed
                raise HostNotAllowed(response["error"])
            raise RuntimeError(response["error"])
        return response.get("result")


async def execute(request: dict) -> dict:
    workspace = Path(request["workspace"]).resolve()
    output_dir = Path(request["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rpc = ParentRPC(int(request["rpc_fd"]))
    bash = BashExecutor(workspace, timeout=int(request.get("bash_timeout", 120)))
    git = GitHelper(bash, workspace)

    def blob_path(filename: str) -> Path:
        path = (output_dir / filename).resolve()
        if output_dir not in path.parents and path != output_dir:
            raise ValueError("Artifact path leaves the output directory.")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def nexus_call(method: str, url: str, provider: str | None = None, **kwargs):
        return await asyncio.to_thread(
            rpc.call, "nexus_call", {
                "method": method, "url": url, "provider": provider,
                "kwargs": _jsonable(kwargs),
            }
        )

    async def fetch_artifact(key: str) -> Path:
        result = await asyncio.to_thread(rpc.call, "fetch_artifact", {"key": key})
        path = blob_path(key.rsplit("/", 1)[-1])
        path.write_bytes(base64.b64decode(result["content"]))
        return path

    import datetime
    import hashlib
    import math
    import pathlib
    import re
    import shutil
    import tempfile
    import textwrap
    import uuid

    namespace = {
        "__builtins__": __builtins__, "result": None,
        "workspace": workspace, "output_dir": output_dir,
        "blob_path": blob_path, "fetch_artifact": fetch_artifact,
        "bash": bash, "git": git, "nexus_call": nexus_call,
        "Path": pathlib.Path, "json": json, "re": re, "datetime": datetime,
        "math": math, "hashlib": hashlib, "uuid": uuid, "shutil": shutil,
        "tempfile": tempfile, "textwrap": textwrap,
    }
    for key, value in (request.get("context") or {}).items():
        if not key.startswith("_"):
            namespace[key] = value

    stdout = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout):
            exec(request["code"], namespace)  # noqa: S102
            entry = namespace.get("main") or namespace.get("run")
            if callable(entry):
                returned = entry()
                if hasattr(returned, "__await__"):
                    returned = await returned
                if returned is not None:
                    namespace["result"] = returned
        return {"result": _jsonable(namespace.get("result")), "stdout": stdout.getvalue()}
    except Exception as exc:
        return {"error": str(exc), "error_type": type(exc).__name__, "stdout": stdout.getvalue()}


def main() -> int:
    request = json.loads(sys.stdin.read())
    response = asyncio.run(execute(request))
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
