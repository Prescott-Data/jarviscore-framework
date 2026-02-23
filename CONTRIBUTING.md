# Contributing to JarvisCore

Thanks for your interest in contributing to JarvisCore. We welcome pull requests for core framework improvements, new examples, docs upgrades, tests, and bug fixes.

JarvisCore is open source under Apache 2.0. Some enterprise-grade hardening features live in a separate commercial distribution; this repository is the open-source core.

---

## Code of Conduct

We expect respectful, constructive collaboration. By participating, you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Quick ways to contribute


Good first contributions:

- Improve docs clarity or fix broken links
- Add expected outputs / success criteria to examples
- Add tests around workflow recovery, step-claiming, and message routing
- Add new production examples (with clear infra + expected outputs)
- Bug fixes with a minimal reproducible case

Check issues labeled **`good first issue`** or **`help wanted`** to find something to work on.

---

## Contributor License Agreement (CLA)

We use a CLA so we can safely distribute JarvisCore in both open-source and enterprise contexts.

- **Individuals**: sign the [Individual CLA](CLA/INDIVIDUAL.md) once.
- **Companies**: if contributing as an employee, sign the [Corporate CLA](CLA/CORPORATE.md), or confirm your employer allows OSS contributions under their existing CLA.

**Pull requests cannot be merged until the CLA is signed.**

To arrange signing, email **info@prescottdata.io** with the subject line "CLA — [your GitHub handle]".

---

## Before you start

### 1. Search existing issues and discussions

If your change is significant (new feature, architecture change, public API changes), open an issue first so we can align before you invest time in implementation.

### 2. Keep changes focused

Prefer small PRs that do one thing well. If you need a large change, break it into a sequence:

1. Refactor / internal cleanup
2. Feature addition
3. Docs + examples
4. Follow-on improvements

---

## Local development setup

This project includes production examples that require Redis.

### Prerequisites

- Python >= 3.10
- Redis (local or Docker)
- Docker (optional, for multi-node/distributed examples)

### Install

```bash
git clone https://github.com/Prescott-Data/jarviscore-framework.git
cd jarviscore-framework

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -U pip
pip install -e ".[dev]"
```

### Start Redis (Docker)

```bash
docker run --name jarviscore-redis -p 6379:6379 -d redis:7
```

### Run tests

```bash
pytest -q
```

### Lint and format

```bash
ruff check .
ruff format .
```

---

## Running examples (and what to include in PRs)

If you add or modify an example, your PR must include:

- How to run it
- Required environment variables
- Expected output / success criteria

**Example template** (use this format in your PR description):

```
### Example: Investment Committee (multi-agent debate + synthesis)

**Run**

    cd examples/investment_committee
    python committee.py --mode full --ticker NVDA --amount 1500000

**Requires**
- Redis running (localhost:6379)
- ANTHROPIC_API_KEY or compatible LLM env var set
- pip install -r examples/investment_committee/requirements.txt

**Success criteria**
- All 7 workflow steps complete (4 parallel → risk → memo → decision)
- Memo written to data/memos/YYYYMMDD_HHMM_{TICKER}_{ACTION}.md
- Console prints final COMMITTEE DECISION block (BUY / HOLD / PASS)
- LTM updated in Redis + blob_storage for next run
```

---

## Branch and PR workflow

### Branch naming

```
fix/<short-description>
feat/<short-description>
docs/<short-description>
test/<short-description>
refactor/<short-description>
```

### Commit message guidelines

```
feat: add investment committee example
fix: correct step claiming race in distributed worker
docs: remove phase numbering from infrastructure section
test: add crash recovery scenario for workflow engine
refactor: extract step dependency resolver
```

### PR checklist

Include in your PR description:

- [ ] What problem this solves
- [ ] How you tested it
- [ ] Any breaking changes (and why)
- [ ] Screenshots or log snippets for examples (if relevant)
- [ ] CLA signed (or confirmation it was signed previously)

---

## Design principles

JarvisCore is a production-first multi-agent framework. Contributions should preserve:

**Deterministic orchestration** — Workflows should be inspectable, recoverable, and testable.

**Extensibility without complexity** — Prefer clean interfaces and hooks over special-case logic.

**Safety and least privilege** — Do not introduce patterns that encourage insecure defaults.

**Clear separation of concerns** — Core framework stays generic; product or business-specific features belong in downstream packages.

If your change affects public APIs, include:

- Docs updates
- An example usage
- Tests
- A migration note if it is a breaking change

---

## Reporting bugs

Please open an issue with:

- JarvisCore version / commit hash
- OS and Python version
- Steps to reproduce
- Expected vs actual behaviour
- Logs / stack trace
- Minimal sample workflow (if possible)

---

## Security issues

**Do not open public issues for security vulnerabilities.**

Email: **info@prescottdata.io** with subject "SECURITY — [brief description]"

Include:

- Description and impact
- Reproduction steps
- Affected versions
- Suggested fix (if you have one)

---

## License

By contributing, you agree your contributions will be licensed under the [Apache License 2.0](LICENSE), consistent with this repository's licence, and subject to the CLA requirement above.

Thank you for helping build JarvisCore.
