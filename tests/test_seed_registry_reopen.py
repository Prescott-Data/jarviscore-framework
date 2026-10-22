"""Re-opening an already seeded registry must not re-parse unchanged atoms."""

import logging

from jarviscore.execution import atom_contract
from jarviscore.execution.code_registry import create_function_registry
from jarviscore.integrations.seed_registry import seed_registry


def test_unchanged_atoms_are_skipped_without_parsing(tmp_path, monkeypatch, caplog):
    registry = create_function_registry(str(tmp_path))
    assert registry.function_metadata, "the shipped catalogue should seed the registry"

    calls = []
    real = atom_contract.read_contract
    monkeypatch.setattr(atom_contract, "read_contract",
                        lambda *a, **k: calls.append(a) or real(*a, **k))
    report = seed_registry(registry, missing_only=True)
    assert report["registered"] == [] and calls == []
    assert len(report["skipped"]) == report["total_atoms"]

    with caplog.at_level(logging.WARNING, logger="jarviscore.execution.code_registry"):
        create_function_registry(str(tmp_path))
    assert "produced no functions" not in caplog.text
