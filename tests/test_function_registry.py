"""
Tests for Phase 5: Graduated Function Registry

What these tests prove:
- FunctionStatus enum has correct graduation levels (candidate → verified → golden)
- Functions are registered with atom versioning and metadata persistence
- Graduation auto-promotes based on execution success count (1→verified, 5→golden)
- Atom files are immutable, versioned, and integrity-checked via SHA256
- Multi-index search works by system, capability, and status
- System bundles generate {System}Capabilities classes from verified/golden functions
- Dependency graphs support topological sorting with cycle detection
- Redis cognitive projection syncs compact index for shared discovery
- Blob storage sync uploads atoms and metadata for distributed persistence
- Semantic search finds functions across metadata fields

WHY THIS MATTERS FOR THE FRAMEWORK:
The kernel (Phase 6) checks the registry for reusable functions before
generating new code. Without graduated registry:
- No way to distinguish untested code from battle-tested functions
- No system bundles for injecting capabilities into sandbox
- No shared discovery via Redis for multi-agent reuse
- No immutable versioning for audit trail
- No dependency ordering for complex function chains
"""

import json
import hashlib
from pathlib import Path

import pytest

from jarviscore.execution.code_registry import (
    FunctionRegistry,
    FunctionStatus,
    CodeRegistry,
    create_function_registry,
    create_code_registry,
)
from jarviscore.testing import MockRedisContextStore
from jarviscore.testing.mocks import MockBlobStorage


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────

@pytest.fixture
def registry(tmp_path):
    """Fresh FunctionRegistry using tmp_path for storage."""
    return FunctionRegistry(storage_path=str(tmp_path / "registry"))


@pytest.fixture
def registry_with_redis(tmp_path):
    """FunctionRegistry with Redis cognitive projection."""
    store = MockRedisContextStore()
    return FunctionRegistry(
        storage_path=str(tmp_path / "registry"),
        redis_store=store,
    ), store


@pytest.fixture
def registry_with_blob(tmp_path):
    """FunctionRegistry with blob storage sync."""
    blob = MockBlobStorage()
    return FunctionRegistry(
        storage_path=str(tmp_path / "registry"),
        blob_storage=blob,
    ), blob


SAMPLE_CODE = "def get_products():\n    return [1, 2, 3]\n"
SAMPLE_METADATA = {
    "system": "shopify",
    "capabilities": ["product_lookup", "inventory"],
    "description": "Fetch product list from Shopify API",
    "tags": ["api", "shopify"],
    "type": "api",
}


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 1: FunctionStatus Enum
# ═════════════════════════════════════════════════════════════════

class TestFunctionStatus:
    """FunctionStatus enum defines the graduation stages."""

    def test_status_values(self):
        """Enum values match IA/CA graduation model."""
        assert FunctionStatus.CANDIDATE.value == "candidate"
        assert FunctionStatus.VERIFIED.value == "verified"
        assert FunctionStatus.GOLDEN.value == "golden"

    def test_status_is_string(self):
        """FunctionStatus is a string enum — usable as dict key and JSON value."""
        d = {FunctionStatus.CANDIDATE: "test"}
        assert d["candidate"] == "test"
        assert json.dumps({"stage": FunctionStatus.GOLDEN}) == '{"stage": "golden"}'

    def test_all_statuses_exist(self):
        """All three graduation stages are defined."""
        statuses = [s.value for s in FunctionStatus]
        assert "candidate" in statuses
        assert "verified" in statuses
        assert "golden" in statuses
        assert len(statuses) == 3


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 2: Registration
# ═════════════════════════════════════════════════════════════════

