"""What an atom is, and how one is checked.

An atom is a single provider call the whole swarm can reuse. The convention is
small on purpose, because it has to hold for code a person contributes and code
an agent writes mid-task, and those only stay interchangeable if they are the
same thing:

    async def hubspot_list_contacts(limit: int = 50) -> dict:
        \"\"\"List CRM contacts. https://developers.hubspot.com/docs/api/crm/contacts\"\"\"
        response = await nexus_call(
            "GET", "https://api.hubapi.com/crm/v3/objects/contacts",
            params={"limit": limit},
        )
        if not response["ok"]:
            return {"success": False, "error": response["body"]}
        return {"success": True, "data": response["json"]}

Authentication is `nexus_call` and nothing else. No `auth_info`, no token
parameter, no header the caller has to build — an atom names a provider and the
call proxy attaches credentials outside anything the agent or the atom can read.

That choice is what makes an atom safe to prove. Because auth arrives through
the proxy, an atom runs correctly inside the sandbox, so a new one can be
verified where it cannot leak anything, by executing it. Nothing has to run in
the framework's own process with a token in scope to find out whether it works.

The parameters are the contract. They are read from the signature, so the caller
gets names, types and defaults rather than a paragraph of source to interpret.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

#: Atoms authenticate through this and nothing else.
AUTH_CALL = "nexus_call"

#: The shape the shipped catalogue was written in before `nexus_call`: a raw
#: token dict and `requests`. Nothing ships in this shape now, but the reader
#: still recognises it so a contribution written from an old example is told
#: precisely what to change rather than failing on a confusing detail.
LEGACY_AUTH_PARAMETER = "auth_info"

_NAME = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")


@dataclass(frozen=True)
class AtomParameter:
    name: str
    type: str
    required: bool
    default: Any = None

    def render(self) -> str:
        if self.required:
            return f"{self.name}: {self.type}"
        return f"{self.name}: {self.type} = {self.default!r}"


@dataclass(frozen=True)
class Atom:
    """One provider call, as the catalogue and the agent both see it."""

    name: str
    system: str
    description: str
    parameters: Tuple[AtomParameter, ...] = ()
    legacy: bool = False

    def signature(self) -> str:
        return f"{self.name}({', '.join(p.render() for p in self.parameters)})"

    def describe(self) -> str:
        return f"{self.signature()} — {self.description.strip() or self.system}"


@dataclass(frozen=True)
class ContractResult:
    """Whether source is an atom, and what is missing when it is not."""

    atom: Optional[Atom]
    problems: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.atom is not None and not self.problems

    def report(self) -> str:
        return "; ".join(self.problems)


def _annotation(node: Optional[ast.expr]) -> str:
    if node is None:
        return "any"
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - an unrenderable annotation is not fatal
        return "any"


def _default(node: ast.expr) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:  # noqa: BLE001 - a computed default is still a default
        return None


def read_contract(source: str, *, system: str = "", expected_name: str = "") -> ContractResult:
    """Read atom source against the convention, saying what fails and why.

    Registration is the last point at which the catalogue can stay coherent.
    Something stored here is offered to every future agent as a capability, so
    "it ran once" is not enough — it has to be the shape everything else is.
    """
    problems: List[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return ContractResult(None, (f"source does not parse: {exc}",))

    functions = [n for n in tree.body if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))]
    if not functions:
        return ContractResult(None, ("no function defined at module level",))

    named = [f for f in functions if f.name == expected_name] if expected_name else []
    fn = named[0] if named else functions[-1]

    if expected_name and fn.name != expected_name:
        problems.append(f"no function named `{expected_name}`")

    legacy = any(a.arg == LEGACY_AUTH_PARAMETER for a in fn.args.args)
    uses_nexus = AUTH_CALL in source

    if not _NAME.match(fn.name):
        problems.append(
            f"`{fn.name}` should be named system_verb_object, like hubspot_list_contacts"
        )
    if system and not fn.name.startswith(f"{system.lower()}_"):
        problems.append(f"`{fn.name}` should start with `{system.lower()}_`")
    if not legacy:
        if not isinstance(fn, ast.AsyncFunctionDef):
            problems.append(f"`{fn.name}` must be `async def` — {AUTH_CALL} is awaited")
        if not uses_nexus:
            problems.append(
                f"`{fn.name}` must authenticate with {AUTH_CALL}; credentials never "
                "appear in an atom"
            )
        # Legacy atoms are reference code and never offered as a capability, so
        # the docstring matters only for the ones an agent can actually call.
        if not ast.get_docstring(fn):
            problems.append(
                f"`{fn.name}` needs a docstring saying what it does, with the API reference"
            )

    parameters = []
    arguments = list(fn.args.args) + list(fn.args.kwonlyargs)
    defaults: dict = {}
    for arg, default in zip(fn.args.args[len(fn.args.args) - len(fn.args.defaults):], fn.args.defaults):
        defaults[arg.arg] = _default(default)
    for arg, default in zip(fn.args.kwonlyargs, fn.args.kw_defaults):
        if default is not None:
            defaults[arg.arg] = _default(default)

    for arg in arguments:
        if arg.arg in {"self", LEGACY_AUTH_PARAMETER}:
            continue
        parameters.append(
            AtomParameter(
                name=arg.arg,
                type=_annotation(arg.annotation),
                required=arg.arg not in defaults,
                default=defaults.get(arg.arg),
            )
        )

    atom = Atom(
        name=fn.name,
        system=system,
        description=(ast.get_docstring(fn) or "").split("\n")[0],
        parameters=tuple(parameters),
        legacy=legacy,
    )
    return ContractResult(atom, tuple(problems))


def invocation(atom: Atom, params: dict) -> str:
    """Sandbox code that runs the atom and returns its result.

    The sandbox awaits `main()` and uses its return value, so the atom is called
    through one — the same entry point every other piece of sandbox code uses.
    """
    arguments = ", ".join(f"{key}={value!r}" for key, value in params.items())
    return f"async def main():\n    return await {atom.name}({arguments})\n"
