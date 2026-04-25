"""
CLI entry point for JarvisCore commands.

Usage:
    python -m jarviscore.cli check
    python -m jarviscore.cli smoketest
    python -m jarviscore.cli nexus status
    python -m jarviscore.cli nexus up
    python -m jarviscore.cli nexus register github --client-id=... --client-secret=...
    python -m jarviscore.cli nexus list
    python -m jarviscore.cli nexus test github
"""

import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: jarviscore <command>")
        print("\nAvailable commands:")
        print("  nexus      - Manage Nexus auth (init, register, status, list, test)")
        print("  memory     - Manage Athena MemOS (init, status, context, search)")
        print("  check      - Health check and validation")
        print("  smoketest  - Quick smoke test")
        sys.exit(1)

    command = sys.argv[1]
    sys.argv = [sys.argv[0]] + sys.argv[2:]  # Remove command from argv

    if command == 'nexus':
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
    else:
        print(f"Unknown command: {command}")
        print("\nAvailable commands: nexus, memory, check, smoketest")
        sys.exit(1)

if __name__ == '__main__':
    main()
