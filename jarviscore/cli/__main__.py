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
    jarviscore human join alice --capabilities review --seed HOST:PORT
    jarviscore room watch launch
"""


def main():
    import sys

    from ._commands import LEGACY_BY_NAME, run_legacy

    # Legacy commands get raw argv and never need Typer.
    argv = sys.argv[1:]
    if argv and argv[0] in LEGACY_BY_NAME:
        run_legacy(argv[0], argv[1:])
        return
    from .app import main as app_main
    app_main()


if __name__ == '__main__':
    main()
