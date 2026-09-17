from pathlib import Path

from jarviscore.cli import atom as atom_cli


def _atom_root(tmp_path: Path, source: str) -> Path:
    root = tmp_path / "atoms"
    bundle = root / "demo"
    bundle.mkdir(parents=True)
    (bundle / "__init__.py").write_text("")
    (bundle / "demo_list_items.py").write_text(source)
    return root


def test_dry_run_accepts_the_runtime_nexus_call_contract(tmp_path, monkeypatch, capsys):
    root = _atom_root(tmp_path, '''
async def demo_list_items(limit: int = 10) -> dict:
    """List items. https://example.test/docs/items"""
    response = await nexus_call("GET", "https://example.test/items", params={"limit": limit})
    return {"success": response["ok"], "data": response.get("json")}
''')
    monkeypatch.setattr(atom_cli, "_atoms_root", lambda: root)

    assert atom_cli.run_dry_run("demo", "demo_list_items") is True
    output = capsys.readouterr().out
    assert "async nexus_call credential boundary" in output
    assert "auth_info" not in output


def test_dry_run_rejects_legacy_auth_info_atoms(tmp_path, monkeypatch, capsys):
    root = _atom_root(tmp_path, '''
def demo_list_items(auth_info: dict, limit: int = 10) -> dict:
    """List items."""
    return {"success": True, "limit": limit}
''')
    monkeypatch.setattr(atom_cli, "_atoms_root", lambda: root)

    assert atom_cli.run_dry_run("demo", "demo_list_items") is False
    assert "migrate authentication to nexus_call" in capsys.readouterr().out
