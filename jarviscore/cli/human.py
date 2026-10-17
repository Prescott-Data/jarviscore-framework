"""
jarviscore human — put a person on the mesh.

Usage:
    jarviscore human join alice --capabilities review,approve --seed 10.0.0.5:7949
    jarviscore human join alice --capabilities review --inbox human_inbox   # answer from files
    jarviscore human inbox [--dir human_inbox]
    jarviscore human answer TASK_ID "Looks good, ship it"
    jarviscore human answer TASK_ID --reject "The numbers are wrong"

`join` starts a mesh node whose only agent is a HumanAgent for you. Other nodes
see you in their roster, route work for your capabilities to you, and you can
/ask any of them in return. With --inbox, tasks are written to files instead of
the terminal and answered with `jarviscore human answer`.
"""

import argparse
import asyncio
import sys


def _ok(msg: str) -> str: return f"\033[32m✓\033[0m  {msg}"
def _err(msg: str) -> str: return f"\033[31m✗\033[0m  {msg}"


async def _join(args) -> None:
    from jarviscore import Mesh
    from jarviscore.human import InboxChannel, TerminalChannel
    from jarviscore.profiles import HumanAgent

    capabilities = [c.strip() for c in args.capabilities.split(",") if c.strip()]
    config = {
        "p2p_enabled": True,
        "bind_host": args.host,
        "bind_port": args.port,
        "node_name": f"human-{args.name}",
    }
    if args.seed:
        config["seed_nodes"] = args.seed
    if args.redis_url:
        config["redis_url"] = args.redis_url

    channel = InboxChannel(args.inbox) if args.inbox else TerminalChannel()
    mesh = Mesh(config=config)
    mesh.add(HumanAgent(args.name, capabilities, channel=channel, description=args.describe))
    await mesh.start()
    if "peer_swim" not in mesh.capabilities:
        print(_err("Could not start the mesh transport; check --host/--port and the logs."))
        await mesh.stop()
        sys.exit(1)
    where = f"seed {args.seed}" if args.seed else f"{args.host}:{args.port} (others use this as --seed)"
    print(_ok(f"{args.name} joined the mesh via {where}"))
    if args.inbox:
        print(_ok(f"Tasks go to {args.inbox}/{args.name}/; answer with `jarviscore human answer`"))
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await mesh.stop()


def cmd_join(args) -> None:
    try:
        asyncio.run(_join(args))
    except KeyboardInterrupt:
        print("\nLeft the mesh.")


def cmd_inbox(args) -> None:
    from jarviscore.human import open_items

    items = open_items(args.dir)
    if not items:
        print("Nothing waiting.")
        return
    for item in items:
        origin = " · ".join(p for p in (item.get("capability"), item.get("asked_by")) if p)
        print(f"{item['id']}  for {item.get('for')}  ({origin})")
        print(f"  {item.get('task')}")
        for step, summary in (item.get("upstream") or {}).items():
            print(f"  ↳ {step}: {summary[:200]}")


def cmd_answer(args) -> None:
    from jarviscore.human import answer_item

    decision, response = "answered", args.response
    for name, flag in (("approved", args.approve), ("rejected", args.reject), ("declined", args.decline)):
        if flag is not None:
            decision, response = name, flag or args.response
    if decision == "answered" and not response:
        print(_err("Give an answer, or use --approve / --reject / --decline"))
        sys.exit(1)
    try:
        answer_item(args.task_id, decision, response or "", by=args.by or "", directory=args.dir)
    except LookupError as exc:
        print(_err(str(exc)))
        sys.exit(1)
    print(_ok(f"{args.task_id}: {decision}"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jarviscore human", description="Put a person on the mesh")
    sub = p.add_subparsers(dest="subcommand")

    join = sub.add_parser("join", help="Join the mesh as a person")
    join.add_argument("name", help="Your role on the mesh, e.g. alice")
    join.add_argument("--capabilities", required=True,
                      help="Comma-separated, e.g. review,approve. 'human' is always added")
    join.add_argument("--seed", default=None, help="host:port of any node already on the mesh")
    join.add_argument("--host", default="127.0.0.1",
                      help="Address to listen on (default 127.0.0.1; use a LAN/VPN address to be reachable)")
    join.add_argument("--port", type=int, default=7960,
                      help="SWIM port to listen on (default 7960); messages use this port + 1000")
    join.add_argument("--redis-url", default=None,
                      help="Shared Redis, to claim workflow steps from the ledger")
    join.add_argument("--inbox", default=None, help="Write tasks to this directory instead of the terminal")
    join.add_argument("--describe", default=None, help="How planners should think of you")

    inbox = sub.add_parser("inbox", help="List tasks waiting in an inbox directory")
    inbox.add_argument("--dir", default="human_inbox")

    answer = sub.add_parser("answer", help="Answer a task in an inbox directory")
    answer.add_argument("task_id")
    answer.add_argument("response", nargs="?", default="")
    group = answer.add_mutually_exclusive_group()
    group.add_argument("--approve", nargs="?", const="", metavar="NOTE", help="Sign it off")
    group.add_argument("--reject", nargs="?", const="", metavar="WHY", help="Refuse it; the step fails")
    group.add_argument("--decline", nargs="?", const="", metavar="WHY", help="You will not or cannot do it")
    answer.add_argument("--by", default=None, help="Who is answering (defaults to the task's owner)")
    answer.add_argument("--dir", default="human_inbox")
    return p


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {"join": cmd_join, "inbox": cmd_inbox, "answer": cmd_answer}
    if args.subcommand not in handlers:
        parser.print_help()
        sys.exit(1)
    handlers[args.subcommand](args)


if __name__ == "__main__":
    main()
