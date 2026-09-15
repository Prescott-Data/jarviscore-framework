"""Import hygiene: a library must not write to stdout when imported."""

import subprocess
import sys


def test_importing_jarviscore_prints_nothing():
    proc = subprocess.run(
        [sys.executable, "-c", "import jarviscore"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", f"import jarviscore wrote to stdout: {proc.stdout!r}"


def test_base_import_does_not_require_optional_redis_package():
    script = """
import builtins
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == 'redis' or name.startswith('redis.'):
        raise ModuleNotFoundError('redis intentionally unavailable')
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
import jarviscore
from jarviscore import SourceAdapter
from jarviscore.storage import BlobStorage
assert SourceAdapter is not None
assert BlobStorage is not None
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr


def test_p2p_lazy_exports_still_resolve():
    from jarviscore.p2p import PeerClient  # eager, swim-free

    assert PeerClient.__name__ == "PeerClient"

    import jarviscore.p2p as p2p

    coordinator = p2p.P2PCoordinator  # lazy, loads swim on first touch
    manager = p2p.SWIMThreadManager
    assert coordinator.__name__ == "P2PCoordinator"
    assert manager.__name__ == "SWIMThreadManager"


def test_p2p_unknown_attribute_raises():
    import pytest

    import jarviscore.p2p as p2p

    with pytest.raises(AttributeError):
        p2p.DoesNotExist
