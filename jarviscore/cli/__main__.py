"""
CLI entry point for JarvisCore commands.

Usage:
    jarviscore init                          # Scaffold new project (.env.example)
    jarviscore init --examples               # Also copy example files
    jarviscore check [--validate-llm]        # Health check
    jarviscore smoketest                     # Quick smoke test
    jarviscore nexus status
    jarviscore nexus up
    jarviscore nexus register github --client-id=... --client-secret=...
    jarviscore nexus list
    jarviscore nexus test github
    jarviscore memory init
    jarviscore atom test --bundle slack --mode dry-run
    jarviscore atom list
    jarviscore inspect                       # List recorded runs
    jarviscore inspect <workflow_id>         # Timeline for one run
    jarviscore verify [journal_dir]          # Check the journal of decisions and effects
    jarviscore policy check|review           # Check a control policy; review what strict mode refuses
    jarviscore replay [journal_dir] [run]    # Re-simulate recorded runs from the journal
    jarviscore evidence acme/u_1 [--export DIR]  # What agents did for a person (or acme/ for a tenant)
    jarviscore human join alice --capabilities review --seed HOST:PORT
    jarviscore room watch launch
"""

import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: jarviscore <command>")
        print("\nAvailable commands:")
        print("  init       - Scaffold a new project (.env.example + optional examples)")
        print("  check      - Health check and validation")
        print("  smoketest  - Quick smoke test")
        print("  nexus      - Manage Nexus auth (init, register, status, list, test)")
        print("  memory     - Manage Athena MemOS (init, status, context, search)")
        print("  atom       - Validate, test, and list integration atoms")
        print("  inspect    - Read recorded traces: what did my agents do?")
        print("  verify     - Check the journal: every record intact, every effect decided")
        print("  policy     - Check a control policy file; review what strict mode would refuse")
        print("  replay     - Re-simulate recorded agent runs from the journal, every effect stubbed")
        print("  evidence   - What agents did for a person or tenant; export it for their auditor")
        print("  human      - Join the mesh as a person (join, inbox, answer)")
        print("  room       - Work together on a shared workspace (ask, diff, accept, watch)")
        sys.exit(1)

    command = sys.argv[1]
    sys.argv = [sys.argv[0]] + sys.argv[2:]  # Remove command from argv

    if command == 'init':
        from .scaffold import main as scaffold_main
        scaffold_main()
    elif command == 'nexus':
        from .nexus import main as nexus_main
        nexus_main()
    elif command == 'memory':
        from .memory import run as memory_main
        memory_main()
    elif command == 'check':
        from .check import main as check_main
        check_main()
    elif command == 'smoketest':
        from .smoketest import main as smoketest_main
        smoketest_main()
    elif command == 'atom':
        from .atom import main as atom_main
        atom_main()
    elif command == 'inspect':
        from .inspect import main as inspect_main
        inspect_main()
    elif command == 'verify':
        from .verify import main as verify_main
        verify_main()
    elif command == 'policy':
        from .policy import main as policy_main
        policy_main()
    elif command == 'replay':
        from .replay import main as replay_main
        replay_main()
    elif command == 'evidence':
        from .evidence import main as evidence_main
        evidence_main()
    elif command == 'human':
        from .human import main as human_main
        human_main()
    elif command == 'room':
        from .room import main as room_main
        room_main()
    else:
        print(f"Unknown command: {command}")
        print("\nAvailable commands: init, check, smoketest, nexus, memory, atom, inspect, verify, policy, replay, evidence, human, room")
        sys.exit(1)


if __name__ == '__main__':
    main()
