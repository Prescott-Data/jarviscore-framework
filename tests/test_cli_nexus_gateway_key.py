"""The nexus CLI's raw Gateway calls carry NEXUS_GATEWAY_API_KEY like NexusClient does."""

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jarviscore.cli.atom import DEFAULT_NEXUS_URL, _resolve_nexus_url
from jarviscore.cli.nexus import _gateway_api_key, _gateway_headers, _gateway_open, _gateway_url


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


def test_dotenv_inline_comment_and_quotes_are_not_part_of_the_key(monkeypatch, tmp_path):
    monkeypatch.delenv("NEXUS_GATEWAY_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "# caller key for the Gateway\n"
        "NEXUS_GATEWAY_API_KEY=gw-secret   # inline comment\n"
        "OTHER='single quoted'\n"
    )
    monkeypatch.chdir(tmp_path)
    assert _gateway_api_key() == "gw-secret"
    assert _gateway_headers() == {"X-API-Key": "gw-secret"}


def test_dotenv_empty_value_means_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("NEXUS_GATEWAY_API_KEY", raising=False)
    (tmp_path / ".env").write_text("NEXUS_GATEWAY_API_KEY=\n")
    monkeypatch.chdir(tmp_path)
    assert _gateway_api_key() is None
    assert _gateway_headers() == {}


def test_environment_wins_over_dotenv(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("NEXUS_GATEWAY_API_KEY=from-file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEXUS_GATEWAY_API_KEY", "from-env")
    assert _gateway_api_key() == "from-env"


# ── Redirects never carry the key ──────────────────────────────────

@pytest.fixture
def redirecting_gateway():
    """A local server: /v1/providers answers 302 to /elsewhere; /elsewhere records what it sees."""
    seen = {"elsewhere": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/v1/providers":
                self.send_response(302)
                self.send_header("Location", "/elsewhere")
                self.end_headers()
            elif self.path == "/elsewhere":
                seen["elsewhere"].append(dict(self.headers))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({}).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", seen
    finally:
        server.shutdown()


def test_gateway_open_does_not_follow_redirects(redirecting_gateway):
    base, seen = redirecting_gateway
    req = urllib.request.Request(f"{base}/v1/providers", headers={"X-API-Key": "gw-secret"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        _gateway_open(req, timeout=5)
    assert exc.value.code == 302
    assert seen["elsewhere"] == [], "the redirect target must never receive the request"


def test_plain_urlopen_would_have_forwarded_the_key(redirecting_gateway):
    """Documents why _gateway_open exists: stdlib urlopen copies the header onto the redirect."""
    base, seen = redirecting_gateway
    req = urllib.request.Request(f"{base}/v1/providers", headers={"X-API-Key": "gw-secret"})
    urllib.request.urlopen(req, timeout=5).read()
    assert seen["elsewhere"] and seen["elsewhere"][0].get("X-Api-Key") == "gw-secret"


# ── atom test resolves the Gateway URL where it resolves the key ───

def test_atom_test_uses_dotenv_gateway_when_only_the_file_configures_it(monkeypatch, tmp_path):
    """File-only configuration: the key must go to the file's Gateway, never to localhost."""
    monkeypatch.delenv("NEXUS_GATEWAY_URL", raising=False)
    monkeypatch.delenv("NEXUS_GATEWAY_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "NEXUS_GATEWAY_URL=https://gw.example.com\nNEXUS_GATEWAY_API_KEY=gw-secret\n"
    )
    monkeypatch.chdir(tmp_path)
    assert _resolve_nexus_url(None) == "https://gw.example.com"
    assert _gateway_headers() == {"X-API-Key": "gw-secret"}


def test_atom_test_explicit_url_wins(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("NEXUS_GATEWAY_URL=https://gw.example.com\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEXUS_GATEWAY_URL", "https://env.example.com")
    assert _resolve_nexus_url("https://flag.example.com") == "https://flag.example.com"
    assert _resolve_nexus_url(None) == "https://env.example.com"


def test_atom_test_falls_back_to_localhost_when_nothing_is_configured(monkeypatch, tmp_path):
    monkeypatch.delenv("NEXUS_GATEWAY_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    assert _resolve_nexus_url(None) == DEFAULT_NEXUS_URL
