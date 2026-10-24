"""`jarviscore init NAME --template T`: generate a complete JarvisCore project.

Template files live in jarviscore/data/templates/<template>/ plus _common/.
"""

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, distribution
from importlib.metadata import version as package_version
from pathlib import Path

from jarviscore.project._names import NAME_PATTERN

from .scaffold import get_data_path

TEMPLATES = {
    "minimal": "One assistant agent",
    "support": "Triage + responder for customer support",
    "research": "Researcher + writer",
    "pipeline": "Extractor -> analyst -> reporter",
}

# provider -> [(env var, prompt, secret?)]
PROVIDERS = {
    "claude": [("CLAUDE_API_KEY", "Anthropic API key", True)],
    "azure": [
        ("AZURE_API_KEY", "Azure OpenAI key", True),
        ("AZURE_ENDPOINT",
         "Azure OpenAI endpoint (https://<resource>.openai.azure.com)", False),
        ("AZURE_DEPLOYMENT", "Azure deployment name", False),
    ],
    "gemini": [("GEMINI_API_KEY", "Gemini API key", True)],
    "promo": [("JARVISCORE_PROMO_TOKEN", "JarvisCore promo token", True)],
}


class InitError(Exception):
    pass


@dataclass
class InitResult:
    root: Path
    files: list[Path] = field(default_factory=list)
    # Existing files left untouched (only with force=True).
    skipped: list[Path] = field(default_factory=list)
    locked: bool = False


def templates_dir() -> Path:
    return get_data_path() / "templates"


def validate_project(
    parent: Path,
    name: str,
    template: str = "minimal",
    provider: str | None = None,
    force: bool = False,
) -> Path:
    """Check everything that can fail before asking the user anything; returns the root."""
    if not re.match(NAME_PATTERN, name):
        raise InitError(
            f"Project name {name!r} must be lowercase letters, digits or '-', starting with a letter.")
    if template not in TEMPLATES:
        raise InitError(
            f"Unknown template {template!r}. Choose from: {', '.join(TEMPLATES)}")
    if provider and provider not in PROVIDERS:
        raise InitError(
            f"Unknown provider {provider!r}. Choose from: {', '.join(PROVIDERS)}")

    root = parent / name
    if root.exists() and not root.is_dir():
        raise InitError(f"{root} exists and is not a directory.")
    if root.exists() and any(root.iterdir()) and not force:
        raise InitError(
            f"{root} already exists and is not empty "
            "(use --force to add the missing files; existing files are kept).")
    return root


def create_project(
    parent: Path,
    name: str,
    template: str = "minimal",
    provider: str | None = None,
    credentials: dict[str, str] | None = None,
    force: bool = False,
) -> InitResult:
    """Generate the project. With force, write into a non-empty directory but never
    replace an existing file (including .env): missing files are added, the rest skipped."""
    root = validate_project(parent, name, template, provider, force)

    secret_names = [var for var, _,
                    secret in PROVIDERS.get(provider, []) if secret]
    context = {
        "service": name,
        "jarviscore_version": _framework_version(),
        "framework_source": _framework_source_block(),
        "secret_list": "[" + ", ".join(secret_names) + "]",
        "secret_refs": "\n".join(f"{n}=${n}" for n in secret_names) or "# CLAUDE_API_KEY=$CLAUDE_API_KEY",
    }

    result = InitResult(root=root)
    for source_dir in (templates_dir() / "_common", templates_dir() / template):
        for src in sorted(p for p in source_dir.rglob("*") if p.is_file()):
            if "__pycache__" in src.parts:
                continue
            dest = root / _target_path(src.relative_to(source_dir))
            if _keep_existing(dest, result):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix == ".tmpl":
                dest.write_text(_render(src.read_text(), context))
            else:
                shutil.copyfile(src, dest)
            result.files.append(dest)

    env_example = root / ".env.example"
    if not _keep_existing(env_example, result):
        shutil.copyfile(get_data_path() / ".env.minimal", env_example)
        result.files.append(env_example)
    env_file = root / ".env"
    if not _keep_existing(env_file, result):
        env_file.write_text(_env_file(provider, credentials or {}))
        env_file.chmod(0o600)
        result.files.append(env_file)

    # An existing lock is the user's; do not rewrite it.
    result.locked = (root / "uv.lock").exists() or _uv_lock(root)
    return result


def _keep_existing(path: Path, result: InitResult) -> bool:
    if path.exists() or path.is_symlink():
        result.skipped.append(path)
        return True
    return False


def _target_path(relative: Path) -> Path:
    parts = []
    for part in relative.parts:
        if part.startswith("dot_"):
            part = "." + part[len("dot_"):]
        if part == "gitignore":
            part = ".gitignore"
        parts.append(part)
    target = Path(*parts)
    return target.with_suffix("") if target.suffix == ".tmpl" else target


def _render(text: str, context: dict[str, str]) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in context:
            raise InitError(f"Template placeholder {{{{{key}}}}} has no value")
        return context[key]

    return re.sub(r"\{\{\s*([a-z_]+)\s*\}\}", replace, text)


def _env_file(provider: str | None, credentials: dict[str, str]) -> str:
    lines = [
        "# Local development secrets. Never commit this file.",
        "# Production secrets are referenced from .jarviscore/secrets instead.",
        "",
    ]
    for var, _, _ in PROVIDERS.get(provider, []):
        value = credentials.get(var, "")
        lines.append(f"{var}={value}" if value else f"# {var}=")
    if not provider:
        lines += [
            "# Set one LLM provider (see .env.example), e.g.:",
            "# CLAUDE_API_KEY=",
        ]
    return "\n".join(lines) + "\n"


def _framework_version() -> str:
    try:
        return package_version("jarviscore-framework")
    except PackageNotFoundError:
        return "2.1.0"


def _framework_source() -> Path | None:
    """The checkout this CLI runs from when installed from a local path (e.g. `pip install -e`).

    Its version number can match a PyPI release that lacks what the checkout adds,
    so a project generated from it must install the checkout, not resolve PyPI.
    """
    try:
        raw = distribution("jarviscore-framework").read_text("direct_url.json")
        url = json.loads(raw or "{}").get("url", "")
    except (PackageNotFoundError, ValueError, OSError):
        return None
    if not url.startswith("file://"):
        return None
    from urllib.parse import unquote, urlparse

    path = Path(unquote(urlparse(url).path))
    return path if (path / "pyproject.toml").is_file() else None


def _framework_source_block() -> str:
    source = _framework_source()
    if source is None:
        return ""
    return ("\n# Installed from a local checkout of the framework; remove to use PyPI.\n"
            "[tool.uv.sources]\n"
            f"jarviscore-framework = {{ path = {json.dumps(str(source))}, editable = true }}\n")


def _uv_lock(root: Path) -> bool:
    if not shutil.which("uv"):
        return False
    print("Locking dependencies with uv…", file=sys.stderr, flush=True)
    try:
        subprocess.run(["uv", "lock", "--quiet"], cwd=root, check=True, timeout=300,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (subprocess.SubprocessError, OSError):
        return False
