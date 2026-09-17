"""A consent should be the last consent, not the first of many.

Google issues a refresh token only when the authorization request asks for
offline access. The seed sent the endpoints and not that, so every token died at
sixty minutes and the broker logged "No refresh token available" hourly while
the agent asked the person to approve the same thing again.
"""

from jarviscore.nexus._data import PROVIDER_URLS


GOOGLE = ("gmail", "google_drive", "google_sheets", "google_calendar")


def test_every_google_profile_asks_for_offline_access():
    for provider in GOOGLE:
        params = PROVIDER_URLS[provider].get("params") or {}
        assert params.get("access_type") == "offline", provider
        assert params.get("prompt") == "consent", provider


def test_non_google_profiles_do_not_inherit_google_params():
    """Sending Google's flags to Slack or GitHub is a different bug."""
    for provider, urls in PROVIDER_URLS.items():
        if provider in GOOGLE:
            continue
        assert "access_type" not in (urls.get("params") or {}), provider
