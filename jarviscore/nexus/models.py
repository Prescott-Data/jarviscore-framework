"""
Nexus Protocol models — Pydantic models for Nexus Gateway integration.

These models define the data structures exchanged between JarvisCore
and the Nexus Gateway for OAuth/auth connection management.

Reference: Nexus Framework documentation
"""

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, field_validator


class ConnectionRequest(BaseModel):
    """Request to establish a connection via the Nexus Gateway."""
    user_id: str
    provider_name: str
    scopes: List[str]
    return_url: str  # Must point to the dashboard OAuth callback, NOT the Broker

    @field_validator("return_url")
    @classmethod
    def validate_return_url(cls, v: str) -> str:
        """Ensure return_url is explicitly set and never targets the Broker port."""
        if not v or v.strip() == "":
            raise ValueError(
                "return_url must be set explicitly (e.g. 'http://localhost:8000/oauth/callback')"
            )
        if ":8080" in v:
            raise ValueError(
                f"return_url '{v}' appears to target the Nexus Broker (port 8080). "
                "Set it to your dashboard callback (e.g. 'http://localhost:8000/oauth/callback')."
            )
        return v


class DynamicStrategy(BaseModel):
    """
    Credentials + application strategy resolved from the Nexus Gateway.

    Where a credential belongs on the request is provider data, not a property
    of the auth type: Okta wants `Authorization: SSWS <key>`, Zoho wants
    `Authorization: Zoho-oauthtoken <token>`, GitLab wants `PRIVATE-TOKEN`.
    `config` carries that placement, mirroring the Nexus broker's strategy
    config (header_name / value_prefix / credential_field / param_name).

    - oauth2:      Authorization: Bearer <access_token>  (RFC 6750)
    - basic_auth:  Authorization: Basic <base64(username:password)>
    - header:      <header_name>: <value_prefix><credential>
    - query_param: ?<param_name>=<credential>
    - api_key:     placement MUST come from config — there is no standard
    """
    type: Literal["oauth2", "basic_auth", "api_key", "header", "query_param"]
    credentials: Dict[str, str]  # access_token, api_key, username/password, etc.
    config: Dict[str, str] = {}
    expires_at: Optional[str] = None  # ISO 8601

    def is_expired(self) -> bool:
        """Check if the strategy's credentials have expired."""
        if not self.expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(self.expires_at)
            now = datetime.now(timezone.utc)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return expiry < now
        except (ValueError, TypeError):
            return False


class ConnectionStatus(BaseModel):
    """
    Status of a Nexus connection.

    States:
    - PENDING:   OAuth handshake initiated, waiting for user consent
    - ACTIVE:    Connection live, tokens valid
    - ATTENTION: Re-authentication required (e.g. refresh_token revoked by provider)
    - REVOKED:   User or admin revoked access
    - EXPIRED:   Token expired and refresh failed
    - FAILED:    Handshake failed (terminal)
    """
    connection_id: str
    status: Literal[
        "PENDING", "ACTIVE", "ATTENTION", "REVOKED", "EXPIRED", "FAILED"
    ]
    provider: str
    created_at: str
