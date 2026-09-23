import json
from types import SimpleNamespace

import pytest

from jarviscore.browser.profile_decoration import decorate_profile


def browser_types():
    pytest.importorskip("playwright")
    from jarviscore.browser.controller import BrowserConfig
    from jarviscore.browser.dispatcher import BrowserDispatcher
    from jarviscore.browser.profiles import BrowserProfile, BrowserProfileRegistry

    return BrowserConfig, BrowserDispatcher, BrowserProfile, BrowserProfileRegistry


def test_profile_decoration_is_idempotent_and_preserves_unknown_metadata(tmp_path):
    metadata = tmp_path / ".jarviscore-profile.json"
    metadata.write_text(json.dumps({"owner": "customer"}))

    decorate_profile(tmp_path, "matter-research", "#1863dc")
    decorate_profile(tmp_path, "matter-research", "#1863dc")

    assert json.loads(metadata.read_text()) == {
        "owner": "customer",
        "name": "matter-research",
        "color": "#1863dc",
    }


@pytest.mark.asyncio
async def test_dispatcher_environment_path_does_not_raise_name_error(monkeypatch):
    BrowserConfig, BrowserDispatcher, BrowserProfile, BrowserProfileRegistry = (
        browser_types()
    )
    monkeypatch.setenv("BROWSER_TRACE_SCREENSHOTS", "false")
    registry = BrowserProfileRegistry(default_profile="test")
    registry.register(BrowserProfile("test", BrowserConfig()))
    dispatcher = BrowserDispatcher(registry)
    controller = SimpleNamespace(
        get_active_target_id=lambda: None,
        navigate=lambda *args, **kwargs: None,
    )

    async def get_controller(profile_name):
        return controller

    async def navigate(url, timeout_ms=None):
        return SimpleNamespace(success=True, data={"url": url}, error=None)

    controller.navigate = navigate
    monkeypatch.setattr(dispatcher, "_get_controller", get_controller)

    result = await dispatcher.dispatch({
        "kind": "navigate",
        "profile": "test",
        "payload": {"url": "https://example.com"},
    })

    assert result.success is True
    assert result.data["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_dispatcher_redacts_screenshot_bytes_from_result(monkeypatch):
    BrowserConfig, BrowserDispatcher, BrowserProfile, BrowserProfileRegistry = (
        browser_types()
    )
    registry = BrowserProfileRegistry(default_profile="test")
    registry.register(BrowserProfile("test", BrowserConfig()))
    dispatcher = BrowserDispatcher(registry)
    controller = SimpleNamespace(get_active_target_id=lambda: None)

    async def get_controller(profile_name):
        return controller

    async def screenshot(ref=None, full_page=False, format="png"):
        return SimpleNamespace(
            success=True,
            data={"bytes": b"\x89PNG\r\nraw-image", "format": format},
            error=None,
            ref=ref,
        )

    controller.screenshot = screenshot
    monkeypatch.setattr(dispatcher, "_get_controller", get_controller)

    result = await dispatcher.dispatch({
        "kind": "screenshot",
        "profile": "test",
        "payload": {"full_page": True, "format": "png"},
    })

    assert result.data == {"bytes": "<redacted>", "format": "png"}
