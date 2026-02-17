"""
6H.1: Nexus Protocol models — Pydantic models for Dromos Gateway integration.

These models define the data structures exchanged between JarvisCore
and the Dromos Gateway for OAuth/auth management.
"""

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


class ConnectionRequest(BaseModel):
    """Request to establish a Nexus connection via Dromos Gateway."""
    user_id: str
    provider_name: str
    scopes: List[str]
    return_url: str = "http://localhost:8080/callback"


class DynamicStrategy(BaseModel):
    """Credentials + application strategy resolved from Dromos Gateway."""
    type: Literal["oauth2", "basic_auth", "api_key"]
    credentials: Dict[str, str]  # access_token, refresh_token, api_key, etc.
    expires_at: Optional[str] = None  # ISO 8601

    def is_expired(self) -> bool:
        """Check if the strategy's credentials have expired."""
        if not self.expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(self.expires_at)
            # Ensure timezone-aware comparison
            now = datetime.now(timezone.utc)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return expiry < now
        except (ValueError, TypeError):
            return False


class ConnectionStatus(BaseModel):
    """Status of a Nexus connection."""
    connection_id: str
    status: Literal[
        "PENDING", "ACTIVE", "ATTENTION", "REVOKED", "EXPIRED", "FAILED"
    ]
    provider: str
    created_at: str
