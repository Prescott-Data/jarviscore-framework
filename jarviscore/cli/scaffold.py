"""
JarvisCore Project Initialization CLI

Scaffolds a new JarvisCore project with configuration and examples.

Usage:
    python -m jarviscore.cli.scaffold              # Create .env from template
    python -m jarviscore.cli.scaffold --examples   # Also copy example files
    python -m jarviscore.cli.scaffold --force      # Overwrite existing files
"""

import sys
import shutil
from pathlib import Path
from importlib import resources
import argparse


def get_data_path() -> Path:
    """Get path to the data directory within the package."""
    # Python 3.9+ approach using importlib.resources
    try:
        # resources.files() returns a Traversable, convert to Path
        data_path = resources.files('jarviscore.data')
        return Path(str(data_path))
    except (TypeError, AttributeError):
        # Fallback for older Python or if resources.files doesn't work
        import jarviscore.data
        return Path(jarviscore.data.__file__).parent


def copy_env_example(dest_dir: Path, force: bool = False) -> bool:
    """
    Copy .env.example to destination directory.

    Args:
        dest_dir: Destination directory
        force: Overwrite if exists

    Returns:
        True if copied, False if skipped
    """
    data_path = get_data_path()
    src = data_path / '.env.example'
    dest = dest_dir / '.env.example'

    if not src.exists():
        print(f"✗ Source file not found: {src}")
        return False

    if dest.exists() and not force:
        print(f"⚠ {dest.name} already exists (use --force to overwrite)")
        return False

    shutil.copy2(src, dest)
    print(f"✓ Created {dest.name}")
    return True


def copy_examples(dest_dir: Path, force: bool = False) -> bool:
    """
    Copy example files to destination directory.

    Args:
        dest_dir: Destination directory
        force: Overwrite if exists

    Returns:
        True if copied, False if skipped
    """
    data_path = get_data_path()
    src = data_path / 'examples'
    dest = dest_dir / 'examples'

    if not src.exists():
        print(f"✗ Examples directory not found: {src}")
        return False

    if dest.exists() and not force:
        print(f"⚠ examples/ directory already exists (use --force to overwrite)")
        return False

    if dest.exists() and force:
        shutil.rmtree(dest)

    shutil.copytree(src, dest)

    # Count files copied
    file_count = sum(1 for _ in dest.glob('*.py'))
    print(f"✓ Created examples/ directory ({file_count} files)")
    return True


def print_header():
    """Print initialization header."""
    print("\n" + "=" * 60)
    print("  JarvisCore Project Initialization")
    print("=" * 60 + "\n")


def print_next_steps(env_created: bool, examples_created: bool):
    """Print next steps after initialization."""
    print("\n" + "=" * 60)
    print("  Next Steps")
    print("=" * 60)

    steps = []

    if env_created:
        steps.append("1. Copy and configure your environment:\n"
                    "   cp .env.example .env\n"
                    "   # Edit .env and add your LLM API key")

    steps.append(f"{'2' if env_created else '1'}. Validate your setup:\n"
                "   python -m jarviscore.cli.check --validate-llm")

    steps.append(f"{'3' if env_created else '2'}. Run smoke test:\n"
                "   python -m jarviscore.cli.smoketest")

    if examples_created:
        steps.append(f"{'4' if env_created else '3'}. Try an example:\n"
                    "   python examples/calculator_agent_example.py for AutoAgent Profile or python examples/customagent_p2p_example.py ")

    for step in steps:
        print(f"\n{step}")

    print()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Initialize a new JarvisCore project'
    )
    parser.add_argument(
        '--examples',
        action='store_true',
        help='Also copy example agent files'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Overwrite existing files'
    )
    parser.add_argument(
        '--dir',
        type=str,
        default='.',
        help='Target directory (default: current directory)'
    )

    args = parser.parse_args()
    dest_dir = Path(args.dir).resolve()

    print_header()
    print(f"Initializing in: {dest_dir}\n")

    # Ensure destination exists
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Copy files
    env_created = copy_env_example(dest_dir, args.force)

    examples_created = False
    if args.examples:
        examples_created = copy_examples(dest_dir, args.force)

    # Summary
    if env_created or examples_created:
        print_next_steps(env_created, examples_created)
        sys.exit(0)
    else:
        print("\n⚠ No files were created. Use --force to overwrite existing files.")
        sys.exit(1)


if __name__ == '__main__':
    main()
