# Publishing Guide

This document describes how to build and publish `jarviscore-framework` to PyPI and TestPyPI.
It is for maintainers only — contributors do not need to follow this flow.

> A formal versioning policy is in progress. Until it is merged, follow the conventions below.

---

## Prerequisites

- Write access to the `Prescott-Data/jarviscore-framework` GitHub repository
- Trusted Publisher registered on both [pypi.org](https://pypi.org) and [test.pypi.org](https://test.pypi.org)
  (one-time setup — see the "Infrastructure" section below)
- No PyPI API tokens or secrets required — authentication is handled automatically via OIDC

---

## Release flow

### 1. Bump the version

Edit `pyproject.toml` and update the `version` field:

```toml
[project]
version = "1.0.5"   # was 1.0.4
```

We follow [Semantic Versioning](https://semver.org):

| Change type | Version bump | Example |
|---|---|---|
| Backwards-compatible bug fix | patch | `1.0.4` → `1.0.5` |
| New backwards-compatible feature | minor | `1.0.4` → `1.1.0` |
| Breaking API change | major | `1.0.4` → `2.0.0` |

Commit the version bump on `main` before triggering the workflow:

```bash
git add pyproject.toml
git commit -m "chore(release): bump version to 1.0.5"
git push origin main
```

### 2. Publish to TestPyPI first

1. Go to **GitHub → Actions → Publish to PyPI**
2. Click **Run workflow**
3. Set **Publish target** → `testpypi`, leave **Dry run** unchecked
4. Click **Run workflow**

Once it completes, verify the package at:
`https://test.pypi.org/project/jarviscore-framework/`

Install and smoke-test from TestPyPI:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ jarviscore-framework
```

### 3. Publish to PyPI

Only after TestPyPI looks correct:

1. Go to **GitHub → Actions → Publish to PyPI**
2. Click **Run workflow**
3. Set **Publish target** → `pypi`, leave **Dry run** unchecked
4. Click **Run workflow**
5. The workflow will pause at the `pypi` environment gate — a required reviewer must click
   **Review deployments → Approve and deploy** before the upload proceeds

Verify at: `https://pypi.org/project/jarviscore-framework/`

### 4. Dry run (build check only)

To verify the build without uploading anything, run the workflow with **Dry run** checked.
This runs `python -m build` and `twine check` and stops there.

---

## Infrastructure (one-time setup)

The workflow uses **PyPI Trusted Publishing** — no stored API tokens.
PyPI issues a short-lived credential automatically during each workflow run.

Both registries must have a Trusted Publisher entry pointing at this workflow:

| Field | Value |
|---|---|
| Owner | `Prescott-Data` |
| Repository | `jarviscore-framework` |
| Workflow filename | `publish.yml` |
| Environment name | `pypi` (on PyPI) / `testpypi` (on TestPyPI) |

To add or update the entry:
- PyPI: **pypi.org → Manage → [project] → Publishing**
- TestPyPI: **test.pypi.org → Manage → [project] → Publishing**

If the project does not exist yet on a registry, use the **"Add a new pending publisher"**
section under your account settings instead.

---

## Troubleshooting

**`403 Forbidden` during upload**
The Trusted Publisher entry is missing or the environment name in the workflow does not
match what is registered on PyPI. Double-check the four fields in the table above.

**Build fails at `twine check`**
Run locally to see the full error:
```bash
rm -rf dist/ && python -m build && twine check dist/*
```

**Workflow not visible in Actions tab**
The `publish.yml` file must be on the `main` branch. Confirm with:
```bash
git log --oneline origin/main -- .github/workflows/publish.yml
```