class TestRegistration:
    """Function registration stores code as atoms with metadata."""

    def test_register_function_returns_true(self, registry):
        """Successful registration returns True."""
        result = registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)
        assert result is True

    def test_register_stores_atom_file(self, registry):
        """Code is stored as an immutable atom file."""
        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)

        metadata = registry.get_function_metadata("get_products")
        atom_path = Path(metadata["atom_path"])
        assert atom_path.exists()
        assert atom_path.read_text() == SAMPLE_CODE
        assert "_v1.py" in str(atom_path)

    def test_register_stores_metadata_json(self, registry):
        """Metadata JSON is saved with all required fields."""
        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)

        meta_file = registry.metadata_path / "get_products.json"
        assert meta_file.exists()

        with open(meta_file) as f:
            saved = json.load(f)

        assert saved["function_name"] == "get_products"
        assert saved["system"] == "shopify"
        assert saved["capabilities"] == ["product_lookup", "inventory"]
        assert saved["version"] == 1
        assert saved["atom_hash"]  # SHA256 hash present
        assert saved["created_at"]
        assert saved["updated_at"]
        assert saved["type"] == "api"

    def test_register_initial_status_is_candidate(self, registry):
        """New functions start as CANDIDATE with zero success count."""
        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)

        metadata = registry.get_function_metadata("get_products")
        assert metadata["registry_stage"] == "candidate"
        assert metadata["success_count"] == 0
        assert metadata["execution_count"] == 0
        assert metadata["failure_count"] == 0


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 3: Graduation
# ═════════════════════════════════════════════════════════════════

class TestGraduation:
    """Auto-promotion based on execution success count."""

    def test_update_execution_stats_increments_count(self, registry):
        """success_count and execution_count go up."""
        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)
        registry.update_execution_stats("get_products", success=True, execution_time=1.0)

        metadata = registry.get_function_metadata("get_products")
        assert metadata["execution_count"] == 1
        assert metadata["success_count"] == 1
        assert metadata["average_execution_time"] == 1.0

    def test_auto_promote_to_verified(self, registry):
        """After 1 success → VERIFIED."""
        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)

        assert registry.get_function_metadata("get_products")["registry_stage"] == "candidate"

        registry.update_execution_stats("get_products", success=True, execution_time=1.0)

        metadata = registry.get_function_metadata("get_products")
        assert metadata["registry_stage"] == "verified"
        assert metadata["success_count"] == 1

    def test_auto_promote_to_golden(self, registry):
        """After 5 successes → GOLDEN."""
        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)

        for i in range(5):
            registry.update_execution_stats("get_products", success=True, execution_time=1.0)

        metadata = registry.get_function_metadata("get_products")
        assert metadata["registry_stage"] == "golden"
        assert metadata["success_count"] == 5

    def test_failure_does_not_promote(self, registry):
        """Failure increments failure_count but doesn't promote."""
        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)
        registry.update_execution_stats("get_products", success=False, execution_time=2.0)

        metadata = registry.get_function_metadata("get_products")
        assert metadata["registry_stage"] == "candidate"
        assert metadata["failure_count"] == 1
        assert metadata["success_count"] == 0
        assert metadata["execution_count"] == 1


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 4: Atom Versioning & Integrity
# ═════════════════════════════════════════════════════════════════

class TestAtomVersioning:
    """Immutable atom versioning with SHA256 integrity checks."""

    def test_atom_versioning(self, registry):
        """Re-registering creates a new version atom."""
        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)
        v1_meta = registry.get_function_metadata("get_products")
        assert v1_meta["version"] == 1

        # Re-register with updated code
        new_code = "def get_products():\n    return [4, 5, 6]\n"
        registry.register_function("get_products", new_code, SAMPLE_METADATA)
        v2_meta = registry.get_function_metadata("get_products")
        assert v2_meta["version"] == 2

        # Both atom files exist (immutable)
        v1_path = Path(v1_meta["atom_path"])
        v2_path = Path(v2_meta["atom_path"])
        assert v1_path.exists()
        assert v2_path.exists()
        assert v1_path != v2_path

    def test_atom_hash_integrity(self, registry):
        """SHA256 hash is stored and matches file content."""
        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)

        metadata = registry.get_function_metadata("get_products")
        stored_hash = metadata["atom_hash"]

        # Compute expected hash
        atom_content = Path(metadata["atom_path"]).read_bytes()
        expected_hash = hashlib.sha256(atom_content).hexdigest()

        assert stored_hash == expected_hash

    def test_verify_atom_integrity(self, registry):
        """Integrity check passes for valid atoms."""
        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)

        metadata = registry.get_function_metadata("get_products")
        assert registry._verify_atom_integrity("get_products", metadata["atom_path"])


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 5: Multi-Index Search
# ═════════════════════════════════════════════════════════════════

