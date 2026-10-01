import pytest

from jarviscore.browser.controller import ActionResult, BrowserConfig
from jarviscore.browser.dispatcher import BrowserDispatcher
from jarviscore.browser.profiles import BrowserProfile, BrowserProfileRegistry


class ConnectedController:
    def is_connected(self):
        return True

    def get_active_target_id(self):
        return None

    async def navigate(self, url, timeout_ms=None):
        return ActionResult(success=True, data={"url": url})


class SilentTrace:
    def record_action(self, **kwargs):
        pass


@pytest.mark.asyncio
async def test_routed_action_completes_with_trace_settings_read_from_environment():
    registry = BrowserProfileRegistry(default_profile="evidence")
    registry.register(BrowserProfile(name="evidence", config=BrowserConfig()))
    dispatcher = BrowserDispatcher(registry, trace_recorder=SilentTrace())
    dispatcher._controllers["evidence"] = ConnectedController()

    result = await dispatcher.dispatch({
        "kind": "navigate",
        "profile": "evidence",
        "payload": {"url": "https://find-and-update.company-information.service.gov.uk/"},
    })

    assert result.success is True
    assert result.data["url"].startswith("https://find-and-update")
