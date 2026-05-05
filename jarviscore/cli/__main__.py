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
    else:
        print(f"Unknown command: {command}")
        print("\nAvailable commands: init, check, smoketest, nexus, memory, atom")
        sys.exit(1)


if __name__ == '__main__':
    main()