class TestMultiIndexSearch:
    """Multi-dimensional search by system, capability, and status."""

    def _register_test_functions(self, registry):
        """Register multiple functions for search testing."""
        registry.register_function("get_products", SAMPLE_CODE, {
            "system": "shopify",
            "capabilities": ["product_lookup"],
            "description": "Get products",
        })
        registry.register_function("create_order", "def create_order(): pass\n", {
            "system": "shopify",
            "capabilities": ["order_management"],
            "description": "Create order",
        })
        registry.register_function("send_message", "def send_message(): pass\n", {
            "system": "slack",
            "capabilities": ["messaging"],
            "description": "Send Slack message",
        })

    def test_get_functions_by_system(self, registry):
        """Finds all functions for a system."""
        self._register_test_functions(registry)

        shopify_funcs = registry.get_functions_by_system("shopify")
        assert len(shopify_funcs) == 2
        names = {f["function_name"] for f in shopify_funcs}
        assert names == {"get_products", "create_order"}

    def test_get_functions_by_capability(self, registry):
        """Finds functions with a specific capability."""
        self._register_test_functions(registry)

        results = registry.get_functions_by_capability("messaging")
        assert len(results) == 1
        assert results[0]["function_name"] == "send_message"

    def test_search_with_status_filter(self, registry):
        """Filters by graduation status."""
        self._register_test_functions(registry)

        # Promote get_products to verified
        registry.update_execution_stats("get_products", success=True, execution_time=1.0)

        # Search for verified only
        results = registry.search(status="verified")
        assert len(results) == 1
        assert results[0]["function_name"] == "get_products"

        # Search for candidates only
        candidates = registry.search(status="candidate")
        assert len(candidates) == 2

    def test_semantic_search(self, registry):
        """Full-text search across metadata fields."""
        self._register_test_functions(registry)

        # Search for "slack"
        results = registry.semantic_search("slack")
        assert len(results) >= 1
        assert results[0]["function_name"] == "send_message"

        # Search for "products"
        results = registry.semantic_search("products")
        assert len(results) >= 1
        assert results[0]["function_name"] == "get_products"


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 6: System Bundles
# ═════════════════════════════════════════════════════════════════

class TestSystemBundles:
    """System bundle generation for sandbox injection."""

    def test_create_system_bundle(self, registry):
        """Generates a {System}Capabilities class."""
        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)
        # Promote to verified so it appears in bundle
        registry.update_execution_stats("get_products", success=True, execution_time=1.0)

        bundle = registry.create_system_bundle("shopify")
        assert bundle is not None
        assert "class ShopifyCapabilities:" in bundle
        assert "def get_products" in bundle
        assert "get_capabilities" in bundle
        assert "describe_capabilities" in bundle

    def test_bundle_excludes_candidates(self, registry):
        """Only verified/golden functions in bundle by default."""
        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)

        # No promotion → still candidate
        bundle = registry.create_system_bundle("shopify")
        assert bundle is None  # No qualifying functions

        # Include candidates explicitly
        bundle = registry.create_system_bundle("shopify", include_candidates=True)
        assert bundle is not None
        assert "def get_products" in bundle

    def test_detect_system_dependencies(self, registry):
        """Parses {System}Capabilities patterns in code."""
        registry.register_function("get_products", SAMPLE_CODE, {
            "system": "shopify",
            "capabilities": ["product_lookup"],
        })

        code = """
caps = ShopifyCapabilities()
products = caps.get_products()
"""
        systems = registry.detect_system_dependencies(code)
        assert "shopify" in systems


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 7: Dependency Graph
# ═════════════════════════════════════════════════════════════════

