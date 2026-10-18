"""One Redis holds workspace and room files, so teams on different machines need nothing else."""

import fakeredis
import pytest

from jarviscore.execution.workspace import BlobSnapshotStore, SandboxBinding, SourceRef
from jarviscore.room import FileRoomLedger, Room
from jarviscore.storage import get_blob_storage
from jarviscore.storage.redis_blob import RedisBlobStorage


@pytest.fixture
def server():
    return fakeredis.FakeServer()


def storage(server, **options):
    return RedisBlobStorage("redis://unused", client=fakeredis.FakeRedis(server=server), **options)


async def test_text_and_bytes_round_trip(server):
    blobs = storage(server)
    await blobs.save("docs/plan.md", "# Plan\n")
    await blobs.save("img/logo.png", b"\x89PNG\x00\xff")
    assert await blobs.read("docs/plan.md") == "# Plan\n"
    assert await blobs.read("img/logo.png") == b"\x89PNG\x00\xff"
    assert await blobs.read("missing") is None
    assert await blobs.list("docs/") == ["docs/plan.md"]
    assert await blobs.exists("img/logo.png") and blobs.has_local_path("img/logo.png")
    assert await blobs.delete("img/logo.png") and not await blobs.exists("img/logo.png")


async def test_unsafe_paths_and_oversized_blobs_are_refused(server):
    blobs = storage(server, max_blob_bytes=4)
    with pytest.raises(ValueError):
        await blobs.save("../escape", "x")
    with pytest.raises(ValueError, match="at most 4"):
        await blobs.save("big.txt", "12345")


async def test_a_workspace_written_on_one_machine_is_materialized_on_another(server, tmp_path):
    here, there = BlobSnapshotStore(storage(server)), BlobSnapshotStore(storage(server))
    snapshot = await here.capture(SourceRef("room", "launch", "1"), "v1", {"plan.md": "# Plan\n"})

    async with SandboxBinding(there, await there.load(snapshot.manifest_blob_path)) as binding:
        assert (binding.workspace / "plan.md").read_text() == "# Plan\n"


async def test_people_on_two_machines_share_one_room(server, tmp_path):
    ledger = FileRoomLedger(str(tmp_path / "rooms"))  # stands in for the shared Redis ledger
    alice = Room("launch", blob_storage=storage(server), ledger=ledger)
    bob = Room("launch", blob_storage=storage(server), ledger=ledger)
    await alice.ensure({"plan.md": "# Plan\n"}, by="alice")

    proposal = await bob.propose({"plan.md": "# Plan\n\nShip Tuesday\n"}, author="bob")
    await alice.accept(proposal.id, by="alice")

    assert await bob.read("plan.md") == b"# Plan\n\nShip Tuesday\n"


def test_the_factory_builds_it_from_settings(monkeypatch):
    from types import SimpleNamespace

    built = get_blob_storage(SimpleNamespace(storage_backend="redis", redis_url="redis://localhost:6399/0"))
    assert isinstance(built, RedisBlobStorage)
    with pytest.raises(ValueError, match="REDIS_URL"):
        get_blob_storage(SimpleNamespace(storage_backend="redis", redis_url=None))
