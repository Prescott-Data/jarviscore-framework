"""The nexus CLI's raw Gateway calls carry NEXUS_GATEWAY_API_KEY like NexusClient does."""

from jarviscore.cli.nexus import _gateway_api_key, _gateway_headers, _gateway_url


def test_key_from_environment(monkeypatch):
    monkeypatch.setenv("NEXUS_GATEWAY_API_KEY", "env-key")
    assert _gateway_api_key() == "env-key"
    assert _gateway_headers() == {"X-API-Key": "env-key"}


def test_key_from_dotenv_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("NEXUS_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("NEXUS_GATEWAY_URL", raising=False)
    (tmp_path / ".env").write_text(
        'NEXUS_GATEWAY_URL="https://gw.example.com"\nNEXUS_GATEWAY_API_KEY=dotenv-key\n'
    )
    monkeypatch.chdir(tmp_path)
    assert _gateway_url() == "https://gw.example.com"
    assert _gateway_api_key() == "dotenv-key"


def test_no_key_means_no_header(monkeypatch, tmp_path):
    monkeypatch.delenv("NEXUS_GATEWAY_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    assert _gateway_api_key() is None
    assert _gateway_headers() == {}