class TestDependencyGraph:
    """Dependency graph with topological sort."""

    def test_get_dependency_graph(self, registry):
        """Returns correct dependency DAG."""
        registry.register_function("fetch_data", "def fetch_data(): pass\n", {
            "system": "shopify",
            "capabilities": ["data"],
        })
        registry.register_function("process_data", "def process_data(): pass\n", {
            "system": "shopify",
            "capabilities": ["processing"],
            "dependencies": ["fetch_data"],
        })

        graph = registry.get_dependency_graph(["fetch_data", "process_data"])
        assert graph["fetch_data"] == []
        assert graph["process_data"] == ["fetch_data"]

    def test_resolve_execution_plan(self, registry):
        """Topological sort puts dependencies first."""
        registry.register_function("fetch_data", "def fetch_data(): pass\n", {
            "system": "shopify",
            "capabilities": ["data"],
        })
        registry.register_function("process_data", "def process_data(): pass\n", {
            "system": "shopify",
            "capabilities": ["processing"],
            "dependencies": ["fetch_data"],
        })
        registry.register_function("report", "def report(): pass\n", {
            "system": "shopify",
            "capabilities": ["reporting"],
            "dependencies": ["process_data"],
        })

        plan = registry.resolve_execution_plan(["report", "process_data", "fetch_data"])
        assert plan.index("fetch_data") < plan.index("process_data")
        assert plan.index("process_data") < plan.index("report")


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 8: Redis Cognitive Projection
# ═════════════════════════════════════════════════════════════════

class TestRedisSync:
    """Redis index sync for shared discovery."""

    def test_sync_registry_index(self, registry_with_redis):
        """Index is pushed to Redis with correct structure."""
        registry, store = registry_with_redis

        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)

        index = store.get_registry_index()
        assert index is not None
        assert index["total_functions"] == 1
        assert "systems" in index
        assert "shopify" in index["systems"]
        assert "updated_at" in index

    def test_redis_index_contains_system_stages(self, registry_with_redis):
        """Per-system stage counts are present in the Redis index."""
        registry, store = registry_with_redis

        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)
        registry.update_execution_stats("get_products", success=True, execution_time=1.0)

        index = store.get_registry_index()
        shopify = index["systems"]["shopify"]
        assert shopify["function_count"] == 1
        assert shopify["stages"]["verified"] == 1
        assert shopify["stages"]["candidate"] == 0
        assert "product_lookup" in shopify["capabilities"]
        assert "get_products" in shopify["functions"]


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 9: Blob Storage Sync
# ═════════════════════════════════════════════════════════════════

