"""The active catalog entry points point to installed data, not snapshot totals."""

import re
import sys
from pathlib import Path

import pytest

from jarviscore.cli import atom

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_CATALOG_PAGES = (
    "README.md",
    "jarviscore/docs/index.md",
    "jarviscore/docs/llms.txt",
    "jarviscore/docs/guides/nexus.md",
    "jarviscore/docs/guides/integrations.md",
    "jarviscore/docs/guides/testing-atoms.md",
    "jarviscore/docs/concepts/nexus.md",
    "jarviscore/docs/reference/cli.md",
    "jarviscore/skills/jarviscore/SKILL.md",
)

CATALOG_TOTAL = re.compile(
    r"\b\d[\d,]*\+?\s+"
    r"(?:(?:built-in|system|typed|discrete,?|versioned|prebuilt|third-party)\s+)*"
    r"(?:services?|integrations?|bundles?|providers?|atoms?|actions?|APIs)\b",
    re.IGNORECASE,
)

@pytest.mark.parametrize("path", ACTIVE_CATALOG_PAGES)
def test_catalog_entry_point_uses_cli_guidance(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    assert "jarviscore atom list" in text
    if path != "jarviscore/docs/reference/cli.md":
        assert re.search(r"reference/cli(?:\.md|/)#atom-list", text)
    else:
        assert "### atom list" in text


@pytest.mark.parametrize("path", ACTIVE_CATALOG_PAGES)
def test_catalog_entry_point_does_not_advertise_snapshot_totals(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    # Scoped to these catalog pages, not historical changelogs or all docs.
    # Remove inline formatting so bold totals cannot evade the check.
    claims = CATALOG_TOTAL.findall(text.replace("*", "").replace("`", ""))
    assert not claims, f"{path}: replace {claims} with installed-catalog guidance"


def test_bundle_summary_tables_do_not_duplicate_per_provider_counts():
    text = (ROOT / "jarviscore/docs/guides/integrations.md").read_text(encoding="utf-8")
    rows = "\n".join(line for line in text.splitlines() if line.startswith("|"))
    assert not re.search(r"\(\d[\d,]*\+?\)|\|\s*\d[\d,]*\+?\s*\|", rows)


@pytest.mark.parametrize(
    "claim",
    (
        "46 service integrations",
        "150 built-in system bundles",
        "237+ prebuilt actions",
        "1224 discrete, versioned atoms",
        "1,218 typed atoms",
        "999 provider bundles",
        "46 third-party APIs",
    ),
)
def test_snapshot_guard_is_not_tied_to_a_particular_catalog_total(claim):
    assert CATALOG_TOTAL.search(claim)


@pytest.mark.parametrize("bundle", (None, "slack"))
def test_documented_list_command_reports_the_installed_catalog(bundle, monkeypatch, capsys):
    """Exercise the documented CLI without seeding, credentials, or fixed totals."""
    root = ROOT / "jarviscore/integrations/atoms"
    assert atom._atoms_root().resolve() == root.resolve()
    bundles = (
        [root / bundle]
        if bundle
        else sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_"))
    )
    expected = {
        path.name: sorted(p.stem for p in path.glob("*.py") if p.stem != "__init__")
        for path in bundles
    }
    monkeypatch.setattr(
        sys, "argv", ["jarviscore atom", "list"] + (["--bundle", bundle] if bundle else [])
    )
    atom.main()
    output = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    total_atoms = sum(len(names) for names in expected.values())
    assert f"{len(expected)} bundles  ·  {total_atoms} atoms total" in output
    for bundle_name, atoms in expected.items():
        assert f"  {bundle_name}  ({len(atoms)} atoms)" in output
        for atom_name in atoms:
            assert f"    · {atom_name}\n" in output