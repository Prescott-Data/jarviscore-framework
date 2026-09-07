"""A run's files leave the sandbox and stay reachable in the next run."""

import pytest

from jarviscore.execution.coder_sandbox import create_coder_sandbox
from jarviscore.storage.local import LocalBlobStorage


@pytest.fixture
def storage(tmp_path):
    return LocalBlobStorage(str(tmp_path / "blobs"))


@pytest.fixture
def sandbox(tmp_path, storage):
    return create_coder_sandbox(
        workspace_dir=tmp_path / "work",
        timeout=20,
        blob_storage=storage,
        artifact_prefix="artifacts/tester",
    )


class TestAnAgentKnowsWhatItProduced:

    @pytest.mark.asyncio
    async def test_a_written_file_is_reported_without_being_declared(self, sandbox):
        """Code that forgets to list a file has still made one."""
        out = await sandbox.execute(
            "blob_path('report.txt').write_text('hello')\n"
            "result = {'data': 'done'}\n"
        )
        names = [a["name"] for a in out["artifacts"]]
        assert names == ["report.txt"]
        assert out["files_created"], "the file it made should be named back to it"

    @pytest.mark.asyncio
    async def test_the_artifact_carries_a_storage_handle(self, sandbox, storage):
        out = await sandbox.execute("blob_path('data.csv').write_text('a,b\\n1,2')\n")
        artifact = out["artifacts"][0]
        assert artifact["key"] == "artifacts/tester/data.csv"
        assert artifact["bytes"] == 7
        assert await storage.read(artifact["key"]) in ("a,b\n1,2", b"a,b\n1,2")

    @pytest.mark.asyncio
    async def test_untouched_files_are_not_reported_again(self, sandbox):
        await sandbox.execute("blob_path('once.txt').write_text('one')\n")
        out = await sandbox.execute("result = {'data': 'nothing written'}\n")
        assert out["artifacts"] == []

    @pytest.mark.asyncio
    async def test_binary_content_survives(self, sandbox, storage):
        out = await sandbox.execute("blob_path('image.bin').write_bytes(bytes([0, 159, 146, 150]))\n")
        stored = await storage.read(out["artifacts"][0]["key"])
        assert bytes(stored) == bytes([0, 159, 146, 150])


class TestWorkContinuesAcrossRuns:

    @pytest.mark.asyncio
    async def test_a_later_run_can_read_what_an_earlier_run_produced(self, sandbox):
        first = await sandbox.execute("blob_path('notes.md').write_text('yesterday')\n")
        key = first["artifacts"][0]["key"]

        second = await sandbox.execute(
            "async def main():\n"
            f"    path = await fetch_artifact({key!r})\n"
            "    return {'recovered': path.read_text()}\n"
        )
        assert second["data"] == {"recovered": "yesterday"}

    @pytest.mark.asyncio
    async def test_a_missing_artifact_says_so(self, sandbox):
        out = await sandbox.execute(
            "async def main():\n"
            "    return await fetch_artifact('artifacts/tester/absent.txt')\n"
        )
        assert out["status"] == "failure"
        assert "absent.txt" in out["error"]


class TestStorageIsTheDevelopersChoice:

    @pytest.mark.asyncio
    async def test_without_storage_the_work_still_runs_and_is_reported(self, tmp_path):
        """A local-only developer configures nothing and still sees what was made."""
        plain = create_coder_sandbox(workspace_dir=tmp_path / "work", timeout=20)
        out = await plain.execute("blob_path('local.txt').write_text('kept on disk')\n")
        artifact = out["artifacts"][0]
        assert artifact["name"] == "local.txt"
        assert artifact["key"] is None
        assert (tmp_path / "work/output/local.txt").read_text() == "kept on disk"

    @pytest.mark.asyncio
    async def test_fetching_without_storage_explains_itself(self, tmp_path):
        plain = create_coder_sandbox(workspace_dir=tmp_path / "work", timeout=20)
        out = await plain.execute(
            "async def main():\n    return await fetch_artifact('anything')\n"
        )
        assert out["status"] == "failure"
        assert "blob storage" in out["error"]

    @pytest.mark.asyncio
    async def test_a_storage_failure_does_not_fail_the_run(self, tmp_path):
        class Broken:
            async def save(self, path, content):
                raise RuntimeError("bucket unreachable")

        sandbox = create_coder_sandbox(
            workspace_dir=tmp_path / "work", timeout=20, blob_storage=Broken()
        )
        out = await sandbox.execute("blob_path('x.txt').write_text('work happened')\n")
        assert out["status"] == "success"
        assert out["artifacts"][0]["error"] == "bucket unreachable"
