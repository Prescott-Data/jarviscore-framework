"""The Nexus stack JarvisCore ships is internally consistent.

JarvisCore used to carry a copy of the broker's schema, because the broker image
did not bundle its migrations. The copy drifted, and the drift surfaced as a
missing column during `nexus register`. From nexus-broker v0.3.0 the broker
applies its own migrations on boot, so the copy is gone and these tests keep it
that way.
"""

import base64
import pathlib
import re
import stat

import pytest

from jarviscore.nexus.providers import broker_name

DATA = pathlib.Path(__file__).resolve().parents[1] / "jarviscore/nexus/_data"
COMPOSE = DATA / "docker-compose.nexus.yml"

#: The release from which the broker carries and applies its own migrations.
SELF_MIGRATING_FROM = (0, 3, 0)


def compose_text():
    return COMPOSE.read_text(encoding="utf-8")


def pinned(service: str) -> str:
    found = re.search(rf"{service}:(\S+)", compose_text())
    assert found, f"no image pinned for {service}"
    tag = found.group(1)
    default = re.fullmatch(r"\$\{[A-Z_]+:-([^}]+)\}", tag)
    return default.group(1) if default else tag


class TestTheStackIsPinned:

    @pytest.mark.parametrize("service", ("nexus-broker", "nexus-gateway"))
    def test_images_are_not_moving_tags(self, service):
        """An upgrade should be a decision, not something that happens overnight."""
        tag = pinned(service)
        assert tag != "latest", f"{service} follows a moving tag"
        assert re.fullmatch(r"v\d+\.\d+\.\d+", tag), tag

    @pytest.mark.parametrize("service", ("nexus-broker", "nexus-gateway"))
    def test_the_pin_is_a_release_that_migrates_itself(self, service):
        version = tuple(int(part) for part in pinned(service).lstrip("v").split("."))
        assert version >= SELF_MIGRATING_FROM, (
            f"{service} is pinned below v0.3.0, where the broker started carrying "
            "its own migrations; a copy of the schema would be needed again"
        )


class TestTheSchemaBelongsToTheBroker:

    def test_no_copy_of_the_brokers_schema_is_shipped(self):
        strays = [p.name for p in DATA.glob("*.sql")]
        assert not strays, (
            f"{strays} reintroduces a copy of the broker's schema, which is what "
            "drifted from the image before v0.3.0"
        )

    def test_nothing_is_mounted_into_initdb(self):
        assert "docker-entrypoint-initdb.d" not in compose_text()


class TestTheStackStandsAlone:
    """A fresh install cannot depend on containers from another compose project."""

    def test_redis_is_shipped_with_the_stack(self):
        text = compose_text()
        assert "nexus-redis" in text
        assert "jarviscore-framework-redis-1" not in text

    def test_the_broker_is_told_where_it_lives(self):
        """Without BASE_URL the redirect_uri is relative and every provider rejects it."""
        assert "BASE_URL:" in compose_text()

    def test_ports_can_be_moved(self):
        """8080 is a popular port; a framework has to coexist with what is there."""
        assert "${NEXUS_BROKER_PORT:-8080}:8080" in compose_text()


class TestProviderNamesCrossTheSeam:

    @pytest.mark.parametrize("given,expected", [
        ("google_drive", "google-drive"),
        ("zoho_crm", "zoho-crm"),
        ("HubSpot", "hubspot"),
        ("github", "github"),
    ])
    def test_underscores_become_hyphens_for_the_broker(self, given, expected):
        assert broker_name(given) == expected


#: The first release whose Gateway can require an API key.
GATEWAY_AUTH_FROM = (0, 6, 0)


def service_block(service: str) -> str:
    text = compose_text()
    start = text.index(f"  {service}:\n")
    rest = text[start + 1:]
    following = re.search(r"\n  [a-z][a-z-]*:\n", rest)
    return rest[: following.start()] if following else rest


class TestNothingAnswersWithoutAKey:
    """With either service open, any caller that reaches the port can list
    connections and read back their decrypted credentials."""

    def test_the_broker_requires_its_api_key(self):
        broker = service_block("nexus-broker")
        assert re.search(r'API_KEY: "\$\{NEXUS_BROKER_API_KEY:\?', broker)
        assert 'REQUIRE_API_KEY: "true"' in broker

    def test_the_gateway_requires_an_api_key(self):
        gateway = service_block("nexus-gateway")
        assert 'GATEWAY_REQUIRE_API_KEY: "true"' in gateway
        assert re.search(r'GATEWAY_API_KEYS: "\$\{NEXUS_GATEWAY_API_KEY:\?', gateway)

    def test_the_gateway_can_require_a_key_at_the_pinned_release(self):
        version = tuple(int(part) for part in pinned("nexus-gateway").lstrip("v").split("."))
        assert version >= GATEWAY_AUTH_FROM

    def test_no_shared_placeholder_key(self):
        assert "dev-broker-api-key-change-in-prod" not in compose_text()

    def test_ports_listen_on_loopback_by_default(self):
        published = re.findall(r'- "([^"]+):\d+"', compose_text())
        assert published, "no published ports found"
        for mapping in published:
            assert mapping.startswith("${NEXUS_BIND_ADDRESS:-127.0.0.1}:"), mapping

    def test_the_gateway_is_told_where_the_broker_is(self):
        """The gateway reads BROKER_BASE_URL; BROKER_URL was never read."""
        gateway = service_block("nexus-gateway")
        assert "BROKER_BASE_URL: http://nexus-broker:8080" in gateway
        assert "BROKER_URL:" not in gateway
        assert "network_mode" not in compose_text()


