"""
CLI entry point for JarvisCore commands.

Usage:
    python -m jarviscore.cli.check
    python -m jarviscore.cli.smoketest
"""

import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m jarviscore.cli <command>")
        print("\nAvailable commands:")
        print("  check      - Health check and validation")
        print("  smoketest  - Quick smoke test")
        sys.exit(1)

    command = sys.argv[1]
    sys.argv = [sys.argv[0]] + sys.argv[2:]  # Remove command from argv

    if command == 'check':
        from .check import main as check_main
        check_main()
    elif command == 'smoketest':
        from .smoketest import main as smoketest_main
        smoketest_main()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

if __name__ == '__main__':
    main()
