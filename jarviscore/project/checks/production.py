"""`jarviscore check --profile prod`: the production checklist as code.

Each agent is checked against the environment it would be deployed with: the project
files plus declared secrets that have a value in the local environment or `.env`.
"""

import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from ..loader import LoadedProject, build_env
from ..schema import SECRET_REF_PREFIX
from . import ERROR, INFO, WARNING, CheckResult
from .redis import check_redis

PROVIDER_VARS = (
    "CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "AZURE_API_KEY", "AZURE_OPENAI_KEY",
    "GEMINI_API_KEY", "LLM_ENDPOINT", "VLLM_ENDPOINT", "JARVISCORE_PROMO_TOKEN",
)
SECRET_NAME = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|CONNECTION_STRING)$")
NEXUS_SECRET_MIN = 32
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def available_values(root: Path, environ: dict[str, str]) -> dict[str, str]:
    """Values that can resolve declared secrets: `.env` overridden by the process env."""
    values = {k: v for k, v in dotenv_values(root / ".env").items() if v}
    values.update({k: v for k, v in environ.items() if v})
    return values


def run_production_checks(
    loaded: LoadedProject,
    environ: dict[str, str],
    *,
    connect: bool = True,
    redis_checker: Callable[..., list[CheckResult]] = check_redis,
) -> list[CheckResult]:
    project = loaded.project
    available = available_values(loaded.root, environ)
    declared = set(project.env.secret) | {s for a in project.agents.values() for s in a.env.secret}
    secrets = {k: v for k, v in available.items() if k in declared or _referenced(loaded, k)}

    results = [*_project_checks(loaded, available, declared)]
    per_agent = {name: build_env(loaded, name, secrets=secrets) for name in project.agents}
    for check in _ENV_CHECKS:
        results += _aggregate(check, per_agent, loaded)
    results += _redis_checks(loaded, secrets, connect, redis_checker)
    return results


def _referenced(loaded: LoadedProject, name: str) -> bool:
    return any(
        (acc.url or "") == f"{SECRET_REF_PREFIX}{name}" for acc in loaded.project.accessories.values()
    )


def _project_checks(loaded: LoadedProject, available: dict, declared: set) -> list[CheckResult]:
    project = loaded.project
    results = []
    overlay = f"jarviscore.{loaded.destination}.yaml" if loaded.destination else "jarviscore.<env>.yaml"
    if project.servers:
        results.append(CheckResult("deploy.servers", INFO, True, f"{len(project.servers)} server(s) defined"))
    else:
        results.append(CheckResult(
            "deploy.servers", ERROR, False, "No servers defined for this environment",
            f"Add servers in {overlay} and run with -d <env>, e.g. servers: {{ main: 203.0.113.10 }}",
        ))

    inline = sorted(
        k for k, v in [*project.env.clear.items(), *(i for a in project.agents.values() for i in a.env.clear.items())]
        if SECRET_NAME.search(k) and v
    )
    if inline:
        results.append(CheckResult(
            "secrets.inline", ERROR, False, f"Secret-looking values committed in env.clear: {', '.join(inline)}",
            "Move them to env.secret and supply values through .jarviscore/secrets",
        ))

    undeclared = sorted(v for v in PROVIDER_VARS if v in available and v not in declared)
    if undeclared:
        results.append(CheckResult(
            "secrets.undeclared", WARNING, False,
            f"{', '.join(undeclared)} set locally but not listed in env.secret, so it will not be deployed",
            "Add it to env.secret in jarviscore.yaml",
        ))
    return results


def _aggregate(check, per_agent: dict[str, dict], loaded: LoadedProject) -> list[CheckResult]:
    by_outcome: dict[CheckResult, list[str]] = {}
    for name, env in per_agent.items():
        result = check(env, loaded)
        if result is not None:
            by_outcome.setdefault(result, []).append(name)
    if len(by_outcome) <= 1:
        return list(by_outcome)
    return [
        CheckResult(r.id, r.severity, r.ok, f"{r.message} (agents: {', '.join(names)})", r.fix)
        for r, names in by_outcome.items()
    ]


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _llm_provider(env, loaded):
    configured = [v for v in PROVIDER_VARS if env.get(v)]
    if configured:
        return CheckResult("llm.provider", INFO, True, f"LLM provider configured ({configured[0]})")
    return CheckResult("llm.provider", ERROR, False, "No LLM provider configured",
                       "Add e.g. CLAUDE_API_KEY to env.secret and give it a value")


