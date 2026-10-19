"""
jarviscore room — rooms from a terminal, for developers and operators.

Usage:
    jarviscore room create launch --from ./site --as alice
    jarviscore room status launch --as alice
    jarviscore room watch launch --as alice              # live feed; Ctrl-C to stop
    jarviscore room ask launch "Add a pricing page" --as alice
    jarviscore room diff launch p-1a2b3c4d --as alice
    jarviscore room accept launch p-1a2b3c4d --as bob
    jarviscore room reject launch p-1a2b3c4d "Prices are wrong" --as bob [--redo]
    jarviscore room release launch p-1a2b3c4d --as alice
    jarviscore room checkout launch ./my-copy --as alice
    jarviscore room push ./my-copy -m "Tighter copy" --as alice [--accept]
    jarviscore room members launch
    jarviscore room audit launch --days 7 [--json]
    jarviscore room caps --usd-per-month 200               # everyone in the tenant
    jarviscore room caps alice --tokens-per-day 2000000    # one person, and their usage
    jarviscore room role launch bob editor --as alice
    jarviscore room visibility launch tenant --as alice
    jarviscore room connectors launch google_drive --as alice
    jarviscore room slack launch --channel C0123ABC --seed 10.0.0.5:7949

Rooms live in the mesh's Redis (REDIS_URL or --redis-url), in a tenant
(JARVISCORE_TENANT or --tenant; default "default"). This tool acts with the
access of whoever holds that Redis URL: ``--as`` names the person an action
is recorded for and whose room role is checked, but it is not a login. People
use rooms through your product or a chat surface, where they are authenticated.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _ok(msg: str) -> str: return f"\033[32m✓\033[0m  {msg}"
def _err(msg: str) -> str: return f"\033[31m✗\033[0m  {msg}"


def _room(args, *, existing=True):
    from jarviscore.room import Room

    room = Room.open(args.room, tenant=args.tenant, redis_url=args.redis_url)
    if existing and not room.exists():
        raise KeyError(f"Room {args.room!r} does not exist in {args.tenant}")
    return room


def _person(args, room):
    """The person ``--as`` names, in the room's tenant."""
    from jarviscore.auth.people import Person

    known = room.identities.get(room.tenant, args.as_)
    return known or room.identities.register(Person(room.tenant, args.as_, args.as_))


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
    room = _room(args, existing=False)
    files = _read_dir(args.from_dir) if args.from_dir else {}
    head = await room.ensure(files, by=_person(args, room))
    print(_ok(f"Room {room.id} at v{head.version} with {len(files)} files; {args.as_} owns it. "
              "It is private: add people with 'jarviscore room role'."))


async def cmd_status(args):
    room = _room(args)
    me = _person(args, room)
    room.require(me, "viewer", "see the room")
    head = room.head()
    snapshot = await room.snapshot()
    print(f"{room.id}  v{head.version}  {len(snapshot.entries)} files  "
          f"(last change by {room.name_of(head.updated_by) if head.updated_by else 'unknown'})")
    proposals = room.proposals("open")
    if not proposals:
        print("No open proposals.")
    for p in proposals:
        if not room.visible_to(me, p):
            print(f"  ▲ {p.id}  held for {room.name_of(p.held_for)}")
            continue
        held = "  (held for you)" if p.held_for else ""
        print(f"  ▲ {p.id}  by {p.author}" + (f" for {room.name_of(p.asked_by)}" if p.asked_by else "")
              + f"  on v{p.base_version}  {len(p.changes)} files  {p.title}{held}")


async def cmd_watch(args):
    from jarviscore.room.feed import RoomFeed, stamp

    room = _room(args)
    me = _person(args, room)
    room.require(me, "viewer", "follow the room")
    feed = RoomFeed(room)
    if args.new:
        feed.skip_history()
    while True:
        for item in feed.poll():
            text = item.withheld if item.held_for and item.held_for != me.id else item.text
            print(f"{stamp(item.at)}  {text}", flush=True)
        if args.once:
            return
        await asyncio.sleep(args.interval)


