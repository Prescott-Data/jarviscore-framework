"""
Tests for FunctionRegistry auth extensions (6H.5).

Tests get_oauth_metadata() and get_system_auth_requirements() methods
using the existing registry fixture pattern.
"""

import os
import tempfile
import pytest

from jarviscore.execution.code_registry import FunctionRegistry


@pytest.fixture
def registry(tmp_path):
    """Fresh FunctionRegistry with temp storage."""
    return FunctionRegistry(storage_path=str(tmp_path / "registry"))


def _register_with_oauth(registry, name, system, oauth_metadata):
    """Helper to register a function with oauth_metadata."""
    code = f"def {name}(): pass"
    registry.register_function(
        function_name=name,
        function=code,
        metadata={
            "system": system,
            "description": f"Test function {name}",
            "oauth_metadata": oauth_metadata,
        },
    )


class TestGetOauthMetadata:

    def test_returns_oauth_metadata(self, registry):
        _register_with_oauth(registry, "list_products", "shopify", {
            "provider": "shopify",
            "scopes": ["read_products"],
            "auth_type": "oauth2",
        })
        meta = registry.get_oauth_metadata("list_products")
        assert meta is not None
        assert meta["provider"] == "shopify"
        assert "read_products" in meta["scopes"]

    def test_returns_none_for_no_oauth(self, registry):
        registry.register_function(
            function_name="add_numbers",
            function="def add_numbers(a, b): return a + b",
            metadata={"system": "utils", "description": "Add two numbers"},
        )
        assert registry.get_oauth_metadata("add_numbers") is None

    def test_returns_none_for_unknown_function(self, registry):
        assert registry.get_oauth_metadata("nonexistent") is None


class TestGetSystemAuthRequirements:

    def test_single_function_system(self, registry):
        _register_with_oauth(registry, "get_orders", "shopify", {
            "provider": "shopify",
            "scopes": ["read_orders"],
            "auth_type": "oauth2",
        })
        reqs = registry.get_system_auth_requirements("shopify")
        assert reqs["provider"] == "shopify"
        assert reqs["scopes"] == ["read_orders"]
        assert reqs["auth_type"] == "oauth2"

    def test_multi_function_scope_aggregation(self, registry):
        _register_with_oauth(registry, "list_products", "shopify", {
            "provider": "shopify",
            "scopes": ["read_products"],
            "auth_type": "oauth2",
        })
        _register_with_oauth(registry, "create_order", "shopify", {
            "provider": "shopify",
            "scopes": ["write_orders", "read_products"],
            "auth_type": "oauth2",
        })
        reqs = registry.get_system_auth_requirements("shopify")
        assert reqs["provider"] == "shopify"
        # Scopes should be aggregated and sorted
        assert "read_products" in reqs["scopes"]
        assert "write_orders" in reqs["scopes"]
        assert len(reqs["scopes"]) == 2  # deduplicated

    def test_no_auth_system_returns_empty(self, registry):
        registry.register_function(
            function_name="calc",
            function="def calc(): return 42",
            metadata={"system": "math", "description": "Calculator"},
        )
        reqs = registry.get_system_auth_requirements("math")
        assert reqs == {}

    def test_unknown_system_returns_empty(self, registry):
        reqs = registry.get_system_auth_requirements("nonexistent")
        assert reqs == {}

    def test_mixed_auth_and_no_auth_functions(self, registry):
        """System with some functions having oauth and some not."""
        _register_with_oauth(registry, "auth_func", "hybrid", {
            "provider": "github",
            "scopes": ["repo"],
            "auth_type": "oauth2",
        })
        registry.register_function(
            function_name="public_func",
            function="def public_func(): pass",
            metadata={"system": "hybrid", "description": "No auth needed"},
        )
        reqs = registry.get_system_auth_requirements("hybrid")
        assert reqs["provider"] == "github"
        assert reqs["scopes"] == ["repo"]
