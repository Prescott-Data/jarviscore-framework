"""
Tests for Phase 8A: WorkingScratchpad.

What these tests prove:
- write() appends a JSONL entry to blob storage
- Multiple writes accumulate correctly (read-append-write)
- read_all() parses every JSONL line into a dict
- get_notes() returns markdown-formatted output
- Malformed lines are skipped gracefully
- Blob path includes role when provided, omits it when empty
- Empty scratchpad returns [] / "" without error
"""
import json
import pytest

from jarviscore.memory.scratchpad import WorkingScratchpad
from jarviscore.testing import MockBlobStorage


@pytest.fixture
def blob():
    return MockBlobStorage()


@pytest.fixture
def pad(blob):
    return WorkingScratchpad(blob, "wf-1", "step1", "analyst")


@pytest.fixture
def pad_no_role(blob):
    return WorkingScratchpad(blob, "wf-1", "step1")


# ======================================================================
# Blob path
# ======================================================================

class TestBlobPath:
    def test_path_includes_role(self, pad):
        assert pad._path == "workflows/wf-1/scratchpads/step1_analyst.md"

    def test_path_omits_role_when_empty(self, pad_no_role):
        assert pad_no_role._path == "workflows/wf-1/scratchpads/step1.md"


# ======================================================================
# write()
# ======================================================================

class TestWrite:
    @pytest.mark.asyncio
    async def test_single_write_creates_blob(self, pad, blob):
        await pad.write("thought", {"content": "analyse the data"})
        raw = await blob.read(pad._path)
        assert raw is not None
        parsed = json.loads(raw.strip())
        assert parsed["type"] == "thought"
        assert parsed["content"] == "analyse the data"

    @pytest.mark.asyncio
    async def test_multiple_writes_accumulate(self, pad):
        await pad.write("thought", {"content": "first"})
        await pad.write("action", {"tool": "http_get"})
        await pad.write("result", {"status": 200})
        entries = await pad.read_all()
        assert len(entries) == 3
        assert entries[0]["type"] == "thought"
        assert entries[1]["type"] == "action"
        assert entries[2]["type"] == "result"

    @pytest.mark.asyncio
    async def test_write_type_injected_into_entry(self, pad):
        await pad.write("observation", {"value": 42})
        entries = await pad.read_all()
        assert entries[0]["type"] == "observation"
        assert entries[0]["value"] == 42


# ======================================================================
# read_all()
# ======================================================================

class TestReadAll:
    @pytest.mark.asyncio
    async def test_empty_scratchpad_returns_empty_list(self, pad):
        result = await pad.read_all()
        assert result == []

    @pytest.mark.asyncio
    async def test_malformed_line_skipped(self, pad, blob):
        await blob.save(pad._path, '{"type":"ok","val":1}\nnot json\n{"type":"ok2","val":2}')
        entries = await pad.read_all()
        assert len(entries) == 2
        assert entries[0]["type"] == "ok"
        assert entries[1]["type"] == "ok2"

    @pytest.mark.asyncio
    async def test_blank_lines_skipped(self, pad, blob):
        await blob.save(pad._path, '\n\n{"type":"entry","x":1}\n\n')
        entries = await pad.read_all()
        assert len(entries) == 1


# ======================================================================
# get_notes()
# ======================================================================

class TestGetNotes:
    @pytest.mark.asyncio
    async def test_empty_returns_empty_string(self, pad):
        notes = await pad.get_notes()
        assert notes == ""

    @pytest.mark.asyncio
    async def test_notes_contain_step_id(self, pad):
        await pad.write("thought", {"content": "check data"})
        notes = await pad.get_notes()
        assert "step1" in notes

    @pytest.mark.asyncio
    async def test_notes_contain_entry_types(self, pad):
        await pad.write("thought", {"content": "plan"})
        await pad.write("action", {"tool": "search"})
        notes = await pad.get_notes()
        assert "thought" in notes
        assert "action" in notes

    @pytest.mark.asyncio
    async def test_notes_is_markdown(self, pad):
        await pad.write("thought", {"content": "testing"})
        notes = await pad.get_notes()
        assert notes.startswith("## ")