async def cmd_diff(args):
    room = _room(args)
    me = _person(args, room)
    proposal = room.proposal(args.proposal)
    if not room.visible_to(me, proposal):
        raise PermissionError(f"{args.proposal} is not visible to {args.as_}")
    print(f"{proposal.id}  {proposal.status}  by {proposal.author}"
          + (f" for {room.name_of(proposal.asked_by)}" if proposal.asked_by else "")
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
        head = await room.accept(args.proposal, by=_person(args, room))
    except RoomConflict as exc:
        print(_err(f"Not accepted: {', '.join(exc.paths)} changed since {args.proposal} was made."))
        print("   Ask for it again on the current files, or check out, merge by hand, and push.")
        sys.exit(1)
    print(_ok(f"{args.proposal} accepted → v{head.version}"))


async def cmd_reject(args):
    room = _room(args)
    await room.reject(args.proposal, by=_person(args, room), reason=args.reason)
    print(_ok(f"{args.proposal} rejected"))
    if args.redo:
        proposal = room.proposal(args.proposal)
        await _ask(args, room, proposal.title or args.reason, revision_of=args.proposal)


async def cmd_release(args):
    room = _room(args)
    room.release(args.proposal, by=_person(args, room))
    print(_ok(f"{args.proposal} released to the room for review"))


async def cmd_members(args):
    room = _room(args)
    settings = room.settings()
    if settings.get("visibility") == "tenant":
        print(f"Everyone in {room.tenant} can see {room.id}, as {settings.get('tenant_role')}.")
    else:
        print(f"{room.id} is private to its members.")
    order = ["viewer", "editor", "owner"]
    for person, role in sorted(room.members().items(), key=lambda m: (-order.index(m[1]), m[0])):
        print(f"  {role:<7} {room.name_of(person)}" + (f"  ({person})" if room.name_of(person) != person else ""))
    shared = settings.get("shared_connectors") or []
    print(f"Shared systems: {', '.join(shared) if shared else 'none'}")


async def cmd_role(args):
    from jarviscore.auth.people import Person

    room = _room(args)
    who = room.identities.get(room.tenant, args.person) or Person(room.tenant, args.person, args.person)
    role = None if args.role == "none" else args.role
    room.set_role(who, role, by=_person(args, room))
    print(_ok(f"{args.person}: {role or 'removed'} in {room.id}"))


async def cmd_visibility(args):
    room = _room(args)
    room.set_visibility(args.visibility, by=_person(args, room), tenant_role=args.tenant_role)
    print(_ok(f"{room.id} is now visible to " + (
        f"everyone in {room.tenant} ({args.tenant_role})" if args.visibility == "tenant" else "its members only")))


async def cmd_connectors(args):
    room = _room(args)
    room.set_shared_connectors(args.providers, by=_person(args, room))
    print(_ok(f"Shared systems in {room.id}: {', '.join(args.providers) or 'none'}"))


async def cmd_audit(args):
    import time

    room = _room(args)
    records = room.audit(since=time.time() - args.days * 86400 if args.days else 0.0)
    if args.json:
        for record in records:
            print(json.dumps(record, default=str))
        return
    for r in records:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r["at"]))
        who = r.get("by_name") or r.get("by") or "-"
        line = f"{stamp}  {who:<18} {r['action']:<20} {r.get('target', '')}  {r.get('detail', '')}"
        if r.get("held_for"):
            line += f"  [held for {room.name_of(r['held_for'])}]"
        if r.get("sources"):
            line += "  used: " + ", ".join(f"{s['provider']} as {s['person'] or 'the deployment'}"
                                           for s in r["sources"])
        if r.get("usage"):
            line += f"  ({r['usage']['tokens']:,} tokens, ${r['usage']['usd']:.4f})"
        print(line)


async def cmd_caps(args):
    from jarviscore.auth.spending import Spending

    spending = Spending(_store(args))
    changes = {k: v for k, v in (("tokens_per_day", args.tokens_per_day), ("tokens_per_month", args.tokens_per_month),
                                 ("usd_per_day", args.usd_per_day), ("usd_per_month", args.usd_per_month))
               if v is not None}
    for name in args.clear or []:
        changes[name.replace("-", "_")] = None
    if changes:
        spending.set_caps(args.tenant, person=args.person or "", **changes)
    who = f"{args.tenant}/{args.person}" if args.person else f"{args.tenant}/*"
    caps = spending.caps_for(who)   # "tenant/*" names no person: the tenant's own caps
    print(f"Caps for {'everyone in ' + args.tenant if not args.person else who}: "
          + (", ".join(f"{k}={v}" for k, v in vars(caps).items() if v is not None) or "none"))
    if args.person:
        for period, used in spending.usage(who).items():
            print(f"  {period} {used['period']}: {used['tokens']:,} tokens, ${used['usd']:.4f}, {used['calls']} calls")


def _store(args):
    import redis as redis_lib

    from jarviscore.storage.redis_store import RedisContextStore

    return RedisContextStore(client=redis_lib.Redis.from_url(_mesh_redis(args), decode_responses=True))


async def cmd_checkout(args):
    room = _room(args)
    head = await room.checkout(args.directory, by=_person(args, room))
    print(_ok(f"{room.id} v{head.version} checked out to {args.directory}"))
    print(f"   Edit there, then: jarviscore room push {args.directory} -m \"what you did\" --as {args.as_}")


