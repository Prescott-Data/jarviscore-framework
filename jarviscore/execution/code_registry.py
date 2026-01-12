"""
Code Registry - Store and retrieve generated code functions

Purpose:
- Store successfully generated code for reuse
- Index by agent_id, capabilities, task patterns
- Retrieve similar code for future tasks
- File-based storage (no external dependencies)

Storage Structure:
./logs/code_registry/
├─ index.json  # Metadata index for fast search
└─ functions/
    ├─ {function_id}__{hash}.py  # Generated code files
    └─ ...
"""
import json
import hashlib
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class CodeRegistry:
    """
    Registry for storing and retrieving generated code.

    Features:
    - Auto-register successful executions
    - Search by agent capabilities and task patterns
    - File-based storage with JSON index
    - No external dependencies

    Example:
        registry = CodeRegistry()

        # Register generated code
        registry.register(
            code="result = 2 + 2",
            agent_id="calculator-123",
            task="Calculate 2+2",
            capabilities=["math", "arithmetic"],
            output=4
        )

        # Search for similar code
        matches = registry.search(
            capabilities=["math"],
            task_pattern="factorial"
        )
    """

    def __init__(self, registry_dir: str = "./logs/code_registry"):
        """
        Initialize code registry.

        Args:
            registry_dir: Base directory for code storage
        """
        self.registry_dir = Path(registry_dir)
        self.functions_dir = self.registry_dir / "functions"
        self.index_file = self.registry_dir / "index.json"

        # Create directories
        self.functions_dir.mkdir(parents=True, exist_ok=True)

        # Load or create index
        self._index = self._load_index()

        logger.info(f"CodeRegistry initialized: {self.registry_dir}")
        logger.info(f"Indexed functions: {len(self._index)}")

    def register(
        self,
        code: str,
        agent_id: str,
        task: str,
        capabilities: List[str],
        output: Any,
        result_id: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        Register generated code in the registry.

        Args:
            code: Generated Python code
            agent_id: ID of agent that generated code
            task: Original task description
            capabilities: Agent capabilities list
            output: Execution output (for verification)
            result_id: Optional result_id from execution
            metadata: Additional metadata

        Returns:
            function_id: Unique identifier for registered function
        """
        # Generate function ID
        code_hash = self._hash_code(code)
        function_id = f"{agent_id}_{code_hash[:8]}"

        # Check if already registered
        if function_id in self._index:
            logger.debug(f"Code already registered: {function_id}")
            return function_id

        # Store code to file
        code_file = self.functions_dir / f"{function_id}.py"
        code_file.write_text(code)

        # Add to index
        self._index[function_id] = {
            "function_id": function_id,
            "agent_id": agent_id,
            "task": task,
            "capabilities": capabilities,
            "code_hash": code_hash,
            "code_file": str(code_file.relative_to(self.registry_dir)),
            "output_sample": str(output)[:100],  # First 100 chars
            "result_id": result_id,
            "registered_at": datetime.now().isoformat(),
            "metadata": metadata or {},
            # Extract task keywords for search
            "task_keywords": self._extract_keywords(task)
        }

        # Save index
        self._save_index()

        logger.info(f"Registered code: {function_id} (task: {task[:50]}...)")
        return function_id

    def get(self, function_id: str) -> Optional[Dict[str, Any]]:
        """
        Get function metadata and code by ID.

        Args:
            function_id: Function identifier

        Returns:
            Dictionary with metadata and code, or None if not found
        """
        if function_id not in self._index:
            return None

        entry = self._index[function_id].copy()

        # Load code from file
        code_file = self.registry_dir / entry["code_file"]
        if code_file.exists():
            entry["code"] = code_file.read_text()
        else:
            logger.warning(f"Code file missing for {function_id}")
            entry["code"] = None

        return entry

    def search(
        self,
        capabilities: Optional[List[str]] = None,
        task_pattern: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search for matching code in registry.

        Args:
            capabilities: Filter by agent capabilities
            task_pattern: Search in task descriptions
            agent_id: Filter by agent ID
            limit: Maximum results to return

        Returns:
            List of matching function metadata (sorted by relevance)
        """
        matches = []

        for function_id, entry in self._index.items():
            score = 0

            # Filter by agent_id
            if agent_id and entry["agent_id"] != agent_id:
                continue

            # Score by capability overlap
            if capabilities:
                entry_caps = set(entry["capabilities"])
                query_caps = set(capabilities)
                overlap = len(entry_caps & query_caps)
                if overlap == 0:
                    continue  # Must have at least one matching capability
                score += overlap * 10

            # Score by task keyword match
            if task_pattern:
                pattern_keywords = self._extract_keywords(task_pattern)
                entry_keywords = set(entry["task_keywords"])
                keyword_overlap = len(set(pattern_keywords) & entry_keywords)
                if keyword_overlap > 0:
                    score += keyword_overlap * 5

            # Add to matches with score
            match = entry.copy()
            match["_score"] = score
            matches.append(match)

        # Sort by score (descending)
        matches.sort(key=lambda x: x["_score"], reverse=True)

        # Return top matches
        return matches[:limit]

    def list_all(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List all registered functions (most recent first).

        Args:
            limit: Maximum results to return

        Returns:
            List of function metadata
        """
        entries = list(self._index.values())

        # Sort by registration time (most recent first)
        entries.sort(
            key=lambda x: x.get("registered_at", ""),
            reverse=True
        )

        return entries[:limit]

    def _hash_code(self, code: str) -> str:
        """Generate hash of code for deduplication."""
        # Normalize code (remove whitespace variations)
        normalized = re.sub(r'\s+', ' ', code.strip())
        return hashlib.md5(normalized.encode()).hexdigest()

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text."""
        # Convert to lowercase
        text = text.lower()

        # Remove common words
        stopwords = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
            'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'should', 'could', 'may', 'might', 'must', 'can'
        }

        # Extract words (alphanumeric only)
        words = re.findall(r'\b[a-z0-9]+\b', text)

        # Filter stopwords and short words
        keywords = [w for w in words if w not in stopwords and len(w) > 2]

        return keywords

    def _load_index(self) -> Dict:
        """Load index from file."""
        if self.index_file.exists():
            try:
                with open(self.index_file, 'r') as f:
                    index = json.load(f)
                    logger.debug(f"Loaded index with {len(index)} entries")
                    return index
            except Exception as e:
                logger.error(f"Failed to load index: {e}")
                return {}
        return {}

    def _save_index(self):
        """Save index to file."""
        try:
            with open(self.index_file, 'w') as f:
                json.dump(self._index, f, indent=2)
            logger.debug(f"Saved index with {len(self._index)} entries")
        except Exception as e:
            logger.error(f"Failed to save index: {e}")


def create_code_registry(registry_dir: str = "./logs/code_registry") -> CodeRegistry:
    """
    Factory function to create code registry.

    Args:
        registry_dir: Directory for code storage

    Returns:
        CodeRegistry instance
    """
    return CodeRegistry(registry_dir)
