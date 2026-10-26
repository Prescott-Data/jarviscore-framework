"""Every published claim names evidence that exists; a claim without it fails the build."""
import ast
import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLAIMS = sorted((ROOT / "claims").glob("*.yaml"))
REQUIRED = {"id", "claim", "scope", "assumptions", "not_claimed", "evidence", "published"}


def _test_names(path: pathlib.Path) -> set:
    tree = ast.parse(path.read_text())
    return {
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    }


def test_there_are_claims():
    assert CLAIMS


@pytest.mark.parametrize("path", CLAIMS, ids=lambda p: p.stem)
def test_a_claim_states_its_scope_limits_and_evidence(path):
    claim = yaml.safe_load(path.read_text())

    assert REQUIRED <= set(claim), f"{path.name} lacks {REQUIRED - set(claim)}"
    assert claim["id"] == path.stem
    assert claim["claim"].strip() and claim["assumptions"] and claim["not_claimed"] and claim["evidence"]


@pytest.mark.parametrize("path", CLAIMS, ids=lambda p: p.stem)
def test_every_piece_of_evidence_exists(path):
    claim = yaml.safe_load(path.read_text())
    missing = []
    for item in claim["evidence"]:
        file_part, _, name = item.partition("::")
        test_file = ROOT / file_part
        if not test_file.exists() or name not in _test_names(test_file):
            missing.append(item)

    assert missing == [], f"{path.name} names evidence that does not exist"
