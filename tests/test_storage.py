"""
Tests for Phase 1: BlobStorage (Local + Azure mock + Abstract interface)

What these tests prove:
- BlobStorage ABC enforces the contract: any backend must implement save/read/list/delete
- LocalBlobStorage correctly stores/reads files on the filesystem
- LocalBlobStorage prevents directory traversal attacks (../../etc/passwd)
- Convenience methods (scratchpad, artifact) build correct paths
- MockBlobStorage is a valid drop-in replacement for real storage
- Binary content (images, compiled code) survives save/read roundtrip
- Empty directories are cleaned up on delete (no filesystem bloat)
- Listing with prefixes returns only matching paths

WHY THIS MATTERS FOR THE FRAMEWORK:
BlobStorage is the foundation for: function registry (stores code atoms),
working memory (JSONL scratchpads), long-term memory (compressed summaries),
and workflow artifacts. Every phase from 5 onward depends on it working correctly.
"""

import asyncio
import os
import shutil
import tempfile

import pytest

from jarviscore.storage.base import BlobStorage
from jarviscore.storage.local import LocalBlobStorage
from jarviscore.testing import MockBlobStorage


# ======================================================================
# BlobStorage ABC Contract
# ======================================================================

class TestBlobStorageABC:
    """Prove that BlobStorage enforces the interface contract."""

    def test_cannot_instantiate_abc(self):
        """BlobStorage is abstract — you must implement all 4 methods."""
        with pytest.raises(TypeError):
            BlobStorage()

    def test_local_is_valid_implementation(self):
        """LocalBlobStorage satisfies the BlobStorage contract."""
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalBlobStorage(base_path=tmp)
            assert isinstance(storage, BlobStorage)

    def test_mock_has_same_interface(self):
        """MockBlobStorage has the same methods as BlobStorage."""
        mock = MockBlobStorage()
        for method in ["save", "read", "list", "delete",
                       "save_scratchpad", "read_scratchpad",
                       "save_artifact", "read_artifact", "exists"]:
            assert hasattr(mock, method), f"MockBlobStorage missing {method}"


# ======================================================================
# LocalBlobStorage
# ======================================================================

