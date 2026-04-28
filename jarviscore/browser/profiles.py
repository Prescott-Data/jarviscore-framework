"""
Browser profile registry and policy enforcement.
"""
import json
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any

from .controller import BrowserConfig


@dataclass
class BrowserProfile:
    name: str
    config: BrowserConfig
    allowed_actions: Optional[List[str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    color: Optional[str] = None


class BrowserProfileRegistry:
    """
    In-memory profile registry with allowlist policy.
    """
    def __init__(self, default_profile: str = "default", allow_unregistered: bool = False):
        self.default_profile = default_profile
        self.allow_unregistered = allow_unregistered
        self._profiles: Dict[str, BrowserProfile] = {}

    def register(self, profile: BrowserProfile) -> None:
        self._profiles[profile.name] = profile

    def get(self, name: Optional[str]) -> Optional[BrowserProfile]:
        if not name:
            name = self.default_profile
        return self._profiles.get(name)

    def ensure_allowed(self, name: Optional[str]) -> BrowserProfile:
        profile = self.get(name)
        if profile:
            return profile
        if self.allow_unregistered:
            return BrowserProfile(
                name=name or self.default_profile,
                    config=BrowserConfig(profile_name=name or self.default_profile),
            )
        raise ValueError(f"Browser profile not registered: {name}")

    def is_action_allowed(self, profile: BrowserProfile, action_kind: str) -> bool:
        if not profile.allowed_actions:
            return True
        return action_kind in profile.allowed_actions

    @staticmethod
    def from_json(raw: str) -> "BrowserProfileRegistry":
        data = json.loads(raw)
        registry = BrowserProfileRegistry(
            default_profile=data.get("default_profile", "default"),
            allow_unregistered=bool(data.get("allow_unregistered", False)),
        )
        for name, cfg in (data.get("profiles") or {}).items():
            profile = BrowserProfile(
                name=name,
                config=BrowserConfig(
                    headless=bool(cfg.get("headless", True)),
                    slow_mo=int(cfg.get("slow_mo", 0)),
                    timeout_ms=int(cfg.get("timeout_ms", 30000)),
                    cdp_url=cfg.get("cdp_url"),
                        user_data_dir=cfg.get("user_data_dir"),
                        launch_args=cfg.get("launch_args"),
                        user_agent=cfg.get("user_agent"),
                        locale=cfg.get("locale"),
                        timezone_id=cfg.get("timezone_id"),
                        viewport=cfg.get("viewport"),
                        geolocation=cfg.get("geolocation"),
                        permissions=cfg.get("permissions"),
                        ignore_https_errors=cfg.get("ignore_https_errors"),
                    stealth_enabled=cfg.get("stealth_enabled"),
                        profile_name=name,
                        profile_color=cfg.get("color"),
                ),
                allowed_actions=cfg.get("allowed_actions"),
                metadata=cfg.get("metadata") or {},
                    color=cfg.get("color"),
            )
            registry.register(profile)
        return registry

