"""Developers and operators use rooms from a terminal: create, check out, push, review, decide, watch."""

import asyncio

import fakeredis
import pytest

from jarviscore.cli.room import main
from jarviscore.room import Room


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # The team's Redis, as every CLI invocation and mesh node would reach it.
    server = fakeredis.FakeServer()
    monkeypatch.setattr("redis.Redis.from_url", lambda url, **kwargs: fakeredis.FakeRedis(
        server=server, decode_responses=kwargs.get("decode_responses", False)))
    monkeypatch.setenv("REDIS_URL", "redis://team-redis:6379/0")
    monkeypatch.setenv("JARVISCORE_TENANT", "acme")
    site = tmp_path / "site"
    (site / "pages").mkdir(parents=True)
    (site / "index.html").write_text("<h1>Launch</h1>\n")
    (site / "pages" / "pricing.html").write_text("<p>$10</p>\n")
    main(["create", "launch", "--from", str(site), "--as", "alice"])
    main(["role", "launch", "bob", "editor", "--as", "alice"])
    return tmp_path


def room(tenant="acme"):
    return Room.open("launch", tenant=tenant)


def test_a_person_checks_out_edits_and_pushes(here, capsys):
    main(["checkout", "launch", str(here / "mine"), "--as", "alice"])
    (here / "mine" / "pages" / "pricing.html").write_text("<p>$12</p>\n")
    main(["push", str(here / "mine"), "-m", "Raise the price", "--as", "alice"])

    [proposal] = room().proposals("open")
    assert (proposal.author, proposal.title, proposal.paths) == (
        "alice", "Raise the price", ["pages/pricing.html"])

    capsys.readouterr()
    main(["diff", "launch", proposal.id, "--as", "bob"])
    out = capsys.readouterr().out
    assert "-<p>$10</p>" in out and "+<p>$12</p>" in out

    main(["accept", "launch", proposal.id, "--as", "bob"])
    assert asyncio.run(room().read("pages/pricing.html")) == b"<p>$12</p>\n"


def test_push_and_accept_in_one_go(here):
    main(["checkout", "launch", str(here / "mine"), "--as", "alice"])
    (here / "mine" / "index.html").write_text("<h1>Launch day</h1>\n")
    main(["push", str(here / "mine"), "--as", "alice", "--accept"])
    assert room().head().version == 2


def test_two_people_editing_one_file_get_a_conflict_not_a_lost_edit(here, capsys):
    main(["checkout", "launch", str(here / "alice"), "--as", "alice"])
    main(["checkout", "launch", str(here / "bob"), "--as", "bob"])
    (here / "alice" / "index.html").write_text("<h1>Alice</h1>\n")
    (here / "bob" / "index.html").write_text("<h1>Bob</h1>\n")
    main(["push", str(here / "alice"), "--as", "alice", "--accept"])
    main(["push", str(here / "bob"), "--as", "bob"])
    [bobs] = room().proposals("open")

    with pytest.raises(SystemExit):
        main(["accept", "launch", bobs.id, "--as", "bob"])
    assert "index.html changed since" in capsys.readouterr().out
    assert asyncio.run(room().read("index.html")) == b"<h1>Alice</h1>\n"


def test_status_and_the_feed(here, capsys):
    main(["checkout", "launch", str(here / "mine"), "--as", "alice"])
    (here / "mine" / "index.html").write_text("<h1>v2</h1>\n")
    main(["push", str(here / "mine"), "-m", "New title", "--as", "alice"])
    [proposal] = room().proposals("open")
    main(["reject", "launch", proposal.id, "Keep the old title", "--as", "bob"])

    capsys.readouterr()
    main(["status", "launch", "--as", "bob"])
    assert "launch  v1  2 files" in capsys.readouterr().out

    main(["watch", "launch", "--once", "--as", "bob"])
    feed = capsys.readouterr().out
    assert "alice opened the room with 2 files (v1)" in feed
    assert f"▲ {proposal.id} proposed by alice: New title (1 file, on v1)" in feed
    assert f"✗ bob rejected {proposal.id}: Keep the old title" in feed


def test_an_unknown_room_is_reported(here, capsys):
    with pytest.raises(SystemExit):
        main(["status", "nowhere", "--as", "alice"])
    assert "does not exist" in capsys.readouterr().out


def test_a_room_is_private_until_its_owner_shares_it(here, capsys):
    main(["members", "launch"])
    out = capsys.readouterr().out
    assert "private to its members" in out and "owner   alice" in out and "editor  bob" in out

    with pytest.raises(SystemExit):
        main(["status", "launch", "--as", "carol"])
    assert "carol cannot see the room" in capsys.readouterr().out

    main(["visibility", "launch", "tenant", "--tenant-role", "viewer", "--as", "alice"])
    main(["status", "launch", "--as", "carol"])
    main(["checkout", "launch", str(here / "carol"), "--as", "carol"])
    (here / "carol" / "index.html").write_text("<h1>Carol</h1>\n")
    with pytest.raises(SystemExit):
        main(["push", str(here / "carol"), "--as", "carol"])
    assert "carol cannot propose changes" in capsys.readouterr().out


def test_tenants_are_separate(here, capsys):
    with pytest.raises(SystemExit):
        main(["--tenant", "globex", "status", "launch", "--as", "alice"])
    assert room("acme").exists() and not room("globex").exists()


def test_the_audit_from_the_terminal(here, capsys):
    main(["checkout", "launch", str(here / "mine"), "--as", "alice"])
    (here / "mine" / "index.html").write_text("<h1>v2</h1>\n")
    main(["push", str(here / "mine"), "-m", "New title", "--as", "alice"])
    [proposal] = room().proposals("open")
    main(["reject", "launch", proposal.id, "Keep the old title", "--as", "bob"])
    capsys.readouterr()
    main(["audit", "launch"])
    out = capsys.readouterr().out
    assert "proposal.rejected" in out and "Keep the old title" in out and "bob" in out
    main(["audit", "launch", "--json"])
    import json
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[-1]["action"] == "proposal.rejected"


def test_spending_caps_from_the_terminal(here, capsys):
    main(["caps", "--usd-per-month", "200"])
    main(["caps", "alice", "--tokens-per-day", "5000"])
    out = capsys.readouterr().out
    assert "everyone in acme: usd_per_month=200.0" in out
    assert "tokens_per_day=5000" in out and "usd_per_month=200.0" in out and "day " in out
    main(["caps", "alice", "--clear", "tokens-per-day"])
    assert "tokens_per_day" not in capsys.readouterr().out
