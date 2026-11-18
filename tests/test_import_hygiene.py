"""Import hygiene: a library must not write to stdout when imported."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "statement",
    [
        "from jarviscore.search.internet_search import InternetSearch",
        "from jarviscore.search import InternetSearch",
    ],
)
def test_search_imports_first_in_a_fresh_process(statement):
    script = f"""
import sys
{statement}
assert InternetSearch.__module__ == "jarviscore.search.internet_search"
assert "jarviscore.core.mesh" not in sys.modules
assert "jarviscore.kernel.defaults.researcher" not in sys.modules
from jarviscore.kernel.defaults import ResearcherSubAgent
from jarviscore.core import Mesh, MeshMode
assert ResearcherSubAgent.__name__ == "ResearcherSubAgent"
assert Mesh.__name__ == "Mesh"
assert MeshMode.__name__ == "MeshMode"
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


def test_core_helpers_do_not_eagerly_import_mesh_and_public_exports_still_work():
    script = """
import sys
import jarviscore.core as core
from jarviscore.core.egress import Egress
from jarviscore.core.search_deadlines import search_deadline
assert "jarviscore.core.mesh" not in sys.modules
assert "jarviscore.kernel.defaults.researcher" not in sys.modules
assert set(core.__all__) <= set(dir(core))
assert issubclass(core.Profile, core.Agent)
from jarviscore.core import Mesh, MeshMode
from jarviscore import Mesh as PublicMesh, MeshMode as PublicMeshMode
assert Mesh is PublicMesh is core.Mesh
assert MeshMode is PublicMeshMode is core.MeshMode
try:
    core.DoesNotExist
except AttributeError:
    pass
else:
    raise AssertionError("Unknown core attribute did not raise AttributeError")
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


def test_importing_jarviscore_prints_nothing():
    proc = subprocess.run(
        [sys.executable, "-c", "import jarviscore"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", f"import jarviscore wrote to stdout: {proc.stdout!r}"


def test_decision_model_types_are_public_without_optional_sdk_installed():
    from jarviscore import DecisionResult, JevDecisionClient

    assert DecisionResult.__name__ == "DecisionResult"
    assert JevDecisionClient.__name__ == "JevDecisionClient"


def test_rag_pipeline_module_imports_without_optional_dependencies():
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                'import sys; sys.modules["numpy"] = None; '
                'sys.modules["faiss"] = None; '
                "from jarviscore.rag.pipeline import RagPipeline; "
                'assert RagPipeline.__name__ == "RagPipeline"'
            ),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


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