class TestLocalBlobStorage:
    """Test filesystem-backed blob storage."""

    @pytest.fixture
    def storage(self):
        tmp = tempfile.mkdtemp()
        yield LocalBlobStorage(base_path=tmp)
        shutil.rmtree(tmp)

    @pytest.mark.asyncio
    async def test_save_and_read_text(self, storage):
        """Basic roundtrip: save text, read it back."""
        await storage.save("test/hello.txt", "Hello World")
        content = await storage.read("test/hello.txt")
        assert content == "Hello World"

    @pytest.mark.asyncio
    async def test_save_and_read_binary(self, storage):
        """Binary content (images, compiled code) survives roundtrip."""
        data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        await storage.save("test/image.png", data)
        content = await storage.read("test/image.png")
        assert content == data

    @pytest.mark.asyncio
    async def test_save_and_read_json(self, storage):
        """JSON content roundtrip (the most common use case)."""
        import json
        payload = {"result": 42, "facts": ["a", "b"], "nested": {"key": True}}
        await storage.save("output.json", json.dumps(payload))
        content = await storage.read("output.json")
        assert json.loads(content) == payload

    @pytest.mark.asyncio
    async def test_read_nonexistent_returns_none(self, storage):
        """Reading a path that doesn't exist returns None, not an error."""
        content = await storage.read("does/not/exist.txt")
        assert content is None

    @pytest.mark.asyncio
    async def test_overwrite(self, storage):
        """Saving to the same path overwrites the content."""
        await storage.save("file.txt", "version 1")
        await storage.save("file.txt", "version 2")
        content = await storage.read("file.txt")
        assert content == "version 2"

    @pytest.mark.asyncio
    async def test_list_with_prefix(self, storage):
        """Listing returns only paths matching the prefix."""
        await storage.save("workflows/wf-1/step-1.json", "data1")
        await storage.save("workflows/wf-1/step-2.json", "data2")
        await storage.save("workflows/wf-2/step-1.json", "data3")

        paths = await storage.list("workflows/wf-1/")
        assert len(paths) == 2
        assert "workflows/wf-1/step-1.json" in paths
        assert "workflows/wf-1/step-2.json" in paths
        assert "workflows/wf-2/step-1.json" not in paths

    @pytest.mark.asyncio
    async def test_list_empty_prefix(self, storage):
        """Listing a non-existent prefix returns empty list."""
        paths = await storage.list("nonexistent/")
        assert paths == []

    @pytest.mark.asyncio
    async def test_delete(self, storage):
        """Delete removes the file and returns True."""
        await storage.save("temp.txt", "delete me")
        assert await storage.delete("temp.txt") is True
        assert await storage.read("temp.txt") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, storage):
        """Deleting a non-existent path returns False."""
        assert await storage.delete("ghost.txt") is False

    @pytest.mark.asyncio
    async def test_delete_cleans_empty_dirs(self, storage):
        """After deleting the last file in a directory, empty parents are cleaned up."""
        await storage.save("deep/nested/dir/file.txt", "data")
        await storage.delete("deep/nested/dir/file.txt")
        # The deep/nested/dir/ chain should be gone
        assert not os.path.exists(os.path.join(storage.base_path, "deep"))

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, storage):
        """Attempting directory traversal raises ValueError."""
        with pytest.raises(ValueError, match="Path traversal"):
            storage._full_path("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_path_traversal_with_dotdot_in_middle(self, storage):
        """Path traversal via embedded .. is also blocked."""
        with pytest.raises(ValueError, match="Path traversal"):
            storage._full_path("workflows/../../etc/shadow")

    @pytest.mark.asyncio
    async def test_creates_base_path_on_init(self):
        """LocalBlobStorage creates the base directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmp:
            new_path = os.path.join(tmp, "new", "storage", "dir")
            storage = LocalBlobStorage(base_path=new_path)
            assert os.path.isdir(new_path)

    @pytest.mark.asyncio
    async def test_exists(self, storage):
        """exists() returns True for saved files, False for missing."""
        assert await storage.exists("nope.txt") is False
        await storage.save("yep.txt", "here")
        assert await storage.exists("yep.txt") is True


# ======================================================================
# Convenience Methods (scratchpad, artifact)
# ======================================================================

class TestConvenienceMethods:
    """
    Test the convenience methods that build on save/read.

    These prove that workflow scratchpads and artifacts use consistent
    path conventions — critical for the memory system (Phase 8) to find
    data written by the kernel (Phase 6).
    """

    @pytest.fixture
    def storage(self):
        tmp = tempfile.mkdtemp()
        yield LocalBlobStorage(base_path=tmp)
        shutil.rmtree(tmp)

    @pytest.mark.asyncio
    async def test_scratchpad_roundtrip(self, storage):
        """Working scratchpad save/read uses correct path convention."""
        await storage.save_scratchpad("wf-1", "step-analyst", "# Research Notes\n- Found API docs")
        content = await storage.read_scratchpad("wf-1", "step-analyst")
        assert content.startswith("# Research Notes")

        # Verify the actual path convention
        paths = await storage.list("workflows/wf-1/scratchpads/")
        assert "workflows/wf-1/scratchpads/step-analyst.md" in paths

    @pytest.mark.asyncio
    async def test_artifact_roundtrip(self, storage):
        """Step artifacts use correct path convention."""
        code = "def hello():\n    return 'world'"
        await storage.save_artifact("wf-1", "step-coder", "generated.py", code)
        content = await storage.read_artifact("wf-1", "step-coder", "generated.py")
        assert content == code

        paths = await storage.list("workflows/wf-1/artifacts/step-coder/")
        assert "workflows/wf-1/artifacts/step-coder/generated.py" in paths

    @pytest.mark.asyncio
    async def test_multiple_artifacts_per_step(self, storage):
        """A single step can produce multiple artifacts."""
        await storage.save_artifact("wf-1", "step-1", "code.py", "print('hi')")
        await storage.save_artifact("wf-1", "step-1", "output.json", '{"ok": true}')
        await storage.save_artifact("wf-1", "step-1", "error.log", "")

        paths = await storage.list("workflows/wf-1/artifacts/step-1/")
        assert len(paths) == 3


# ======================================================================
# MockBlobStorage
# ======================================================================

class TestMockBlobStorage:
    """
    Prove MockBlobStorage behaves identically to LocalBlobStorage.

    This is critical — if MockBlobStorage diverges from the real impl,
    tests pass but production breaks.
    """

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Same lifecycle as LocalBlobStorage: save → read → list → delete."""
        mock = MockBlobStorage()

        await mock.save("a/b/c.txt", "content")
        assert await mock.read("a/b/c.txt") == "content"
        assert await mock.list("a/") == ["a/b/c.txt"]
        assert await mock.exists("a/b/c.txt") is True

        await mock.delete("a/b/c.txt")
        assert await mock.read("a/b/c.txt") is None
        assert await mock.exists("a/b/c.txt") is False

    @pytest.mark.asyncio
    async def test_scratchpad_and_artifact(self):
        """Convenience methods work on mock too."""
        mock = MockBlobStorage()

        await mock.save_scratchpad("wf-1", "step-1", "notes")
        assert await mock.read_scratchpad("wf-1", "step-1") == "notes"

        await mock.save_artifact("wf-1", "step-1", "code.py", "x=1")
        assert await mock.read_artifact("wf-1", "step-1", "code.py") == "x=1"

    @pytest.mark.asyncio
    async def test_clear(self):
        """clear() wipes all stored data (useful between tests)."""
        mock = MockBlobStorage()
        await mock.save("a.txt", "1")
        await mock.save("b.txt", "2")
        mock.clear()
        assert await mock.read("a.txt") is None
        assert mock.stored_paths == []

    @pytest.mark.asyncio
    async def test_stored_paths_for_assertions(self):
        """stored_paths property lets tests verify what was written."""
        mock = MockBlobStorage()
        await mock.save("z.txt", "last")
        await mock.save("a.txt", "first")
        # sorted alphabetically
        assert mock.stored_paths == ["a.txt", "z.txt"]
