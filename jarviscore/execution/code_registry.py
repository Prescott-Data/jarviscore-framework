"""
Function Registry - Graduated function storage with atom versioning.

Ported from IA/CA FunctionRegistry patterns:
- Graduated promotion: candidate → verified (1 success) → golden (5 successes)
- Immutable atom versioning with SHA256 integrity checks
- System capability bundles ({System}Capabilities classes)
- Multi-index search (by system, capability, source)
- Redis cognitive projection (registry index for shared discovery)
- BlobStorage sync (optional distributed persistence)
- Dependency graph with topological sort
- Semantic search across metadata fields
- Source-only registration via AST for functions with missing deps

Storage Layout:
    {storage_path}/
    ├── metadata/
    │   ├── {function_name}.json
    │   └── ...
    ├── atoms/
    │   ├── {system_name}/
    │   │   ├── {function_name}_v1.py
    │   │   └── {function_name}_v2.py
    │   └── _general/
    │       └── {function_name}_v1.py
    └── bundles/
        ├── {system_name}_bundle.py
        └── ...
"""

import ast
import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Function Status Enum
# ─────────────────────────────────────────────────────────────────

class FunctionStatus(str, Enum):
    """Graduation stages for registered functions.

    Matches IA/CA graduation model:
    - CANDIDATE: Just generated, untested
    - VERIFIED: 1+ successful execution
    - GOLDEN: 5+ successful executions (production-ready)
    """
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    GOLDEN = "golden"


# ─────────────────────────────────────────────────────────────────
# Function Registry
# ─────────────────────────────────────────────────────────────────

