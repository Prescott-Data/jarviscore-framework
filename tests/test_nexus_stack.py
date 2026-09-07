"""The Nexus stack JarvisCore ships is internally consistent.

JarvisCore used to carry a copy of the broker's schema, because the broker image
did not bundle its migrations. The copy drifted, and the drift surfaced as a
missing column during `nexus register`. From nexus-broker v0.3.0 the broker
applies its own migrations on boot, so the copy is gone and these tests keep it
that way.
"""

import pathlib
import re

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