async def cmd_push(args):
    from jarviscore.room import RoomConflict
    from jarviscore.room.room import CHECKOUT_MARKER

    marker = Path(args.directory) / CHECKOUT_MARKER
    if not marker.exists():
        print(_err(f"{args.directory} is not a room checkout"))
        sys.exit(1)
    checkout = json.loads(marker.read_text())
    args.room = checkout["room"]
    args.tenant = checkout.get("tenant", args.tenant)
    room = _room(args)
    me = _person(args, room)
    proposal = await room.push(args.directory, by=me, title=args.message or "")
    if proposal is None:
        print("Nothing changed.")
        return
    print(_ok(f"{proposal.id} proposed ({len(proposal.changes)} files)"))
    if args.accept:
        try:
            head = await room.accept(proposal.id, by=me)
        except RoomConflict as exc:
            print(_err(f"Not accepted: {', '.join(exc.paths)} changed in the room meanwhile."))
            sys.exit(1)
        print(_ok(f"accepted → v{head.version}"))


async def cmd_ask(args):
    await _ask(args, _room(args), args.goal)


async def _ask(args, room, goal, revision_of=""):
    """Ask the mesh's agents to do the work, as the person ``--as`` names."""
    from jarviscore import Mesh
    from jarviscore.room import Room

    mesh = Mesh(config={"redis_url": _mesh_redis(args), "p2p_enabled": False})
    await mesh.start()
    try:
        bound = Room.for_mesh(mesh, room.id, tenant=room.tenant)
        print(f"Asked. Follow along with: jarviscore room watch {room.id} --as {args.as_}")
        asked = await bound.ask(goal, asked_by=_person(args, bound), revision_of=revision_of,
                                timeout=args.timeout)
        if asked.proposal:
            held = " (held for you: it used your own access; release it to share it)" if asked.held_for else ""
            print(_ok(f"{asked.proposal.id} to review{held}: "
                      f"jarviscore room diff {room.id} {asked.proposal.id} --as {args.as_}"))
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


