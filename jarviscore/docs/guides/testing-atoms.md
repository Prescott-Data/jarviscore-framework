---
icon: material/test-tube
---

# Testing Custom Atoms

When you add a custom atom to a bundle, the `jarviscore atom` CLI gives you a structured two-mode test harness. No external test framework is required, and no live API calls are needed to get started.

---

## Two Test Modes

### Dry-run (no network)

Dry-run analyses your atom file using the Python AST. It does not import the file and makes no network calls. This mode is the gate that must pass before you move to integration testing.

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
| Forbidden imports | No `subprocess`, `pickle`, `ctypes`, `eval`, `exec`, or `__import__` |

### Integration (live Nexus check)

Integration mode runs all dry-run checks first. If they pass, it verifies that a Nexus `connection_id` resolves to a valid token payload against your running Nexus Gateway.

```bash
jarviscore atom test \
    --bundle my_bundle \
    --connection-id abc123 \
    --mode integration
```

The integration check does not call the external API. It verifies that credentials are registered and resolvable. Actual API behaviour must be verified manually or in your own integration tests.

---

## Command Reference

### Test a full bundle

```bash
# Structural check across all atoms in the bundle
jarviscore atom test --bundle slack --mode dry-run

# Integration check across all atoms in the bundle
jarviscore atom test --bundle slack --connection-id abc123 --mode integration
```

### Test a single atom

```bash
jarviscore atom test \
    --bundle slack \
    --atom slack_send_message \
    --mode dry-run
```

### Test every atom across all bundles

This only works in dry-run mode.

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
        auth_info: Injected by Nexus. Contains access_token and client_id.
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

**The atom contract:**

1. **Filename equals function name.** The file `github_list_repos.py` must contain `def github_list_repos(...)`. They must match exactly.
2. **First parameter is `auth_info: dict`.** Nexus injects credentials via this parameter. Do not rename it and do not move it to a different position.
3. **Return annotation is `-> dict`.** If your payload is list-shaped, wrap it: `{"items": [...]}`.
4. **Write a docstring.** Describe what the atom does, what `auth_info` provides, and what the return dict contains.
5. **No shell or unsafe imports.** The following are blocked: `subprocess`, `pickle`, `ctypes`, `eval`, and `exec`.

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
| `candidate` | Newly added. Dry-run passed, but not yet tested against a live API. |
| `verified` | Confirmed against a live API. Promoted by at least one successful execution. |
| `golden` | Repeatedly successful. Five or more executions. Highest confidence for reuse. |

The Kernel's semantic search only selects `verified` and `golden` atoms for reuse. Atoms at the `candidate` stage are never selected.

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
   Fix any structural errors or warnings before continuing.
        ↓
3. jarviscore nexus register <bundle>
   Register credentials locally or with the Nexus Gateway.
        ↓
4. jarviscore atom test --bundle <bundle> --connection-id <id> --mode integration
   Confirms the Nexus connection resolves correctly.
        ↓
5. Test the atom against the live API manually, or write your own integration test.
        ↓
6. Update stage to "verified" in seed_registry.py.
        ↓
7. The atom is now eligible for Kernel reuse.
```

---

## Further Reading

- [Service Integrations](integrations.md) documents the 46 built-in atom bundles.
- [Nexus: Credential Management](nexus.md) covers credential registration, which is required before running integration tests.
- [Concepts: System Bundles](../concepts/system-bundles.md) covers the immutable atom contract and the graduation model in depth.
