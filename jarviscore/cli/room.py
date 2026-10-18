"""
jarviscore room — work together on one shared workspace.

Usage:
    jarviscore room create launch --from ./site --as alice
    jarviscore room status launch
    jarviscore room watch launch                       # live feed; Ctrl-C to stop
    jarviscore room ask launch "Add a pricing page" --as alice
    jarviscore room diff launch p-1a2b3c4d
    jarviscore room accept launch p-1a2b3c4d --as bob
    jarviscore room reject launch p-1a2b3c4d "Prices are wrong" --as bob [--redo]
    jarviscore room checkout launch ./my-copy
    jarviscore room push ./my-copy -m "Tighter copy" --as alice [--accept]
    jarviscore room role launch bob editor --as alice   # makes the room members-only

Rooms live in the mesh's Redis (REDIS_URL or --redis-url), so every person
and agent node that shares it sees the same rooms.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _ok(msg: str) -> str: return f"\033[32m✓\033[0m  {msg}"
def _err(msg: str) -> str: return f"\033[31m✗\033[0m  {msg}"


def _room(args):
    from jarviscore.room import Room

    return Room.open(args.room, redis_url=args.redis_url)


def _read_dir(directory: str):
    from jarviscore.room.room import CHECKOUT_MARKER, IGNORED_NAMES

    root = Path(directory)
    if not root.is_dir():
        raise SystemExit(_err(f"{directory} is not a directory"))
    files = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if (path.is_dir() or relative == CHECKOUT_MARKER
                or set(Path(relative).parts) & set(IGNORED_NAMES)):
            continue
        files[relative] = path.read_bytes()
    return files


async def cmd_create(args):
    room = _room(args)
    files = _read_dir(args.from_dir) if args.from_dir else {}
    head = await room.ensure(files, by=args.as_)
    print(_ok(f"Room {room.id} at v{head.version} with {len(files)} files"))


async def cmd_status(args):
    room = _room(args)
    head = room.head()
    snapshot = await room.snapshot()
    print(f"{room.id}  v{head.version}  {len(snapshot.entries)} files  "
          f"(last change by {head.updated_by or 'unknown'})")
    proposals = room.proposals("open")
    if not proposals:
        print("No open proposals.")
    for p in proposals:
        print(f"  ▲ {p.id}  by {p.author}" + (f" for {p.asked_by}" if p.asked_by else "")
              + f"  on v{p.base_version}  {len(p.changes)} files  {p.title}")


async def cmd_watch(args):
    from jarviscore.room.feed import RoomFeed, stamp

    room = _room(args)
    room.head()
    feed = RoomFeed(room)
    if args.new:
        feed.skip_history()
    while True:
        for item in feed.poll():
            print(f"{stamp(item.at)}  {item.text}", flush=True)
        if args.once:
            return
        await asyncio.sleep(args.interval)


async def cmd_diff(args):
    room = _room(args)
    proposal = room.proposal(args.proposal)
    print(f"{proposal.id}  {proposal.status}  by {proposal.author}"
          + (f" for {proposal.asked_by}" if proposal.asked_by else "")
          + f"  on v{proposal.base_version}")
    if proposal.title:
        print(f"  {proposal.title}")
    if proposal.reason:
        print(f"  reason: {proposal.reason}")
    print()
    for change in await room.diff(args.proposal):
        sys.stdout.write(change.unified())


async def cmd_accept(args):
    from jarviscore.room import RoomConflict

    room = _room(args)
    try:
        head = await room.accept(args.proposal, by=args.as_)
    except RoomConflict as exc:
        print(_err(f"Not accepted: {', '.join(exc.paths)} changed since {args.proposal} was made."))
        print("   Ask for it again on the current files, or check out, merge by hand, and push.")
        sys.exit(1)
    print(_ok(f"{args.proposal} accepted → v{head.version}"))


async def cmd_reject(args):
    room = _room(args)
    await room.reject(args.proposal, by=args.as_, reason=args.reason)
    print(_ok(f"{args.proposal} rejected"))
    if args.redo:
        proposal = room.proposal(args.proposal)
        await _ask(args, room, proposal.title or args.reason, revision_of=args.proposal)


async def cmd_members(args):
    room = _room(args)
    members = room.members()
    if not members:
        print(f"{room.id} is open: everyone can ask, propose, accept and reject.")
        return
    for person, role in sorted(members.items(), key=lambda m: (-["viewer", "editor", "owner"].index(m[1]), m[0])):
        print(f"  {role:<7} {person}")


async def cmd_role(args):
    room = _room(args)
    role = None if args.role == "none" else args.role
    room.set_role(args.person, role, by=args.as_)
    print(_ok(f"{args.person}: {role or 'removed'} in {room.id}"))


async def cmd_checkout(args):
    room = _room(args)
    head = await room.checkout(args.directory)
    print(_ok(f"{room.id} v{head.version} checked out to {args.directory}"))
    print(f"   Edit there, then: jarviscore room push {args.directory} -m \"what you did\" --as YOU")


async def cmd_push(args):
    from jarviscore.room import RoomConflict
    from jarviscore.room.room import CHECKOUT_MARKER

    marker = Path(args.directory) / CHECKOUT_MARKER
    if not marker.exists():
        print(_err(f"{args.directory} is not a room checkout"))
        sys.exit(1)
    args.room = json.loads(marker.read_text())["room"]
    room = _room(args)
    proposal = await room.push(args.directory, author=args.as_, title=args.message or "")
    if proposal is None:
        print("Nothing changed.")
        return
    print(_ok(f"{proposal.id} proposed ({len(proposal.changes)} files)"))
    if args.accept:
        try:
            head = await room.accept(proposal.id, by=args.as_)
        except RoomConflict as exc:
            print(_err(f"Not accepted: {', '.join(exc.paths)} changed in the room meanwhile."))
            sys.exit(1)
        print(_ok(f"accepted → v{head.version}"))


async def cmd_ask(args):
    await _ask(args, _room(args), args.goal)


async def _ask(args, room, goal, revision_of=""):
    """Put the asker on the mesh as a person, then ask the mesh's agents to do the work."""
    from jarviscore import Mesh
    from jarviscore.human import HumanAgent
    from jarviscore.room import Room

    mesh = Mesh(config={"redis_url": _mesh_redis(args), "p2p_enabled": False})
    mesh.add(HumanAgent(args.as_, ["human"]))
    await mesh.start()
    try:
        bound = Room.for_mesh(mesh, room.id)
        print(f"Asked. Follow along with: jarviscore room watch {room.id}")
        asked = await bound.ask(goal, asked_by=args.as_, revision_of=revision_of,
                                timeout=args.timeout)
        if asked.proposal:
            print(_ok(f"{asked.proposal.id} to review: jarviscore room diff {room.id} {asked.proposal.id}"))
        else:
            print(f"Finished ({asked.status}) with no file changes. {asked.summary}")
    finally:
        await mesh.stop()