class TestBlobSync:
    """Blob storage sync with namespace prefix for distributed persistence."""

    def test_blob_upload_on_register(self, registry_with_blob):
        """Atom + metadata are uploaded to blob using namespace prefix."""
        registry, blob = registry_with_blob

        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)

        # Check atom was uploaded with prefix namespace
        atom_key = "function_registry/atoms/shopify/get_products_v1.py"
        assert atom_key in blob._data
        assert blob._data[atom_key] == SAMPLE_CODE

        # Check metadata was uploaded with prefix namespace
        meta_key = "function_registry/metadata/get_products.json"
        assert meta_key in blob._data
        meta = json.loads(blob._data[meta_key])
        assert meta["function_name"] == "get_products"
        assert meta["system"] == "shopify"

    def test_blob_sync_on_startup(self, tmp_path):
        """Registry loads from blob when local is empty."""
        blob = MockBlobStorage()

        # Pre-populate blob with a function
        import asyncio
        metadata = {
            "function_name": "remote_func",
            "system": "remote_system",
            "capabilities": ["remote_cap"],
            "version": 1,
            "registry_stage": "verified",
            "atom_path": "",
            "atom_hash": "",
            "success_count": 3,
            "execution_count": 3,
            "failure_count": 0,
        }
        asyncio.run(blob.save(
            "function_registry/metadata/remote_func.json",
            json.dumps(metadata),
        ))
        asyncio.run(blob.save(
            "function_registry/atoms/remote_system/remote_func_v1.py",
            "def remote_func(): return 'from blob'\n",
        ))

        # Create registry and trigger blob sync
        registry = FunctionRegistry(
            storage_path=str(tmp_path / "fresh_registry"),
            blob_storage=blob,
        )
        registry._sync_from_blob()

        # Verify function was synced
        assert registry.has_function("remote_func")
        meta = registry.get_function_metadata("remote_func")
        assert meta["system"] == "remote_system"
        assert meta["registry_stage"] == "verified"

    def test_blob_key_for_local_path(self, registry_with_blob):
        """Local paths map to correct blob namespace keys."""
        registry, _ = registry_with_blob

        # Metadata path
        meta_path = str(registry.metadata_path / "my_func.json")
        assert registry._blob_key_for_local_path(meta_path) == \
            "function_registry/metadata/my_func.json"

        # Atom path (with system subdirectory)
        atom_path = str(registry.atom_storage_path / "shopify" / "get_products_v1.py")
        assert registry._blob_key_for_local_path(atom_path) == \
            "function_registry/atoms/shopify/get_products_v1.py"

        # Bundle path
        bundle_path = str(registry.bundle_cache_path / "shopify_bundle.py")
        assert registry._blob_key_for_local_path(bundle_path) == \
            "function_registry/bundles/shopify_bundle.py"

    def test_local_path_for_blob_key(self, registry_with_blob):
        """Blob keys reverse-map to correct local paths."""
        registry, _ = registry_with_blob

        # Metadata
        local = registry._local_path_for_blob_key(
            "function_registry/metadata/my_func.json"
        )
        assert local == str(registry.metadata_path / "my_func.json")

        # Atom
        local = registry._local_path_for_blob_key(
            "function_registry/atoms/slack/send_msg_v2.py"
        )
        assert local == str(registry.atom_storage_path / "slack" / "send_msg_v2.py")

        # Wrong prefix → None
        assert registry._local_path_for_blob_key("other_prefix/metadata/f.json") is None

    def test_custom_blob_prefix(self, tmp_path, monkeypatch):
        """Custom FUNCTION_REGISTRY_BLOB_PREFIX env var changes namespace."""
        monkeypatch.setenv("FUNCTION_REGISTRY_BLOB_PREFIX", "tenant_a/registry")
        blob = MockBlobStorage()
        registry = FunctionRegistry(
            storage_path=str(tmp_path / "registry"),
            blob_storage=blob,
        )

        registry.register_function("my_func", SAMPLE_CODE, SAMPLE_METADATA)

        # Verify uploads use custom prefix
        assert any(k.startswith("tenant_a/registry/") for k in blob._data)
        assert "tenant_a/registry/atoms/shopify/my_func_v1.py" in blob._data
        assert "tenant_a/registry/metadata/my_func.json" in blob._data

    def test_bundle_upload_to_blob(self, registry_with_blob):
        """System bundles are uploaded to blob storage."""
        registry, blob = registry_with_blob

        # Register a verified function so bundle has content
        registry.register_function("get_products", SAMPLE_CODE, SAMPLE_METADATA)
        registry.update_execution_stats("get_products", success=True, execution_time=1.0)

        # Create bundle
        registry.create_system_bundle("shopify")

        # Verify bundle was uploaded
        bundle_key = "function_registry/bundles/shopify_bundle.py"
        assert bundle_key in blob._data


# ═════════════════════════════════════════════════════════════════
# TEST CLASS 10: Backward Compatibility
# ═════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """CodeRegistry alias and factory function still work."""

    def test_code_registry_alias(self, tmp_path):
        """CodeRegistry is an alias for FunctionRegistry."""
        assert CodeRegistry is FunctionRegistry

    def test_create_code_registry_alias(self, tmp_path):
        """create_code_registry is an alias for create_function_registry."""
        assert create_code_registry is create_function_registry

    def test_old_factory_works(self, tmp_path):
        """create_code_registry() returns a FunctionRegistry."""
        registry = create_code_registry(str(tmp_path / "compat"))
        assert isinstance(registry, FunctionRegistry)