class TestStackSecretsStayWithTheStack:

    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        for name in ("NEXUS_ENCRYPTION_KEY", "NEXUS_STATE_KEY",
                     "NEXUS_BROKER_API_KEY", "NEXUS_GATEWAY_API_KEY", "NEXUS_GATEWAY_PORT"):
            monkeypatch.delenv(name, raising=False)
        project = tmp_path / "project" / ".env"
        project.parent.mkdir()
        stack = tmp_path / "home" / ".jarviscore" / "nexus" / "stack.env"
        return project, stack

    @staticmethod
    def read(path):
        from jarviscore.cli.nexus import _read_env_file
        return _read_env_file(path)

    def test_a_fresh_setup_keeps_the_master_key_out_of_the_project(self, env):
        from jarviscore.cli.nexus import BROKER_ONLY_SECRETS, ensure_stack_secrets

        project, stack = env
        secrets, _ = ensure_stack_secrets(project, stack)

        project_values = self.read(project)
        for name in BROKER_ONLY_SECRETS:
            assert name not in project_values
        assert project_values["NEXUS_GATEWAY_URL"] == "http://localhost:8090"
        assert project_values["NEXUS_GATEWAY_API_KEY"] == secrets["NEXUS_GATEWAY_API_KEY"]
        assert self.read(stack) == secrets
        assert len(base64.b64decode(secrets["NEXUS_ENCRYPTION_KEY"])) == 32

    def test_the_stack_file_is_readable_by_its_owner_only(self, env):
        from jarviscore.cli.nexus import ensure_stack_secrets

        project, stack = env
        ensure_stack_secrets(project, stack)
        assert stat.S_IMODE(stack.stat().st_mode) == 0o600
        assert stat.S_IMODE(stack.parent.stat().st_mode) == 0o700

    def test_the_project_directory_keeps_its_permissions(self, env):
        from jarviscore.cli.nexus import ensure_stack_secrets

        project, stack = env
        before = stat.S_IMODE(project.parent.stat().st_mode)
        ensure_stack_secrets(project, stack)
        assert stat.S_IMODE(project.parent.stat().st_mode) == before

    def test_keys_from_an_older_init_are_adopted_not_regenerated(self, env):
        """A new ENCRYPTION_KEY would leave every stored credential unreadable."""
        from jarviscore.cli.nexus import ensure_stack_secrets

        project, stack = env
        project.write_text("OPENAI_API_KEY=keep-me\nNEXUS_ENCRYPTION_KEY=old-enc\nNEXUS_STATE_KEY=old-state\n")

        secrets, _ = ensure_stack_secrets(project, stack)

        assert secrets["NEXUS_ENCRYPTION_KEY"] == "old-enc"
        assert secrets["NEXUS_STATE_KEY"] == "old-state"
        project_values = self.read(project)
        assert "NEXUS_ENCRYPTION_KEY" not in project_values
        assert "NEXUS_STATE_KEY" not in project_values
        assert project_values["OPENAI_API_KEY"] == "keep-me"

    def test_a_conflicting_key_is_never_the_one_deleted(self, env):
        from jarviscore.cli.nexus import _write_private, ensure_stack_secrets

        project, stack = env
        _write_private(stack, "NEXUS_ENCRYPTION_KEY=stack-enc\n")
        project.write_text("NEXUS_ENCRYPTION_KEY=other-enc\n")

        secrets, notes = ensure_stack_secrets(project, stack)

        assert secrets["NEXUS_ENCRYPTION_KEY"] == "stack-enc"
        assert self.read(project)["NEXUS_ENCRYPTION_KEY"] == "other-enc"
        assert any(note.startswith("WARNING") for note in notes)

    def test_the_old_placeholder_broker_key_is_replaced(self, env):
        from jarviscore.cli.nexus import ensure_stack_secrets

        project, stack = env
        project.write_text("NEXUS_BROKER_API_KEY=dev-broker-api-key-change-in-prod\n")

        secrets, _ = ensure_stack_secrets(project, stack)

        assert secrets["NEXUS_BROKER_API_KEY"] != "dev-broker-api-key-change-in-prod"
        assert "NEXUS_BROKER_API_KEY" not in self.read(project)

    def test_running_it_again_changes_nothing(self, env):
        from jarviscore.cli.nexus import ensure_stack_secrets

        project, stack = env
        first, _ = ensure_stack_secrets(project, stack)
        project_text = project.read_text()
        second, notes = ensure_stack_secrets(project, stack)

        assert first == second
        assert project.read_text() == project_text
        assert notes == []


class TestTheClientPresentsTheGatewayKey:

    def test_an_explicit_key_is_sent(self):
        from jarviscore.nexus.client import NexusClient

        client = NexusClient("http://localhost:8090", api_key="gw-key")
        assert client.client.headers["X-API-Key"] == "gw-key"

    def test_the_key_is_read_from_the_environment(self, monkeypatch):
        from jarviscore.nexus.client import NexusClient

        monkeypatch.setenv("NEXUS_GATEWAY_API_KEY", "from-env")
        client = NexusClient("http://localhost:8090")
        assert client.client.headers["X-API-Key"] == "from-env"

    def test_no_key_no_header(self, monkeypatch):
        from jarviscore.nexus.client import NexusClient

        monkeypatch.delenv("NEXUS_GATEWAY_API_KEY", raising=False)
        client = NexusClient("http://localhost:8090")
        assert "X-API-Key" not in client.client.headers