def _mesh_redis(args) -> str:
    redis_url = args.redis_url
    if not redis_url:
        from jarviscore.config.settings import Settings
        redis_url = Settings().redis_url
    if not redis_url:
        print(_err("This needs the mesh's Redis: set REDIS_URL or pass --redis-url"))
        sys.exit(1)
    return redis_url


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jarviscore room", description="Work together in a shared room")
    p.add_argument("--redis-url", default=None, help="Redis shared by the mesh (default: REDIS_URL)")
    sub = p.add_subparsers(dest="subcommand")

    def with_room(name, help_text):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("room")
        return cmd

    create = with_room("create", "Open a room, optionally with the files of a directory")
    create.add_argument("--from", dest="from_dir", default=None)
    create.add_argument("--as", dest="as_", default="")

    with_room("status", "The room's version and open proposals")

    watch = with_room("watch", "Live feed of what happens in the room")
    watch.add_argument("--new", action="store_true", help="Only what happens from now on")
    watch.add_argument("--once", action="store_true", help="Print what has happened and exit")
    watch.add_argument("--interval", type=float, default=1.0)

    ask = with_room("ask", "Ask the mesh's agents to do something in the room")
    ask.add_argument("goal")
    ask.add_argument("--as", dest="as_", required=True)
    ask.add_argument("--timeout", type=float, default=1800)

    diff = with_room("diff", "What a proposal changes")
    diff.add_argument("proposal")

    accept = with_room("accept", "Merge a proposal into the room")
    accept.add_argument("proposal")
    accept.add_argument("--as", dest="as_", required=True)

    reject = with_room("reject", "Turn a proposal down with a reason")
    reject.add_argument("proposal")
    reject.add_argument("reason")
    reject.add_argument("--as", dest="as_", required=True)
    reject.add_argument("--redo", action="store_true", help="Ask the agents to redo it with your reason")
    reject.add_argument("--timeout", type=float, default=1800)

    with_room("members", "Who is in the room and their roles")

    role = with_room("role", "Set someone's role (makes an open room members-only)")
    role.add_argument("person")
    role.add_argument("role", choices=["viewer", "editor", "owner", "none"])
    role.add_argument("--as", dest="as_", required=True)

    checkout = with_room("checkout", "Copy the room's files into an empty directory")
    checkout.add_argument("directory")

    push = sub.add_parser("push", help="Propose what you changed in a checkout")
    push.add_argument("directory")
    push.add_argument("-m", "--message", default="")
    push.add_argument("--as", dest="as_", required=True)
    push.add_argument("--accept", action="store_true", help="Accept it straight away")

    return p


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = globals().get(f"cmd_{args.subcommand}") if args.subcommand else None
    if handler is None:
        parser.print_help()
        sys.exit(1)
    try:
        asyncio.run(handler(args))
    except KeyboardInterrupt:
        pass
    except (KeyError, ValueError, FileExistsError, PermissionError) as exc:
        print(_err(str(exc).strip("'\"")))
        sys.exit(1)


if __name__ == "__main__":
    main()