def _log_level(env, loaded):
    level = env.get("LOG_LEVEL", "INFO").upper()
    if level == "DEBUG":
        return CheckResult("logging.level", ERROR, False, "LOG_LEVEL=DEBUG logs LLM payloads",
                           "Set LOG_LEVEL: INFO in env.clear")
    return CheckResult("logging.level", INFO, True, f"LOG_LEVEL={level}")


def _unsafe_execution(env, loaded):
    if _truthy(env.get("ALLOW_UNSAFE_LOCAL_EXECUTION")):
        return CheckResult("sandbox.unsafe", ERROR, False,
                           "ALLOW_UNSAFE_LOCAL_EXECUTION runs model-written code unconfined",
                           "Remove ALLOW_UNSAFE_LOCAL_EXECUTION; deploys provide a confined sandbox")
    return CheckResult("sandbox.unsafe", INFO, True, "Model-written code requires confinement")


def _llm_concurrency(env, loaded):
    limit = env.get("LLM_MAX_CONCURRENT", "0")
    if (limit.isdigit() and int(limit) > 0) or loaded.project.llm.rpm:
        return CheckResult("llm.concurrency", INFO, True, "LLM concurrency is limited")
    return CheckResult("llm.concurrency", WARNING, False,
                       "No LLM concurrency limit: agents can trigger provider 429s together",
                       "Set llm.rpm in jarviscore.yaml or LLM_MAX_CONCURRENT in env.clear")


def _prometheus(env, loaded):
    if _truthy(env.get("PROMETHEUS_ENABLED")):
        return CheckResult("observability.prometheus", INFO, True, "Prometheus metrics enabled")
    return CheckResult("observability.prometheus", WARNING, False, "Prometheus metrics are off",
                       "Set PROMETHEUS_ENABLED: \"true\" in env.clear")


def _p2p(env, loaded):
    if len(loaded.project.agents) > 1 and "P2P_ENABLED" in env and not _truthy(env["P2P_ENABLED"]):
        return CheckResult("p2p.enabled", ERROR, False, "P2P_ENABLED is off but agents run as separate peers",
                           "Remove P2P_ENABLED or set it to true")
    return None


def _storage(env, loaded):
    backend = env.get("STORAGE_BACKEND", "local").lower()
    if backend == "azure" and not env.get("AZURE_STORAGE_CONNECTION_STRING"):
        return CheckResult("storage.backend", ERROR, False,
                           "STORAGE_BACKEND=azure without AZURE_STORAGE_CONNECTION_STRING",
                           "Add AZURE_STORAGE_CONNECTION_STRING to env.secret")
    return CheckResult("storage.backend", INFO, True, f"Storage backend: {backend}")


def _nexus(env, loaded):
    gateway = env.get("NEXUS_GATEWAY_URL")
    if "nexus" not in loaded.project.accessories and not gateway:
        return None
    if gateway and (urlsplit(gateway).hostname or "") in LOCAL_HOSTS:
        return CheckResult("nexus.gateway", ERROR, False, f"NEXUS_GATEWAY_URL points at {gateway}",
                           "Use the deployed gateway URL, or let deploy run the nexus accessory")
    if len(env.get("NEXUS_SECRET", "")) < NEXUS_SECRET_MIN:
        return CheckResult("nexus.secret", ERROR, False,
                           f"NEXUS_SECRET missing or shorter than {NEXUS_SECRET_MIN} characters",
                           "Add NEXUS_SECRET to env.secret with a long random value (openssl rand -base64 48)")
    return CheckResult("nexus.secret", INFO, True, "NEXUS_SECRET set")


_ENV_CHECKS = (_llm_provider, _log_level, _unsafe_execution, _llm_concurrency, _prometheus, _p2p,
               _storage, _nexus)


def _redis_checks(loaded, secrets, connect, redis_checker) -> list[CheckResult]:
    redis = loaded.project.accessories["redis"]
    if not redis.external:
        return [CheckResult("redis.managed", INFO, True, "Redis runs as a managed accessory with persistence")]
    url = redis.url or ""
    if url.startswith(SECRET_REF_PREFIX):
        name = url[len(SECRET_REF_PREFIX):]
        if name not in secrets:
            return [CheckResult("redis.url", ERROR, False, f"accessories.redis.url needs secret {name}, which has no value",
                                f"Set {name} in your environment or .env, or reference it in .jarviscore/secrets")]
        url = secrets[name]
    if not connect:
        return [CheckResult("redis.reachable", INFO, True, "Skipped connecting to Redis (--no-connect)")]
    return redis_checker(url, strict=True)
