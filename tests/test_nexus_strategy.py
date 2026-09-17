"""
Tests for credential placement — where a credential goes on an outgoing request.

Placement is a property of the provider, not of the auth type: Okta wants
`Authorization: SSWS`, Zoho wants `Zoho-oauthtoken`, GitLab wants `PRIVATE-TOKEN`.
These tests pin the shapes the shipped atom corpus proves are in use.
"""

import base64

import pytest

from jarviscore.nexus.models import DynamicStrategy
from jarviscore.nexus.strategy import StrategyError, apply_strategy


def header_for(strategy, name="Authorization"):
    return apply_strategy(strategy, "GET", "https://api.example.com/v1/thing")["headers"][name]


class TestProviderSchemes:
    """Every scheme found in the shipped atoms must be expressible."""

    def test_oauth2_uses_the_rfc_bearer_default(self):
        strategy = DynamicStrategy(type="oauth2", credentials={"access_token": "tok"})
        assert header_for(strategy) == "Bearer tok"

    def test_zoho_keeps_its_own_scheme_word(self):
        strategy = DynamicStrategy(
            type="oauth2",
            credentials={"access_token": "tok"},
            config={"value_prefix": "Zoho-oauthtoken "},
        )
        assert header_for(strategy) == "Zoho-oauthtoken tok"

    def test_okta_uses_ssws(self):
        strategy = DynamicStrategy(
            type="api_key",
            credentials={"api_key": "k"},
            config={"header_name": "Authorization", "value_prefix": "SSWS "},
        )
        assert header_for(strategy) == "SSWS k"

    def test_gitlab_uses_a_non_authorization_header(self):
        strategy = DynamicStrategy(
            type="api_key",
            credentials={"api_key": "k"},
            config={"header_name": "PRIVATE-TOKEN"},
        )
        assert header_for(strategy, "PRIVATE-TOKEN") == "k"

    def test_basic_auth_encodes_the_pair(self):
        strategy = DynamicStrategy(
            type="basic_auth", credentials={"username": "u", "password": "p"}
        )
        expected = base64.b64encode(b"u:p").decode()
        assert header_for(strategy) == f"Basic {expected}"

    def test_a_key_can_travel_as_a_query_parameter(self):
        strategy = DynamicStrategy(
            type="query_param",
            credentials={"api_key": "k"},
            config={"param_name": "token_auth"},
        )
        request = apply_strategy(strategy, "GET", "https://api.example.com/v1?page=2")
        assert "token_auth=k" in request["url"]
        assert "page=2" in request["url"]

    def test_the_credential_field_is_configurable(self):
        strategy = DynamicStrategy(
            type="header",
            credentials={"private_token": "k"},
            config={"header_name": "X-Token", "credential_field": "private_token"},
        )
        assert header_for(strategy, "X-Token") == "k"


class TestRefusalToGuess:
    """A wrong header produces an opaque 401, so unknown placement must be named."""

    def test_an_api_key_without_placement_is_refused(self):
        strategy = DynamicStrategy(type="api_key", credentials={"api_key": "k"})
        with pytest.raises(StrategyError, match="no standard location"):
            apply_strategy(strategy, "GET", "https://api.example.com")

    def test_a_query_strategy_without_a_parameter_name_is_refused(self):
        strategy = DynamicStrategy(type="query_param", credentials={"api_key": "k"})
        with pytest.raises(StrategyError, match="param_name"):
            apply_strategy(strategy, "GET", "https://api.example.com")

    def test_a_missing_credential_names_the_field(self):
        strategy = DynamicStrategy(
            type="header",
            credentials={"access_token": "t"},
            config={"header_name": "X-Token", "credential_field": "api_key"},
        )
        with pytest.raises(StrategyError, match="api_key"):
            apply_strategy(strategy, "GET", "https://api.example.com")

    def test_an_unconnected_oauth2_provider_says_what_is_missing(self):
        """Registering a provider's app is not the same as connecting an account."""
        strategy = DynamicStrategy(type="oauth2", credentials={"client_secret": "s"})
        with pytest.raises(StrategyError, match="not the same as connecting an account"):
            apply_strategy(strategy, "GET", "https://api.example.com")


class TestCallerSuppliedHeaders:

    def test_caller_headers_survive(self):
        strategy = DynamicStrategy(type="oauth2", credentials={"access_token": "tok"})
        request = apply_strategy(
            strategy, "POST", "https://api.example.com",
            headers={"Content-Type": "application/json"}, json={"a": 1},
        )
        assert request["headers"]["Content-Type"] == "application/json"
        assert request["headers"]["Authorization"] == "Bearer tok"
        assert request["json"] == {"a": 1}
        assert request["method"] == "POST"
