"""People use a room from the terminal: create, check out, push, review, decide, watch."""

import asyncio

import pytest

from jarviscore.cli.room import main
from jarviscore.room import Room


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REDIS_URL", raising=False)
    site = tmp_path / "site"
    (site / "pages").mkdir(parents=True)
    (site / "index.html").write_text("<h1>Launch</h1>\n")
    (site / "pages" / "pricing.html").write_text("<p>$10</p>\n")
    main(["create", "launch", "--from", str(site), "--as", "alice"])
    return tmp_path


def room():
    return Room.open("launch")


def test_a_person_checks_out_edits_and_pushes(here, capsys):
    main(["checkout", "launch", str(here / "mine")])
    (here / "mine" / "pages" / "pricing.html").write_text("<p>$12</p>\n")
    main(["push", str(here / "mine"), "-m", "Raise the price", "--as", "alice"])

    [proposal] = room().proposals("open")
    assert (proposal.author, proposal.title, proposal.paths) == (
        "alice", "Raise the price", ["pages/pricing.html"])

    capsys.readouterr()
    main(["diff", "launch", proposal.id])
    out = capsys.readouterr().out
    assert "-<p>$10</p>" in out and "+<p>$12</p>" in out

    main(["accept", "launch", proposal.id, "--as", "bob"])
    assert asyncio.run(room().read("pages/pricing.html")) == b"<p>$12</p>\n"


def test_push_and_accept_in_one_go(here):
    main(["checkout", "launch", str(here / "mine")])
    (here / "mine" / "index.html").write_text("<h1>Launch day</h1>\n")
    main(["push", str(here / "mine"), "--as", "alice", "--accept"])
    assert room().head().version == 2


def test_two_people_editing_one_file_get_a_conflict_not_a_lost_edit(here, capsys):
    main(["checkout", "launch", str(here / "alice")])
    main(["checkout", "launch", str(here / "bob")])
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
    main(["checkout", "launch", str(here / "mine")])
    (here / "mine" / "index.html").write_text("<h1>v2</h1>\n")
    main(["push", str(here / "mine"), "-m", "New title", "--as", "alice"])
    [proposal] = room().proposals("open")
    main(["reject", "launch", proposal.id, "Keep the old title", "--as", "bob"])

    capsys.readouterr()
    main(["status", "launch"])
    assert "launch  v1  2 files" in capsys.readouterr().out

    main(["watch", "launch", "--once"])
    feed = capsys.readouterr().out
    assert "alice opened the room with 2 files (v1)" in feed
    assert f"▲ {proposal.id} proposed by alice: New title (1 file, on v1)" in feed
    assert f"✗ bob rejected {proposal.id}: Keep the old title" in feed


def test_an_unknown_room_is_reported(here, capsys):
    with pytest.raises(SystemExit):
        main(["status", "nowhere"])
    assert "does not exist" in capsys.readouterr().out


def test_members_only_from_the_terminal(here, capsys):
    main(["members", "launch"])
    assert "is open" in capsys.readouterr().out
    main(["role", "launch", "bob", "viewer", "--as", "alice"])
    main(["members", "launch"])
    out = capsys.readouterr().out
    assert "owner   alice" in out and "viewer  bob" in out

    main(["checkout", "launch", str(here / "bob")])
    (here / "bob" / "index.html").write_text("<h1>Bob</h1>\n")
    with pytest.raises(SystemExit):
        main(["push", str(here / "bob"), "--as", "bob"])
    assert "bob cannot propose changes" in capsys.readouterr().out
