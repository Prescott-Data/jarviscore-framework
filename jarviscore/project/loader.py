"""
Find, merge, validate and convert `jarviscore.yaml` into process environments.
"""

import difflib
import re
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from .schema import NAME_PATTERN, SECRET_REF_PREFIX, Agent, Project

PROJECT_FILE = "jarviscore.yaml"
DEFAULT_ENVIRONMENT = "development"

# External accessory -> env var the framework already reads.
ACCESSORY_ENV = {
    "redis": "REDIS_URL",
    "nexus": "NEXUS_GATEWAY_URL",
    "athena": "ATHENA_URL",
}


class ProjectError(Exception):
    """A problem with the user's project files, worded for the terminal."""


@dataclass
class LoadedProject:
    root: Path
    project: Project
    destination: str | None
    files: list[Path] = field(default_factory=list)

    @property
    def environment(self) -> str:
        return self.destination or DEFAULT_ENVIRONMENT


def find_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    for directory in (start, *start.parents):
        if (directory / PROJECT_FILE).is_file():
            return directory
    raise ProjectError(
        f"No {PROJECT_FILE} found in {start} or any parent directory.\n"
        f"Create one with: jarviscore init <name>"
    )


def deep_merge(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for key, value in overlay.items():
            merged[key] = deep_merge(
                base[key], value) if key in base else value
        return merged
    return overlay


def load_project(start: Path | None = None, destination: str | None = None) -> LoadedProject:
    root = find_root(start)
    base_file = root / PROJECT_FILE
    data = _read_yaml(base_file)
    files = [base_file]
    overlay: dict = {}

    if destination:
        if not re.match(NAME_PATTERN, destination):
            raise ProjectError(
                f"Invalid destination {destination!r}: use lowercase letters, digits or '-'.")
        overlay_file = root / f"jarviscore.{destination}.yaml"
        if not overlay_file.is_file():
            available = sorted(p.name[len("jarviscore."):-len(".yaml")]
                               for p in root.glob("jarviscore.*.yaml"))
            hint = f"Available: {', '.join(available)}" if available else f"Create {overlay_file.name} to define it."
            raise ProjectError(
                f"Destination {destination!r} has no {overlay_file.name}. {hint}")
        overlay = _read_yaml(overlay_file)
        data = deep_merge(data, overlay)
        files.append(overlay_file)

    data = _apply_defaults(data, files)
    try:
        project = Project.model_validate(data)
    except ValidationError as exc:
        raise ProjectError(_format_errors(exc, files, overlay)) from None
    return LoadedProject(root=root, project=project, destination=destination, files=files)


def build_env(
    loaded: LoadedProject,
    agent_name: str,
    secrets: dict[str, str] | None = None,
    endpoints: dict[str, str] | None = None,
) -> dict[str, str]:
    """Environment for one agent process.

    `secrets` resolves `env.secret` names and `secret:` accessory URLs; names without a
    value are left out so the framework can still read them from `.env`. `endpoints`
    gives URLs for managed accessories (e.g. the dev Redis) keyed by accessory name.
    """
    project = loaded.project
    agent: Agent = project.agents[agent_name]
    secrets = secrets or {}
    endpoints = endpoints or {}

    env: dict[str, str] = {
        "JARVISCORE_SERVICE": project.service,
        "JARVISCORE_ENV": loaded.environment,
        "JARVISCORE_ROLE": agent_name,
    }
    env.update(project.env.clear)
    env.update(agent.env.clear)
    for name in [*project.env.secret, *agent.env.secret]:
        if name in secrets:
            env[name] = secrets[name]

    for name, accessory in project.accessories.items():
        var = ACCESSORY_ENV.get(name)
        if not var:
            continue
        if accessory.external:
            url = accessory.url or ""
            if url.startswith(SECRET_REF_PREFIX):
                ref = url[len(SECRET_REF_PREFIX):]
                if ref in secrets:
                    env[var] = secrets[ref]
            else:
                env[var] = url
        elif name in endpoints:
            env[var] = endpoints[name]
    return env


def _read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"{path.name}:{mark.line + 1}:{mark.column + 1}" if mark else path.name
        problem = getattr(exc, "problem", None) or str(exc)
        raise ProjectError(f"{where}: invalid YAML ({problem})") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ProjectError(
            f"{path.name}: top level must be a mapping of keys, got {type(data).__name__}")
    return data


def _apply_defaults(data: dict, files: list[Path]) -> dict:
    """Every project gets a Redis; with servers, agents default to the only server and
    each agent host gets a sandbox."""
    data = dict(data)
    accessories = dict(data.get("accessories") or {})
    servers = data.get("servers") or {}
    agents = dict(data.get("agents") or {})

    if len(servers) == 1:
        only = next(iter(servers))
        for name, agent in agents.items():
            if isinstance(agent, dict) and not agent.get("hosts"):
                agents[name] = {**agent, "hosts": [only]}
        data["agents"] = agents

    if "redis" not in accessories:
        if len(servers) > 1:
            raise ProjectError(
                f"{files[-1].name}: with more than one server, declare where Redis runs, e.g.\n"
                f"  accessories:\n    redis: {{ host: {next(iter(servers))} }}\n"
                f"or point at an external one: redis: {{ url: secret:REDIS_URL }}"
            )
        accessories["redis"] = {"host": next(iter(servers))} if servers else {}

    if "sandbox" not in accessories and servers:
        agent_hosts = sorted({
            h for a in agents.values() if isinstance(a, dict) for h in (a.get("hosts") or [])
        })
        accessories["sandbox"] = {"hosts": agent_hosts}

    data["accessories"] = accessories
    return data


def _format_errors(exc: ValidationError, files: list[Path], overlay: dict) -> str:
    lines = [
        f"Invalid project configuration ({' + '.join(f.name for f in files)}):"]
    for error in exc.errors():
        loc = [str(part) for part in error["loc"]]
        path = ".".join(loc) or "(top level)"
        source = files[-1].name if len(files) > 1 and _has_path(
            overlay, loc) else files[0].name
        message = error["msg"].removeprefix("Value error, ")
        line = f"  {source}: {path}: {message}"
        if error["type"] == "extra_forbidden":
            allowed = _allowed_keys(loc[:-1])
            close = difflib.get_close_matches(loc[-1], allowed, n=1)
            if close:
                line += f" (did you mean '{close[0]}'?)"
            elif allowed:
                line += f" (allowed: {', '.join(allowed)})"
        lines.append(line)
    return "\n".join(lines)


def _has_path(data: Any, loc: list[str]) -> bool:
    for part in loc:
        if not isinstance(data, dict) or part not in data:
            return False
        data = data[part]
    return True


def _allowed_keys(parent: list[str]) -> list[str]:
    """Field names of the model at `parent`, following dict-of-model fields by key."""
    model: Any = Project
    expect_key = False
    for part in parent:
        if expect_key:
            expect_key = False
            continue
        if not (isinstance(model, type) and issubclass(model, BaseModel)) or part not in model.model_fields:
            return []
        annotation = model.model_fields[part].annotation
        args = typing.get_args(annotation)
        if typing.get_origin(annotation) is dict and args:
            model, expect_key = args[1], True
        else:
            model = next((a for a in args if isinstance(a, type)
                         and issubclass(a, BaseModel)), annotation)
    if isinstance(model, type) and issubclass(model, BaseModel):
        return list(model.model_fields)
    return []
