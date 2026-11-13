"""Credential-free original-byte decoding and descriptor-anchored artifact writes."""
from __future__ import annotations

import base64
import os
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024


def byte_limit(value):
    if type(value) is not int or not 0 < value <= MAX_BYTES:
        raise ValueError("Invalid original byte bound")
    return value


def original_bytes(response, max_bytes):
    byte_limit(max_bytes)
    if (not isinstance(response, dict) or response.get("ok", True) is not True
            or type(response.get("status_code")) is not int
            or not 200 <= response["status_code"] < 300):
        raise ValueError("Original download failed")
    content = response.get("content")
    if isinstance(content, dict):
        if set(content) != {"__bytes__"} or not isinstance(content["__bytes__"], str):
            raise ValueError("Invalid native byte envelope")
        if len(content["__bytes__"]) > 4 * ((max_bytes + 2) // 3):
            raise ValueError("Original exceeds byte bound")
        content = base64.b64decode(content["__bytes__"], validate=True)
    if not isinstance(content, bytes) or len(content) > max_bytes:
        raise ValueError("Invalid original bytes")
    return content


def destination(path, output_dir=None, *, relative_only=True):
    """Validate before any download; never create paths or follow provider filenames."""
    if (not isinstance(path, str) or not path or "\\" in path or ":" in path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)):
        raise ValueError("Invalid original destination")
    absolute = path.startswith("/")
    if absolute and relative_only:
        raise ValueError("Original destination must be relative")
    parts = path.split("/")[1:] if absolute else path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Invalid original destination")
    if output_dir is not None:
        root = Path(output_dir)
        if absolute:
            parts = list(Path(path).relative_to(root).parts)
            if not parts:
                raise ValueError("Original destination must name a file")
    elif relative_only:
        raise ValueError("Original destination needs a native output directory")
    else:
        root = Path("/") if absolute else Path.cwd()
    return root, parts


def write_original(content, selected_destination):
    """Exclusive no-follow writes; a failed write removes only its own partial file."""
    root, parts = selected_destination
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    file_fd = None
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=directory)
            except FileExistsError:
                pass
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        file_fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600, dir_fd=directory)
        try:
            view = memoryview(content)
            while view:
                written = os.write(file_fd, view)
                if written <= 0:
                    raise OSError("Original write failed")
                view = view[written:]
        except BaseException:
            created = os.fstat(file_fd)
            current = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
            if (created.st_dev, created.st_ino) == (current.st_dev, current.st_ino):
                os.unlink(parts[-1], dir_fd=directory)
            raise
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory)


def identifier(value):
    from urllib.parse import quote

    if (not isinstance(value, str) or not value or value in (".", "..")
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("Invalid source identifier")
    return quote(value, safe="")
