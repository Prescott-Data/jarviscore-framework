"""
Schema for `jarviscore.yaml`
"""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ._names import NAME_PATTERN, SECRET_REF_PREFIX

ENV_NAME_PATTERN = r"^[A-Z_][A-Z0-9_]*$"

# Accessories JarvisCore knows how to run without an image.
PRESET_ACCESSORIES = ("redis", "sandbox", "nexus")


def _strip_extensions(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            k: _strip_extensions(v)
            for k, v in data.items()
            if not (isinstance(k, str) and k.startswith("x-"))
        }
    if isinstance(data, list):
        return [_strip_extensions(v) for v in data]
    return data


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _drop_extensions(cls, data: Any) -> Any:
        return _strip_extensions(data)


def _check_name(kind: str, name: str) -> str:
    if not re.match(NAME_PATTERN, name):
        raise ValueError(
            f"{kind} name {name!r} must be lowercase letters, digits or '-', starting with a letter"
        )
    return name


class EnvSpec(_Strict):
    clear: dict[str, str] = Field(default_factory=dict)
    secret: list[str] = Field(default_factory=list)

    @field_validator("clear", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: ("" if v is None else str(v).lower() if isinstance(v, bool) else str(v)) for k, v in value.items()}
        return value

    @model_validator(mode="after")
    def _check_names(self) -> "EnvSpec":
        for name in [*self.clear, *self.secret]:
            if not re.match(ENV_NAME_PATTERN, name):
                raise ValueError(
                    f"env var name {name!r} must match {ENV_NAME_PATTERN}")
        overlap = set(self.clear) & set(self.secret)
        if overlap:
            raise ValueError(
                f"{sorted(overlap)} listed in both env.clear and env.secret")
        return self


class Server(_Strict):
    host: str
    user: str = "root"
    port: int = Field(22, ge=1, le=65535)


class Agent(_Strict):
    path: str
    hosts: list[str] = Field(default_factory=list)
    replicas: int = Field(1, ge=1)
    hitl: bool = False
    env: EnvSpec = Field(default_factory=EnvSpec)

    @field_validator("path")
    @classmethod
    def _relative_py(cls, value: str) -> str:
        if value.startswith("/") or ".." in value.split("/"):
            raise ValueError("path must be relative to the project root")
        if not value.endswith(".py"):
            raise ValueError("path must point to a .py file")
        return value


class Accessory(_Strict):
    host: str | None = None
    hosts: list[str] = Field(default_factory=list)
    url: str | None = None
    image: str | None = None
    port: int | None = Field(None, ge=1, le=65535)
    env: EnvSpec = Field(default_factory=EnvSpec)

    @model_validator(mode="after")
    def _managed_xor_external(self) -> "Accessory":
        if self.host and self.hosts:
            raise ValueError("use either 'host' or 'hosts', not both")
        if self.url and (self.host or self.hosts or self.image):
            raise ValueError(
                "an external accessory ('url') cannot also set host, hosts or image")
        if self.url and self.url.startswith(SECRET_REF_PREFIX):
            ref = self.url[len(SECRET_REF_PREFIX):]
            if not re.match(ENV_NAME_PATTERN, ref):
                raise ValueError(
                    f"secret reference {self.url!r} must be 'secret:NAME' with NAME matching {ENV_NAME_PATTERN}")
        return self

    @property
    def external(self) -> bool:
        return self.url is not None

    @property
    def placed_on(self) -> list[str]:
        return [self.host] if self.host else list(self.hosts)


class Proxy(_Strict):
    host: str
    ssl: bool = True
    app_port: int | None = Field(None, ge=1, le=65535)


class LLM(_Strict):
    rpm: int | None = Field(None, ge=1)


class Project(_Strict):
    service: str
    servers: dict[str, Server] = Field(default_factory=dict)
    agents: dict[str, Agent]
    accessories: dict[str, Accessory] = Field(default_factory=dict)
    proxy: Proxy | None = None
    env: EnvSpec = Field(default_factory=EnvSpec)
    llm: LLM = Field(default_factory=LLM)
    drain_timeout: int = Field(30, ge=1)
    deploy_timeout: int = Field(120, ge=1)
    retain_releases: int = Field(5, ge=1)

    @field_validator("servers", mode="before")
    @classmethod
    def _host_shorthand(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: ({"host": v} if isinstance(v, str) else v) for k, v in value.items()}
        return value

    @field_validator("service")
    @classmethod
    def _service_name(cls, value: str) -> str:
        return _check_name("service", value)

    @model_validator(mode="after")
    def _cross_references(self) -> "Project":
        if not self.agents:
            raise ValueError("at least one agent is required under 'agents'")
        for kind, names in (("server", self.servers), ("agent", self.agents), ("accessory", self.accessories)):
            for name in names:
                _check_name(kind, name)

        for name, agent in self.agents.items():
            self._check_hosts(f"agents.{name}", agent.hosts)
        for name, acc in self.accessories.items():
            self._check_hosts(f"accessories.{name}", acc.placed_on)
            if not acc.external and name not in PRESET_ACCESSORIES and not acc.image:
                raise ValueError(
                    f"accessories.{name}: custom accessories need 'image' (or 'url' for an external service)")

        redis = self.accessories.get("redis")
        if redis and len(redis.placed_on) > 1:
            raise ValueError(
                "accessories.redis: run one Redis per environment (single 'host'), or use 'url'")

        sandbox = self.accessories.get("sandbox")
        if sandbox and not sandbox.external and self.servers:
            missing = sorted(self.agent_hosts() - set(sandbox.placed_on))
            if missing:
                raise ValueError(
                    f"accessories.sandbox: every agent host needs a sandbox; missing {missing}")
        return self

    def _check_hosts(self, where: str, hosts: list[str]) -> None:
        if hosts and not self.servers:
            raise ValueError(
                f"{where}: hosts are set but no 'servers' are defined")
        unknown = [h for h in hosts if h not in self.servers]
        if unknown:
            raise ValueError(
                f"{where}: unknown server(s) {unknown}; defined: {sorted(self.servers)}")

    def agent_hosts(self) -> set:
        return {h for agent in self.agents.values() for h in agent.hosts}
