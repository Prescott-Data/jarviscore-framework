---
icon: material/test-tube
---

# Testing Custom Atoms

When you add a custom atom to a bundle, the `jarviscore atom` CLI gives you a structured two-mode test harness — no test framework required, no live API calls needed to start.

---

## Two Test Modes

### Dry-run (no network)

Runs a full structural analysis of your atom file using the Python AST — no imports, no network calls. This is the gate before anything else.

```bash
jarviscore atom test --bundle my_bundle --mode dry-run
```

What it checks:

| Check | What it validates |
|---|---|
| File exists | `integrations/atoms/<bundle>/<atom>.py` is present |
| Valid Python | File parses without a `SyntaxError` |
| Function name | Top-level function name matches the filename stem |
| Signature | First parameter is `auth_info: dict` |
| Return type | Return annotation is `-> dict` |
| Docstring | Function has a docstring |
| Return statement | At least one `return` statement with a value |
| Forbidden imports | No `subprocess`, `pickle`, `ctypes`, `eval`, `exec`, `__import__` |

### Integration (live Nexus check)

Runs all dry-run checks first, then verifies that a Nexus `connection_id` resolves to a valid token payload against your running Nexus Gateway.

```bash
jarviscore atom test \
    --bundle my_bundle \
    --connection-id abc123 \
    --mode integration
```

The integration check does **not** call the external API — it verifies that credentials are registered and resolvable. Actual API behaviour must be verified manually (or in your own integration tests).

---

## Command Reference

### Test a full bundle

```bash
# Structural check — all atoms in the bundle
jarviscore atom test --bundle slack --mode dry-run

# Integration check — all atoms in the bundle  
jarviscore atom test --bundle slack --connection-id abc123 --mode integration
```

### Test a single atom

```bash
jarviscore atom test \
    --bundle slack \
    --atom slack_send_message \
    --mode dry-run
```

### Test every atom across all bundles (dry-run only)

```bash
jarviscore atom test --mode dry-run --all
```

### List all bundles and their atoms

```bash
jarviscore atom list
```

```bash
# Filter to one bundle
jarviscore atom list --bundle github
```

---

## Writing an Atom That Passes

The harness enforces the JarvisCore atom contract. A conforming atom looks like this:

```python
def github_list_repos(auth_info: dict, username: str, per_page: int = 30) -> dict:
    """
    List public repositories for a GitHub user.

    Args:
        auth_info: Injected by Nexus — contains access_token and client_id.
        username:  GitHub username to list repos for.
        per_page:  Number of results per page (max 100).

    Returns:
        {"repos": [...], "total": int}
    """
    import requests

    headers = {
        "Authorization": f"Bearer {auth_info.get('access_token', '')}",
        "Accept": "application/vnd.github+json",
    }
    resp = requests.get(
        f"https://api.github.com/users/{username}/repos",
        headers=headers,
        params={"per_page": per_page, "sort": "updated"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return {"repos": data, "total": len(data)}
```

**Rules that the harness enforces:**

1. **Filename == function name.** `github_list_repos.py` must contain `def github_list_repos(...)`.
2. **First parameter is `auth_info: dict`.** Nexus injects credentials here — do not rename it, do not move it.
3. **Return `-> dict`.** Even if your payload is list-shaped, wrap it: `{"items": [...]}`.
4. **Write a docstring.** Describe what it does, what `auth_info` provides, and what the return dict contains.
5. **No shell or unsafe imports.** `subprocess`, `pickle`, `ctypes`, `eval`, and `exec` are blocked.

---

## Atom Graduation

Once an atom passes the harness and you have verified it works against the live API, update its stage in `seed_registry.py`:

```python
PROVIDER_META = {
    "my_provider": {
        "stage": "verified",   # was: "candidate"
        ...
    }
}
```

The FunctionRegistry graduation ladder:

| Stage | Meaning |
|---|---|
| `candidate` | Newly added — dry-run passed, not yet live-tested |
| `verified` | Confirmed against live API — promoted by execution |
| `golden` | Repeatedly successful — highest confidence reuse |

The Kernel's Option A semantic search **only reuses `verified` and `golden` atoms** — `candidate` atoms are never selected for reuse.

---

## Example Output

```
JarvisCore Atom Test Harness
Mode: dry-run
Atoms root: jarviscore/integrations/atoms

ℹ  Bundle: slack  |  Atoms: 6

  slack_send_message
  ────────────────────────────────────────────────
  ✓  Atom file exists: integrations/atoms/slack/slack_send_message.py
  ✓  File parses as valid Python
  ✓  Function name matches filename: slack_send_message()
  ✓  First parameter: auth_info: dict  ✓
  ✓  Return annotation: -> dict  ✓
  ✓  Function has a docstring
  ✓  Function has return statement(s)
  ✓  No forbidden imports or builtins
  ────────────────────────────────────────────────
  PASSED  (8 passed, 0 warnings)

════════════════════════════════════════════════════
✓  ALL PASSED
ℹ  Next step: run with --mode integration and a real --connection-id
```

---

## Workflow Summary

```
1. Write atom file at integrations/atoms/<bundle>/<atom>.py
        ↓
2. jarviscore atom test --bundle <bundle> --mode dry-run
   → Fix any structural errors or warnings
        ↓
3. jarviscore nexus register <bundle>
   → Register credentials locally or with the Nexus Gateway
        ↓
4. jarviscore atom test --bundle <bundle> --connection-id <id> --mode integration
   → Confirms Nexus connection resolves correctly
        ↓
5. Test against live API manually (or with your own integration test)
        ↓
6. Update seed_registry.py stage → "verified"
        ↓
7. Atom is now eligible for Kernel Option A reuse
```

---

## Further Reading

- [System Bundles & Integrations](integrations.md) — The 46 built-in atom bundles
- [Nexus: Credential Management](nexus.md) — Registering credentials before integration tests
- [Concepts: System Bundles](../concepts/system-bundles.md) — The immutable atom contract and graduation model