class FunctionRegistry:
    """
    Graduated function registry with atom versioning and multi-index search.

    Stores generated code as immutable versioned atoms, tracks execution
    statistics, and automatically promotes functions through graduation
    stages (candidate → verified → golden) based on success count.

    Example:
        registry = FunctionRegistry("./logs/function_registry")

        # Register a function
        registry.register_function(
            "get_products",
            "def get_products(): return [1, 2, 3]",
            metadata={"system": "shopify", "capabilities": ["product_lookup"]}
        )

        # Record successful execution
        registry.update_execution_stats("get_products", success=True, execution_time=1.5)

        # Search by system
        results = registry.get_functions_by_system("shopify")

        # Create system bundle
        bundle_code = registry.create_system_bundle("shopify")
    """

    # Graduation thresholds (matching IA/CA)
    VERIFIED_SUCCESS_THRESHOLD = 1
    GOLDEN_SUCCESS_THRESHOLD = 5

    def __init__(
        self,
        storage_path: Optional[str] = None,
        blob_storage=None,
        redis_store=None,
    ):
        """
        Initialize function registry.

        Args:
            storage_path: Base directory for function storage
            blob_storage: Optional BlobStorage for distributed sync
            redis_store: Optional RedisContextStore for cognitive projection
        """
        # Storage paths (matching IA/CA layout)
        self.storage_path = Path(
            storage_path
            or os.environ.get("FUNCTION_REGISTRY_PATH", "./logs/function_registry")
        )
        self.metadata_path = self.storage_path / "metadata"
        self.atom_storage_path = Path(
            os.environ.get(
                "FUNCTION_ATOM_PATH", str(self.storage_path / "atoms")
            )
        )
        self.bundle_cache_path = Path(
            os.environ.get(
                "FUNCTION_BUNDLE_CACHE_PATH", str(self.storage_path / "bundles")
            )
        )

        # Create directories
        self.metadata_path.mkdir(parents=True, exist_ok=True)
        self.atom_storage_path.mkdir(parents=True, exist_ok=True)
        self.bundle_cache_path.mkdir(parents=True, exist_ok=True)

        # External storage (optional)
        self.blob_storage = blob_storage
        self.redis_store = redis_store

        # Blob namespace prefix (configurable for multi-tenant isolation)
        self.registry_blob_prefix = os.environ.get(
            "FUNCTION_REGISTRY_BLOB_PREFIX", "function_registry"
        ).strip("/")

        # In-memory registries
        self.functions: Dict[str, Optional[Callable]] = {}
        self.function_metadata: Dict[str, Dict[str, Any]] = {}

        # Multi-dimensional indexes
        self.functions_by_system: Dict[str, Set[str]] = {}
        self.functions_by_capability: Dict[str, Set[str]] = {}
        self.functions_by_source: Dict[str, Set[str]] = {}

        # Load existing functions from disk
        self._load_all_metadata()
        self._rebuild_indexes()

        logger.info(
            f"FunctionRegistry initialized: {self.storage_path} "
            f"({len(self.function_metadata)} functions)"
        )

    # ─────────────────────────────────────────────────────────────
    # Registration & Retrieval
    # ─────────────────────────────────────────────────────────────

    def register_function(
        self,
        function_name: str,
        function: Union[str, Callable],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Register a function in the registry.

        Stores code as an immutable versioned atom, saves metadata JSON,
        updates in-memory indexes, and syncs to Redis/blob if configured.

        Args:
            function_name: Unique function name
            function: Source code string or callable
            metadata: Optional metadata dict with keys like:
                - system: System tag (e.g., "shopify", "slack")
                - capabilities: List of capabilities
                - type: Function type ("api", "logic", "utility")
                - description: Human-readable description
                - tags: List of tags
                - dependencies: List of function names this depends on
                - strategy: Execution strategy ("sandbox", "local_exec")

        Returns:
            True if registered successfully
        """
        metadata = metadata or {}

        # Extract source code
        if callable(function):
            import inspect
            source_code = inspect.getsource(function)
            self.functions[function_name] = function
        elif isinstance(function, str):
            source_code = function
            # Try dynamic import
            try:
                self._try_load_callable(function_name, source_code)
            except Exception:
                self._register_source_only(function_name, source_code)
        else:
            logger.error(f"Invalid function type: {type(function)}")
            return False

        # Determine system (for atom directory organization)
        system = metadata.get("system") or metadata.get("domain") or "_general"

        # Resolve version
        existing = self.function_metadata.get(function_name, {})
        current_version = existing.get("version", 0) or 0
        new_version = current_version + 1

        # Save immutable atom
        atom_path = self._save_atom(function_name, source_code, system, new_version)
        atom_hash = self._compute_file_hash(atom_path)

        # Build metadata
        now = datetime.now().isoformat()
        func_metadata = {
            "function_name": function_name,
            "type": metadata.get("type", "utility"),
            "created_at": existing.get("created_at", now),
            "updated_at": now,
            "execution_count": existing.get("execution_count", 0),
            "success_count": existing.get("success_count", 0),
            "failure_count": existing.get("failure_count", 0),
            "average_execution_time": existing.get("average_execution_time", 0.0),
            "registry_stage": existing.get("registry_stage", FunctionStatus.CANDIDATE.value),
            "version": new_version,
            "atom_path": str(atom_path),
            "atom_hash": atom_hash,
            "system": metadata.get("system") or metadata.get("domain"),
            "capabilities": metadata.get("capabilities", []),
            "description": metadata.get("description", ""),
            "tags": metadata.get("tags", []),
            "dependencies": metadata.get("dependencies", []),
            "task_keywords": self._extract_keywords(
                metadata.get("task", "") or metadata.get("description", "")
            ),
            "strategy": metadata.get("strategy", "sandbox"),
            "agent_id": metadata.get("agent_id"),
            "load_status": "loaded" if function_name in self.functions else "source_only",
        }

        # Store in memory
        self.function_metadata[function_name] = func_metadata

        # Save metadata to disk
        self._save_function_metadata(function_name)

        # Update indexes
        self._index_function(function_name, func_metadata)

        # Sync to Redis
        self.sync_registry_index()

        # Sync to blob storage
        self._upload_to_blob(function_name, source_code, func_metadata)

        logger.info(
            f"Registered function: {function_name} v{new_version} "
            f"(system={func_metadata['system']}, stage={func_metadata['registry_stage']})"
        )
        return True

    def unregister_function(
        self, function_name: str, delete_file: bool = False
    ) -> bool:
        """
        Remove a function from the registry.

        Args:
            function_name: Function to remove
            delete_file: If True, delete atom files from disk

        Returns:
            True if removed successfully
        """
        if function_name not in self.function_metadata:
            logger.warning(f"Function not found: {function_name}")
            return False

        metadata = self.function_metadata.pop(function_name, {})
        self.functions.pop(function_name, None)

        # Remove from indexes
        self._deindex_function(function_name, metadata)

        # Remove metadata file
        meta_file = self.metadata_path / f"{function_name}.json"
        if meta_file.exists():
            meta_file.unlink()

        # Optionally delete atom files
        if delete_file and metadata.get("atom_path"):
            atom = Path(metadata["atom_path"])
            if atom.exists():
                atom.unlink()

        # Sync
        self.sync_registry_index()

        logger.info(f"Unregistered function: {function_name}")
        return True

    def get_function(self, function_name: str) -> Optional[Callable]:
        """Get callable function object, or None if not found/source-only."""
        return self.functions.get(function_name)

    def get_function_code(self, function_name: str) -> Optional[str]:
        """Get function source code from atom file."""
        metadata = self.function_metadata.get(function_name)
        if not metadata:
            return None

        atom_path = Path(metadata.get("atom_path", ""))
        if atom_path.exists():
            return atom_path.read_text()

        return None

    def get_function_metadata(self, function_name: str) -> Optional[Dict[str, Any]]:
        """Get function metadata dict."""
        metadata = self.function_metadata.get(function_name)
        return metadata.copy() if metadata else None

    def has_function(self, function_name: str) -> bool:
        """Check if function is registered."""
        return function_name in self.function_metadata

    def update_function_metadata(
        self, function_name: str, updates: Dict[str, Any]
    ) -> bool:
        """
        Merge updates into function metadata.

        Args:
            function_name: Function to update
            updates: Dict of metadata fields to merge

        Returns:
            True if updated successfully
        """
        if function_name not in self.function_metadata:
            return False

        # Remove from old indexes before updating
        old_metadata = self.function_metadata[function_name]
        self._deindex_function(function_name, old_metadata)

        # Merge updates
        old_metadata.update(updates)
        old_metadata["updated_at"] = datetime.now().isoformat()

        # Re-index
        self._index_function(function_name, old_metadata)

        # Save
        self._save_function_metadata(function_name)
        self.sync_registry_index()

        return True

    def list_function_names(self) -> List[str]:
        """List all registered function names."""
        return list(self.function_metadata.keys())

    # ─────────────────────────────────────────────────────────────
    # Graduation & Execution Stats
    # ─────────────────────────────────────────────────────────────

    def update_execution_stats(
        self,
        function_name: str,
        success: bool,
        execution_time: float,
    ) -> bool:
        """
        Update execution statistics and auto-promote based on success count.

        Graduation thresholds:
        - 1+ successes → VERIFIED
        - 5+ successes → GOLDEN

        Args:
            function_name: Function that was executed
            success: Whether execution succeeded
            execution_time: Execution duration in seconds

        Returns:
            True if stats updated successfully
        """
        metadata = self.function_metadata.get(function_name)
        if not metadata:
            logger.warning(f"Cannot update stats: {function_name} not found")
            return False

        # Update counts
        metadata["execution_count"] = metadata.get("execution_count", 0) + 1
        if success:
            metadata["success_count"] = metadata.get("success_count", 0) + 1
        else:
            metadata["failure_count"] = metadata.get("failure_count", 0) + 1

        # Update average execution time
        old_avg = metadata.get("average_execution_time", 0.0)
        old_count = metadata["execution_count"] - 1
        if old_count > 0:
            metadata["average_execution_time"] = (
                (old_avg * old_count + execution_time) / metadata["execution_count"]
            )
        else:
            metadata["average_execution_time"] = execution_time

        # Auto-promote based on success count
        stage = metadata.get("registry_stage", FunctionStatus.CANDIDATE.value)
        if success:
            if metadata["success_count"] >= self.GOLDEN_SUCCESS_THRESHOLD:
                stage = FunctionStatus.GOLDEN.value
            elif metadata["success_count"] >= self.VERIFIED_SUCCESS_THRESHOLD:
                stage = FunctionStatus.VERIFIED.value
        metadata["registry_stage"] = stage
        metadata["updated_at"] = datetime.now().isoformat()

        # Save and sync
        self._save_function_metadata(function_name)
        self.sync_registry_index()

        logger.debug(
            f"Stats updated: {function_name} "
            f"(success={success}, stage={stage}, "
            f"count={metadata['success_count']}/{metadata['execution_count']})"
        )
        return True

    # ─────────────────────────────────────────────────────────────
    # Multi-Index Search
    # ─────────────────────────────────────────────────────────────

    def get_functions_by_system(self, system_name: str) -> List[Dict[str, Any]]:
        """Get all functions for a system."""
        names = self.functions_by_system.get(system_name, set())
        return [
            self.function_metadata[n].copy()
            for n in names
            if n in self.function_metadata
        ]

    def get_functions_by_capability(self, capability: str) -> List[Dict[str, Any]]:
        """Get all functions with a capability."""
        names = self.functions_by_capability.get(capability, set())
        return [
            self.function_metadata[n].copy()
            for n in names
            if n in self.function_metadata
        ]

    def search(
        self,
        capabilities: Optional[List[str]] = None,
        task_pattern: Optional[str] = None,
        system: Optional[str] = None,
        status: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Multi-filter scored search across registered functions.

        Args:
            capabilities: Filter by capabilities (at least one must match)
            task_pattern: Search in task keywords
            system: Filter by system
            status: Filter by registry_stage
            agent_id: Filter by agent_id
            limit: Maximum results

        Returns:
            List of matching metadata dicts, sorted by relevance score
        """
        matches = []

        for name, metadata in self.function_metadata.items():
            score = 0

            # Filter by agent_id
            if agent_id and metadata.get("agent_id") != agent_id:
                continue

            # Filter by system
            if system and metadata.get("system") != system:
                continue

            # Filter by status
            if status and metadata.get("registry_stage") != status:
                continue

            # Score by capability overlap
            if capabilities:
                entry_caps = set(metadata.get("capabilities", []))
                query_caps = set(capabilities)
                overlap = len(entry_caps & query_caps)
                if overlap == 0:
                    continue
                score += overlap * 10

            # Score by task keyword match
            if task_pattern:
                pattern_keywords = self._extract_keywords(task_pattern)
                entry_keywords = set(metadata.get("task_keywords", []))
                keyword_overlap = len(set(pattern_keywords) & entry_keywords)
                if keyword_overlap > 0:
                    score += keyword_overlap * 5

            # Bonus for higher graduation stage
            stage = metadata.get("registry_stage", "candidate")
            if stage == FunctionStatus.GOLDEN.value:
                score += 3
            elif stage == FunctionStatus.VERIFIED.value:
                score += 1

            match = metadata.copy()
            match["_score"] = score
            matches.append(match)

        matches.sort(key=lambda x: x["_score"], reverse=True)
        return matches[:limit]

    def semantic_search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Full-text search across function metadata fields.

        Searches: name, description, system, capabilities, tags.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching metadata dicts, sorted by relevance
        """
        terms = query.lower().split()
        matches = []

        for name, metadata in self.function_metadata.items():
            # Build searchable text
            searchable_parts = [
                name.lower(),
                (metadata.get("description") or "").lower(),
                (metadata.get("system") or "").lower(),
                " ".join(metadata.get("capabilities", [])).lower(),
                " ".join(metadata.get("tags", [])).lower(),
            ]
            searchable = " ".join(searchable_parts)

            score = 0
            for term in terms:
                if term in name.lower():
                    score += 3  # Name match is highest
                elif term in (metadata.get("system") or "").lower():
                    score += 2  # System match
                elif term in searchable:
                    score += 1  # General match

            if score > 0:
                match = metadata.copy()
                match["_score"] = score
                matches.append(match)

        matches.sort(key=lambda x: x["_score"], reverse=True)
        return matches[:limit]

    # ─────────────────────────────────────────────────────────────
    # System Bundles
    # ─────────────────────────────────────────────────────────────

    def create_system_bundle(
        self, system_name: str, include_candidates: bool = False
    ) -> Optional[str]:
        """
        Generate a {System}Capabilities class from registered functions.

        Only includes verified/golden functions by default. The generated
        class has a method for each function, suitable for sandbox injection.

        Args:
            system_name: System to bundle (e.g., "shopify")
            include_candidates: If True, include candidate functions too

        Returns:
            Generated Python class code, or None if no qualifying functions
        """
        functions = self.get_functions_by_system(system_name)
        if not functions:
            return None

        # Filter by graduation stage
        if not include_candidates:
            functions = [
                f for f in functions
                if f.get("registry_stage") in (
                    FunctionStatus.VERIFIED.value,
                    FunctionStatus.GOLDEN.value,
                )
            ]

        if not functions:
            return None

        # Generate class name: shopify → ShopifyCapabilities
        class_name = f"{system_name.title().replace('_', '')}Capabilities"

        # Build bundle code
        lines = [
            f'"""Auto-generated capability bundle for {system_name}."""',
            "",
            f"class {class_name}:",
            f'    """Capabilities for {system_name} system.',
            f"",
            f"    Functions: {len(functions)}",
            f"    Generated: {datetime.now().isoformat()}",
            f'    """',
            "",
            "    def __init__(self, auth_context=None):",
            "        self.auth_context = auth_context or {}",
            "",
        ]

        # Add a method for each function
        for func in functions:
            name = func["function_name"]
            desc = func.get("description", f"Execute {name}")
            stage = func.get("registry_stage", "candidate")
            lines.extend([
                f"    def {name}(self, **kwargs):",
                f'        """{desc} [{stage}]"""',
                f"        # Load from registry atom: {func.get('atom_path', 'N/A')}",
                f"        raise NotImplementedError(",
                f'            "Inject via prepare_code_with_bundle()"',
                f"        )",
                "",
            ])

        # Add discovery methods
        cap_list = set()
        for f in functions:
            cap_list.update(f.get("capabilities", []))

        lines.extend([
            "    @staticmethod",
            "    def get_capabilities():",
            f'        """List available capabilities."""',
            f"        return {sorted(cap_list)}",
            "",
            "    @staticmethod",
            "    def describe_capabilities():",
            f'        """Describe available functions."""',
            "        return {",
        ])
        for func in functions:
            name = func["function_name"]
            desc = func.get("description", "")
            lines.append(f'            "{name}": "{desc}",')
        lines.extend([
            "        }",
            "",
        ])

        bundle_code = "\n".join(lines)

        # Cache bundle to disk
        bundle_file = self.bundle_cache_path / f"{system_name}_bundle.py"
        bundle_file.write_text(bundle_code)
        self._upload_registry_path(str(bundle_file))

        # Check if all golden + all hashed → cache key
        all_golden = all(
            f.get("registry_stage") == FunctionStatus.GOLDEN.value
            for f in functions
        )
        all_hashed = all(f.get("atom_hash") for f in functions)
        if all_golden and all_hashed:
            cache_key = self._compute_bundle_cache_key(system_name, functions)
            cached_file = self.bundle_cache_path / f"{cache_key}.py"
            cached_file.write_text(bundle_code)
            self._upload_registry_path(str(cached_file))

        logger.info(
            f"Created system bundle: {class_name} "
            f"({len(functions)} functions)"
        )
        return bundle_code

    def prepare_code_with_bundle(
        self,
        function_code: str,
        system_name: str,
        auth_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Inject system bundle into function code for sandbox execution.

        Prepends the bundle class definition so generated code can use
        {System}Capabilities without external imports.

        Args:
            function_code: Generated code to augment
            system_name: System bundle to inject
            auth_context: Optional auth context dict

        Returns:
            Code with bundle prepended
        """
        bundle_code = self.create_system_bundle(system_name)
        if not bundle_code:
            return function_code

        class_name = f"{system_name.title().replace('_', '')}Capabilities"

        # Build injection
        injection_lines = [
            "# === Auto-injected System Bundle ===",
            bundle_code,
            "",
        ]

        # Instantiate with auth context
        if auth_context:
            injection_lines.append(
                f"{system_name}_caps = {class_name}(auth_context={auth_context!r})"
            )
        else:
            injection_lines.append(f"{system_name}_caps = {class_name}()")

        injection_lines.extend([
            "# === End System Bundle ===",
            "",
        ])

        return "\n".join(injection_lines) + function_code

    def detect_system_dependencies(self, function_code: str) -> List[str]:
        """
        Detect {System}Capabilities patterns in code.

        Scans for patterns like ShopifyCapabilities, SlackCapabilities, etc.

        Args:
            function_code: Code to analyze

        Returns:
            List of system names detected
        """
        pattern = r"(\w+)Capabilities"
        matches = re.findall(pattern, function_code)

        systems = set()
        for match in matches:
            # Convert PascalCase back to lowercase system name
            system = match.lower()
            if system in self.functions_by_system:
                systems.add(system)

        return sorted(systems)

    # ─────────────────────────────────────────────────────────────
    # Dependency Graph
    # ─────────────────────────────────────────────────────────────

    def get_dependency_graph(
        self, function_names: List[str]
    ) -> Dict[str, List[str]]:
        """
        Get dependency relationships between functions.

        Args:
            function_names: Functions to include in graph

        Returns:
            Dict mapping function_name → list of dependency names
        """
        graph = {}
        for name in function_names:
            metadata = self.function_metadata.get(name, {})
            deps = metadata.get("dependencies", [])
            # Only include deps that are in our function set
            graph[name] = [d for d in deps if d in self.function_metadata]
        return graph

    def resolve_execution_plan(
        self, function_names: List[str]
    ) -> List[str]:
        """
        Topologically sort functions by dependencies.

        Dependencies execute first. Raises ValueError on circular deps.

        Args:
            function_names: Functions to sort

        Returns:
            Functions in execution order (dependencies first)
        """
        graph = self.get_dependency_graph(function_names)
        visited = set()
        in_stack = set()
        order = []

        def dfs(node):
            if node in in_stack:
                raise ValueError(f"Circular dependency detected involving: {node}")
            if node in visited:
                return
            in_stack.add(node)
            for dep in graph.get(node, []):
                dfs(dep)
            in_stack.remove(node)
            visited.add(node)
            order.append(node)

        for name in function_names:
            dfs(name)

        return order

    # ─────────────────────────────────────────────────────────────
    # Atom Versioning & Integrity
    # ─────────────────────────────────────────────────────────────

    def _save_atom(
        self, function_name: str, code: str, system: str, version: int
    ) -> Path:
        """Save immutable versioned atom file."""
        system_dir = self.atom_storage_path / system
        system_dir.mkdir(parents=True, exist_ok=True)

        atom_file = system_dir / f"{function_name}_v{version}.py"
        atom_file.write_text(code)

        logger.debug(f"Saved atom: {atom_file}")
        return atom_file

    def _compute_file_hash(self, path: Union[str, Path]) -> str:
        """Compute SHA256 hash of a file."""
        path = Path(path)
        if not path.exists():
            return ""
        content = path.read_bytes()
        return hashlib.sha256(content).hexdigest()

    def _verify_atom_integrity(self, function_name: str, atom_path: str) -> bool:
        """Verify atom integrity by comparing stored hash to file hash."""
        stored = self.function_metadata.get(function_name, {}).get("atom_hash")
        if not stored:
            return True  # Allow legacy atoms without hash
        current = self._compute_file_hash(atom_path)
        if current != stored:
            logger.error(
                f"Atom integrity check failed for {function_name}: "
                f"stored={stored[:16]}... current={current[:16]}..."
            )
            return False
        return True

    # ─────────────────────────────────────────────────────────────
    # Persistence (Metadata & Indexes)
    # ─────────────────────────────────────────────────────────────

    def _save_function_metadata(self, function_name: str) -> None:
        """Write function metadata to JSON file."""
        metadata = self.function_metadata.get(function_name)
        if not metadata:
            return

        meta_file = self.metadata_path / f"{function_name}.json"
        # Convert Path objects and sets for JSON serialization
        serializable = {}
        for k, v in metadata.items():
            if isinstance(v, Path):
                serializable[k] = str(v)
            elif isinstance(v, set):
                serializable[k] = sorted(v)
            else:
                serializable[k] = v

        try:
            with open(meta_file, "w") as f:
                json.dump(serializable, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save metadata for {function_name}: {e}")

    def _load_all_metadata(self) -> None:
        """Load all metadata JSON files from disk."""
        if not self.metadata_path.exists():
            return

        for meta_file in self.metadata_path.glob("*.json"):
            try:
                with open(meta_file) as f:
                    metadata = json.load(f)
                function_name = metadata.get(
                    "function_name", meta_file.stem
                )
                self.function_metadata[function_name] = metadata

                # Try to load callable from atom
                atom_path = metadata.get("atom_path")
                if atom_path and Path(atom_path).exists():
                    try:
                        code = Path(atom_path).read_text()
                        self._try_load_callable(function_name, code)
                    except Exception:
                        self.functions[function_name] = None
                else:
                    self.functions[function_name] = None

            except Exception as e:
                logger.error(f"Failed to load metadata from {meta_file}: {e}")

    def _rebuild_indexes(self) -> None:
        """Rebuild in-memory indexes from metadata."""
        self.functions_by_system.clear()
        self.functions_by_capability.clear()
        self.functions_by_source.clear()

        for name, metadata in self.function_metadata.items():
            self._index_function(name, metadata)

    def _index_function(self, function_name: str, metadata: Dict) -> None:
        """Add function to all applicable indexes."""
        # System index
        system = metadata.get("system")
        if system:
            self.functions_by_system.setdefault(system, set()).add(function_name)

        # Capability index
        for cap in metadata.get("capabilities", []):
            self.functions_by_capability.setdefault(cap, set()).add(function_name)

        # Source index (by agent_id)
        agent_id = metadata.get("agent_id")
        if agent_id:
            self.functions_by_source.setdefault(agent_id, set()).add(function_name)

    def _deindex_function(self, function_name: str, metadata: Dict) -> None:
        """Remove function from all indexes."""
        system = metadata.get("system")
        if system and system in self.functions_by_system:
            self.functions_by_system[system].discard(function_name)
            if not self.functions_by_system[system]:
                del self.functions_by_system[system]

        for cap in metadata.get("capabilities", []):
            if cap in self.functions_by_capability:
                self.functions_by_capability[cap].discard(function_name)
                if not self.functions_by_capability[cap]:
                    del self.functions_by_capability[cap]

        agent_id = metadata.get("agent_id")
        if agent_id and agent_id in self.functions_by_source:
            self.functions_by_source[agent_id].discard(function_name)
            if not self.functions_by_source[agent_id]:
                del self.functions_by_source[agent_id]

    # ─────────────────────────────────────────────────────────────
    # Redis Cognitive Projection
    # ─────────────────────────────────────────────────────────────

    def sync_registry_index(self) -> None:
        """Push compact registry index to Redis for shared discovery."""
        if not self.redis_store:
            return

        try:
            index = self._build_registry_index()
            self.redis_store.save_registry_index(index)
        except Exception as e:
            logger.warning(f"Failed to sync registry index to Redis: {e}")

    def _build_registry_index(self) -> Dict[str, Any]:
        """Build compact index summary for Redis."""
        systems = {}
        for system_name, func_names in self.functions_by_system.items():
            capabilities = set()
            stages = {"candidate": 0, "verified": 0, "golden": 0}
            functions_list = []

            for name in func_names:
                metadata = self.function_metadata.get(name, {})
                capabilities.update(metadata.get("capabilities", []))
                stage = metadata.get("registry_stage", "candidate")
                if stage in stages:
                    stages[stage] += 1
                functions_list.append(name)

            systems[system_name] = {
                "function_count": len(func_names),
                "capability_count": len(capabilities),
                "capabilities": sorted(capabilities)[:20],
                "functions": sorted(functions_list)[:20],
                "stages": stages,
            }

        return {
            "updated_at": datetime.now().isoformat(),
            "total_functions": len(self.function_metadata),
            "systems": systems,
        }

    # ─────────────────────────────────────────────────────────────
    # Blob Storage Sync
    # ─────────────────────────────────────────────────────────────

    def _blob_key_for_local_path(self, local_path: str) -> str:
        """Map a local filesystem path to its blob storage key.

        Uses registry_blob_prefix to namespace all registry artifacts,
        enabling multi-tenant isolation when multiple registries share
        the same blob storage backend.

        Mapping:
            {metadata_path}/foo.json  → {prefix}/metadata/foo.json
            {atom_storage_path}/s/f.py → {prefix}/atoms/s/f.py
            {bundle_cache_path}/b.py  → {prefix}/bundles/b.py
            {storage_path}/other.py   → {prefix}/flat/other.py
            unrecognized/file.py      → {prefix}/misc/file.py
        """
        local_path = os.path.abspath(local_path)
        metadata_root = os.path.abspath(str(self.metadata_path))
        atoms_root = os.path.abspath(str(self.atom_storage_path))
        bundles_root = os.path.abspath(str(self.bundle_cache_path))
        flat_root = os.path.abspath(str(self.storage_path))

        if local_path.startswith(metadata_root):
            rel = os.path.relpath(local_path, metadata_root)
            return f"{self.registry_blob_prefix}/metadata/{rel.replace(os.sep, '/')}"
        if local_path.startswith(atoms_root):
            rel = os.path.relpath(local_path, atoms_root)
            return f"{self.registry_blob_prefix}/atoms/{rel.replace(os.sep, '/')}"
        if local_path.startswith(bundles_root):
            rel = os.path.relpath(local_path, bundles_root)
            return f"{self.registry_blob_prefix}/bundles/{rel.replace(os.sep, '/')}"
        if local_path.startswith(flat_root):
            rel = os.path.relpath(local_path, flat_root)
            return f"{self.registry_blob_prefix}/flat/{rel.replace(os.sep, '/')}"
        # Fallback for unrecognized paths
        return f"{self.registry_blob_prefix}/misc/{os.path.basename(local_path)}"

    def _local_path_for_blob_key(self, blob_name: str) -> Optional[str]:
        """Reverse-map a blob storage key to its local filesystem path.

        Returns None if the blob key doesn't belong to this registry's prefix.
        """
        prefix = f"{self.registry_blob_prefix}/"
        if not blob_name.startswith(prefix):
            return None
        rel = blob_name[len(prefix):]
        if rel.startswith("metadata/"):
            return str(self.metadata_path / rel[len("metadata/"):])
        if rel.startswith("atoms/"):
            return str(self.atom_storage_path / rel[len("atoms/"):])
        if rel.startswith("bundles/"):
            return str(self.bundle_cache_path / rel[len("bundles/"):])
        if rel.startswith("flat/"):
            return str(self.storage_path / rel[len("flat/"):])
        return None

    def _upload_registry_path(self, local_path: str) -> None:
        """Upload a single local file to blob storage using namespace mapping."""
        if not self.blob_storage:
            return
        try:
            blob_key = self._blob_key_for_local_path(local_path)
            content = Path(local_path).read_text()
            self._run_async(self.blob_storage.save(blob_key, content))
            logger.debug(f"Blob upload: {blob_key}")
        except Exception as e:
            logger.warning(f"Blob upload failed for {local_path}: {e}")

    def _download_registry_path(self, local_path: str) -> None:
        """Download a single file from blob storage to local path."""
        if not self.blob_storage:
            return
        try:
            blob_key = self._blob_key_for_local_path(local_path)
            content = self._run_async(self.blob_storage.read(blob_key))
            if content is not None:
                Path(local_path).parent.mkdir(parents=True, exist_ok=True)
                Path(local_path).write_text(content)
                logger.debug(f"Blob download: {blob_key}")
        except Exception as e:
            logger.warning(f"Blob download failed for {local_path}: {e}")

    def _upload_to_blob(
        self, function_name: str, code: str, metadata: Dict
    ) -> None:
        """Upload atom + metadata to blob storage if configured."""
        if not self.blob_storage:
            return

        try:
            # Upload atom via namespace mapping
            atom_path = metadata.get("atom_path")
            if atom_path:
                self._upload_registry_path(atom_path)

            # Upload metadata
            meta_path = str(self.metadata_path / f"{function_name}.json")
            self._upload_registry_path(meta_path)

            logger.debug(f"Uploaded to blob: {function_name}")
        except Exception as e:
            logger.warning(f"Failed to upload {function_name} to blob: {e}")

    def _sync_from_blob(self) -> None:
        """Download missing registry artifacts from blob on startup.

        Lists all blob keys under this registry's prefix and downloads
        any that don't have a corresponding local file.
        """
        if not self.blob_storage:
            return

        try:
            prefix = f"{self.registry_blob_prefix}/"
            blob_names = self._run_async(self.blob_storage.list(prefix))

            downloaded = 0
            for blob_name in blob_names:
                local_path = self._local_path_for_blob_key(blob_name)
                if not local_path:
                    continue
                if os.path.exists(local_path):
                    continue
                # Download missing file
                content = self._run_async(self.blob_storage.read(blob_name))
                if content is not None:
                    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(local_path).write_text(content)
                    downloaded += 1

            if downloaded:
                # Reload metadata and rebuild indexes after sync
                self._load_all_metadata()
                self._rebuild_indexes()

            logger.info(
                f"Blob sync complete: downloaded {downloaded} files, "
                f"{len(self.function_metadata)} functions total"
            )
        except Exception as e:
            logger.warning(f"Blob sync failed: {e}")

    def _run_async(self, coro):
        """Run async BlobStorage method synchronously."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()

    # ─────────────────────────────────────────────────────────────
    # Source-Only Registration (AST fallback)
    # ─────────────────────────────────────────────────────────────

    def _register_source_only(self, function_name: str, source_code: str) -> None:
        """Register function via AST without importing (no callable)."""
        try:
            tree = ast.parse(source_code)
            # Validate that at least one function/class definition exists
            has_def = any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                for node in ast.walk(tree)
            )
            if has_def:
                self.functions[function_name] = None  # Source-only marker
                logger.debug(f"Source-only registration: {function_name}")
            else:
                # Still register — code might be a script-style function
                self.functions[function_name] = None
                logger.debug(
                    f"Source-only registration (no def): {function_name}"
                )
        except SyntaxError as e:
            logger.warning(
                f"Failed to parse source for {function_name}: {e}"
            )
            self.functions[function_name] = None

    def _try_load_callable(self, function_name: str, source_code: str) -> None:
        """Try to dynamically import function as callable."""
        import types

        module = types.ModuleType(f"_registry_{function_name}")
        try:
            exec(compile(source_code, f"<registry:{function_name}>", "exec"), module.__dict__)
            # Look for the function in module namespace
            if hasattr(module, function_name):
                self.functions[function_name] = getattr(module, function_name)
            else:
                # Try to find any callable
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if callable(attr) and not attr_name.startswith("_"):
                        self.functions[function_name] = attr
                        break
                else:
                    self.functions[function_name] = None
        except Exception:
            raise

    # ─────────────────────────────────────────────────────────────
    # Bundle Cache Helpers
    # ─────────────────────────────────────────────────────────────

    def _compute_bundle_cache_key(
        self, system_name: str, functions: List[Dict]
    ) -> str:
        """Deterministic cache key based on atom hashes + version + stage."""
        parts = [system_name]
        for func in sorted(functions, key=lambda f: f["function_name"]):
            parts.append(
                f"{func['function_name']}:"
                f"{func.get('version', 0)}:"
                f"{func.get('atom_hash', '')}:"
                f"{func.get('registry_stage', 'candidate')}"
            )
        combined = "|".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    # ─────────────────────────────────────────────────────────────
    # Text Utilities (from original CodeRegistry)
    # ─────────────────────────────────────────────────────────────

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text."""
        text = text.lower()
        stopwords = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "as", "is", "was", "are",
            "were", "been", "be", "have", "has", "had", "do", "does", "did",
            "will", "would", "should", "could", "may", "might", "must", "can",
        }
        words = re.findall(r"\b[a-z0-9]+\b", text)
        return [w for w in words if w not in stopwords and len(w) > 2]

    def _hash_code(self, code: str) -> str:
        """Generate hash of code for deduplication."""
        normalized = re.sub(r"\s+", " ", code.strip())
        return hashlib.md5(normalized.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────
# Backward-Compatible Aliases
# ─────────────────────────────────────────────────────────────────

CodeRegistry = FunctionRegistry


# ─────────────────────────────────────────────────────────────────
# Factory Functions
# ─────────────────────────────────────────────────────────────────

def create_function_registry(
    storage_path: str = "./logs/function_registry",
    blob_storage=None,
    redis_store=None,
) -> FunctionRegistry:
    """
    Factory function to create function registry.

    Args:
        storage_path: Directory for function storage
        blob_storage: Optional BlobStorage for distributed sync
        redis_store: Optional RedisContextStore for cognitive projection

    Returns:
        FunctionRegistry instance
    """
    return FunctionRegistry(storage_path, blob_storage, redis_store)


# Backward-compatible alias
create_code_registry = create_function_registry