async def cmd_slack(args):
    """Serve the room in a Slack channel: a RoomAgent talks with the people there."""
    from jarviscore import Mesh
    from jarviscore.human import HumanAgent
    from jarviscore.room import Room, RoomAgent
    from jarviscore.room.slack import SLACK_API, SlackApi, SlackApp, SlackError

    # The room's conversation remembers by room (with Athena configured).
    config = {"redis_url": _mesh_redis(args), "p2p_enabled": False, "memory_scope_field": "room_id"}
    if args.seed or args.port:
        # On the mesh's transport, planners and agents find the room's people.
        config.update(p2p_enabled=True, bind_host=args.host, bind_port=args.port or 7961,
                      node_name=f"slack-{args.room}")
        if args.seed:
            config["seed_nodes"] = args.seed
    mesh = Mesh(config=config)
    agent = mesh.add(RoomAgent)
    agent.ask_options = {"timeout": args.timeout}
    capabilities = [c.strip() for c in args.capabilities.split(",") if c.strip()]
    if capabilities:
        # A step the agents route to people is asked in the room, in the work's thread.
        mesh.add(HumanAgent(
            args.people, capabilities, channel=None,
            description=(f"The people of the {args.room} room: they answer, confirm, approve "
                         "or decide in the room's chat. Answers take minutes, not seconds."),
        ))
    await mesh.start()
    if config["p2p_enabled"] and "peer_swim" not in mesh.capabilities:
        print(_err("Could not join the mesh transport; check --seed/--host/--port and the logs."))
        await mesh.stop()
        sys.exit(1)
    try:
        room = Room.for_mesh(mesh, args.room, tenant=args.tenant)
        room.head()
        api = await SlackApi.through_nexus(mesh, api_url=os.environ.get("SLACK_API_URL", SLACK_API))
        slack = SlackApp(agent, tenant=args.tenant, api=api)
        slack.connect(room, args.channel)
        try:
            await slack.start()
        except (SlackError, RuntimeError) as exc:
            print(_err(f"Could not reach Slack: {exc}"))
            print("   Connect the workspace's bot (slack) and app-level (slack_app) tokens in Nexus;")
            print("   see the Rooms in Slack guide. Check the bot is in the channel.")
            sys.exit(1)
        print(_ok(f"Room {room.id} is in Slack channel {args.channel}. Ctrl-C to stop."))
        await slack.run()
    finally:
        await mesh.stop()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jarviscore room", description="Work together in a shared room")
    p.add_argument("--redis-url", default=None, help="Redis shared by the mesh (default: REDIS_URL)")
    p.add_argument("--tenant", default=os.environ.get("JARVISCORE_TENANT", "default"),
                   help="Tenant the room belongs to (default: JARVISCORE_TENANT or 'default')")
    sub = p.add_subparsers(dest="subcommand")

    def with_room(name, help_text, *, person=True, required=True):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("room")
        if person:
            cmd.add_argument("--as", dest="as_", required=required,
                             help="The person this is done as (their room role applies)")
        return cmd

    create = with_room("create", "Open a private room, optionally with the files of a directory")
    create.add_argument("--from", dest="from_dir", default=None)

    with_room("status", "The room's version and open proposals")

    watch = with_room("watch", "Live feed of what happens in the room")
    watch.add_argument("--new", action="store_true", help="Only what happens from now on")
    watch.add_argument("--once", action="store_true", help="Print what has happened and exit")
    watch.add_argument("--interval", type=float, default=1.0)

    ask = with_room("ask", "Ask the mesh's agents to do something in the room")
    ask.add_argument("goal")
    ask.add_argument("--timeout", type=float, default=1800)

    diff = with_room("diff", "What a proposal changes")
    diff.add_argument("proposal")

    accept = with_room("accept", "Merge a proposal into the room")
    accept.add_argument("proposal")

    reject = with_room("reject", "Turn a proposal down with a reason")
    reject.add_argument("proposal")
    reject.add_argument("reason")
    reject.add_argument("--redo", action="store_true", help="Ask the agents to redo it with your reason")
    reject.add_argument("--timeout", type=float, default=1800)

    release = with_room("release", "Release work held for you (it used your own access) to the room")
    release.add_argument("proposal")

    with_room("members", "Who can see the room, their roles, and its shared systems", person=False)

    role = with_room("role", "Give someone a role in the room, or remove them (owners only)")
    role.add_argument("person")
    role.add_argument("role", choices=["viewer", "editor", "owner", "none"])

    visibility = with_room("visibility", "Who can see the room (owners only)")
    visibility.add_argument("visibility", choices=["members", "tenant"])
    visibility.add_argument("--tenant-role", default="editor", choices=["viewer", "editor"],
                            help="The role everyone in the tenant gets when it is 'tenant'")

    connectors = with_room("connectors", "Systems whose data the whole room may see (owners only)")
    connectors.add_argument("providers", nargs="*", help="Nexus providers, e.g. google_drive; none to clear")

    audit = with_room("audit", "Everything done in the room: who, what, why, with whose access, at what cost",
                      person=False)
    audit.add_argument("--days", type=float, default=0, help="Only the last N days")
    audit.add_argument("--json", action="store_true", help="One JSON record per line")

    caps = sub.add_parser("caps", help="Spending caps for a tenant, or one person in it, and their usage")
    caps.add_argument("person", nargs="?", default="", help="A person's id (default: everyone in the tenant)")
    caps.add_argument("--tokens-per-day", type=int)
    caps.add_argument("--tokens-per-month", type=int)
    caps.add_argument("--usd-per-day", type=float)
    caps.add_argument("--usd-per-month", type=float)
    caps.add_argument("--clear", nargs="*", choices=["tokens-per-day", "tokens-per-month", "usd-per-day",
                                                     "usd-per-month"], help="Remove these caps")

    checkout = with_room("checkout", "Copy the room's files into an empty directory")
    checkout.add_argument("directory")

    push = sub.add_parser("push", help="Propose what you changed in a checkout")
    push.add_argument("directory")
    push.add_argument("-m", "--message", default="")
    push.add_argument("--as", dest="as_", required=True)
    push.add_argument("--accept", action="store_true", help="Accept it straight away")

    slack = with_room("slack", "Serve the room in a Slack channel (Slack connected through Nexus)",
                      person=False)
    slack.add_argument("--channel", required=True, help="Slack channel id, e.g. C0123ABC")
    slack.add_argument("--people", default="team",
                       help="Name the room's people go by on the mesh (default: team)")
    slack.add_argument("--capabilities", default="",
                       help="What the room's people do for agents, e.g. approval,review; with none, "
                            "agents still ask people when they need them")
    slack.add_argument("--seed", default=None,
                       help="host:port of a node on the mesh, so planners and agents find the people")
    slack.add_argument("--host", default="127.0.0.1", help="Address to join the mesh on")
    slack.add_argument("--port", type=int, default=0, help="Port to join the mesh on (default 7961)")
    slack.add_argument("--timeout", type=float, default=1800, help="Seconds each piece of work may take")
    return p


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = globals().get(f"cmd_{args.subcommand}") if args.subcommand else None
    if handler is None:
        parser.print_help()
        sys.exit(1)
    from jarviscore.auth.people import IdentityError
    from jarviscore.room import RoomPermissionError

    try:
        asyncio.run(handler(args))
    except KeyboardInterrupt:
        pass
    except (KeyError, ValueError, FileExistsError, PermissionError, RoomPermissionError,
            IdentityError) as exc:
        print(_err(str(exc).strip("'\"")))
        sys.exit(1)


if __name__ == "__main__":
    main()
