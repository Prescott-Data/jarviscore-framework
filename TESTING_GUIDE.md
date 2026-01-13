# JarvisCore Testing Guide for v0.1.0

Complete guide for testing the AutoAgent/Prompt-Dev framework before packaging.

---

## Overview

JarvisCore v0.1.0 is designed for **AutoAgent/Prompt-Dev** users who:
1. Write prompts describing what they want
2. Specify LLM model and API keys
3. Let the framework generate code and execute it

This testing suite validates the complete "Prompt → Code → Result" workflow.

---

## Testing Tools

### 1. Health Check CLI
**Command:** `python -m jarviscore.cli.check`

**Purpose:** Validates installation and configuration

**What it checks:**
- ✅ Python version (>=3.10)
- ✅ JarvisCore package installed
- ✅ Core dependencies (pydantic, pydantic-settings, dotenv)
- ✅ .env file exists
- ✅ LLM provider configured (Claude/Azure/Gemini/vLLM)
- ✅ Sandbox configuration

**With LLM validation:**
```bash
python -m jarviscore.cli.check --validate-llm
```
Makes actual API calls to test connectivity.

---

### 2. Smoke Test CLI
**Command:** `python -m jarviscore.cli.smoketest`

**Purpose:** End-to-end validation of AutoAgent workflow

**What it tests:**
1. Framework imports work
2. Environment configuration loads
3. Mesh creation succeeds
4. Agent definition works
5. **Full workflow:** Prompt → LLM → Code → Sandbox → Result

**Features:**
- Automatic retry with exponential backoff (3 attempts)
- Handles temporary LLM overload (529 errors)
- Validates result correctness (2+2=4)
- Shows execution time and repair attempts

**Verbose mode:**
```bash
python -m jarviscore.cli.smoketest --verbose
```
Shows detailed output and stack traces.

---

## User Testing Workflow

### Step 1: Install Framework (1 minute)
```bash
pip install jarviscore
```

### Step 2: Configure LLM (2 minutes)
```bash
# Copy example config
cp .env.example .env

# Edit .env and add API key
# Choose ONE:
CLAUDE_API_KEY=sk-ant-...
# OR
AZURE_API_KEY=...
AZURE_ENDPOINT=https://your-resource.openai.azure.com
AZURE_DEPLOYMENT=gpt-4o
# OR
GEMINI_API_KEY=...
# OR
LLM_ENDPOINT=http://localhost:8000
```

### Step 3: Validate Setup (30 seconds)
```bash
# Basic check
python -m jarviscore.cli.check

# Test LLM connectivity
python -m jarviscore.cli.check --validate-llm
```

**Expected output:**
```
✓ Python Version: OK
✓ JarvisCore Package: OK
✓ Dependencies: OK
✓ .env File: OK
✓ Claude/Azure/Gemini: OK
✓ Sandbox Mode: OK

✓ All checks passed! Ready to use JarvisCore.
```

### Step 4: Run Smoke Test (1 minute)
```bash
python -m jarviscore.cli.smoketest
```

**Expected output:**
```
✓ Import Framework (0.02s)
✓ Configuration (0.01s)
✓ Create Mesh (0.00s)
✓ Define Agent (0.00s)
✓ End-to-End Workflow (4.23s)
  Task: '2 + 2' → Result: 4
  Execution time: 3.84s
  Repairs: 0

✓ All smoke tests passed!
```

### Step 5: Try Examples (2 minutes)
```bash
# Calculator agent
python examples/calculator_agent_example.py

# Research agent (with web search)
python examples/research_agent_example.py

# Multi-agent workflow
python examples/multi_agent_workflow.py
```

### Step 6: Run Test Suite (Optional, 3 minutes)
```bash
# Run all 88 framework tests
pytest tests/ -v
```

---

## Success Criteria

A user should be able to:

| Step | Time | Success Metric |
|------|------|----------------|
| Install | <1 min | `pip install` completes without errors |
| Configure | <5 min | `.env` file created with valid API key |
| Validate | <1 min | Health check shows all green checkmarks |
| First run | <1 min | Smoke test passes with result=4 |
| Examples | <5 min | All 3 examples execute successfully |

**Total time to success:** ~10-15 minutes

---

## Common Test Scenarios

### Scenario 1: Fresh Installation (Happy Path)
```bash
pip install jarviscore
cp .env.example .env
# Edit .env, add CLAUDE_API_KEY
python -m jarviscore.cli.check --validate-llm
python -m jarviscore.cli.smoketest
python examples/calculator_agent_example.py
```

**Expected:** All pass ✅

---

### Scenario 2: Missing API Key
```bash
pip install jarviscore
# Don't create .env
python -m jarviscore.cli.check
```

**Expected:**
```
⚠ .env File: Not found (will use environment vars)
✗ LLM Configuration: No LLM provider configured

✗ Issues found:
  - No LLM provider configured. AutoAgent requires at least one LLM.

Next Steps:
  1. Copy .env.example to .env
  2. Add your LLM API key...
```

---

### Scenario 3: Invalid API Key
```bash
# .env has invalid key
python -m jarviscore.cli.check --validate-llm
```

**Expected:**
```
✓ Claude: CLAUDE_API_KEY=sk-an...xxxx
✗ Claude API: Error code: 401 - Unauthorized

Troubleshooting:
  - Verify API key is correct
  - Check it hasn't expired
```

---

### Scenario 4: LLM Temporarily Overloaded
```bash
python -m jarviscore.cli.smoketest
```

**Expected:**
```
✓ Import Framework (0.02s)
✓ Configuration (0.01s)
✓ Create Mesh (0.00s)
✓ Define Agent (0.00s)
[Integration Test]
  LLM temporarily unavailable, retrying in 2s...
  Retry attempt 2/3...
✓ End-to-End Workflow (8.45s)
  Task: '2 + 2' → Result: 4
  Retries: 1
```

Test handles retries automatically and succeeds.

---

## Testing Infrastructure

### Files Created

```
jarviscore/
├── cli/                              # NEW: CLI tools
│   ├── __init__.py
│   ├── __main__.py                   # CLI entry point
│   ├── check.py                      # Health check tool
│   └── smoketest.py                  # Smoke test tool
├── docs/
│   ├── USER_GUIDE.md                 # UPDATED: Added testing steps
│   ├── TROUBLESHOOTING.md            # NEW: Common issues guide
│   └── ...
├── pyproject.toml                    # UPDATED: All dependencies
└── README.md                         # UPDATED: Testing workflow
```

### Dependencies Updated

```toml
dependencies = [
    # Core
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",

    # P2P (always included)
    "swim-p2p",
    "pyzmq",

    # Configuration
    "python-dotenv>=1.0.0",

    # Web/HTTP
    "aiohttp>=3.9.0",
    "beautifulsoup4>=4.12.0",

    # LLM Providers
    "anthropic>=0.18.0",
    "openai>=1.0.0",
    "google-generativeai>=0.3.0",

    # Utilities
    "httpx>=0.25.0",
]
```

All dependencies are always installed - no optional packages for core functionality.

---

## Edge Cases Handled

### 1. Rate Limiting
- **Detection:** Checks for error codes 429, 529
- **Handling:** Exponential backoff (2s, 4s, 8s)
- **Max retries:** 3 attempts

### 2. Network Issues
- **Detection:** Timeout errors, connection failures
- **Handling:** Retry with backoff
- **Guidance:** Troubleshooting guide with solutions

### 3. Configuration Errors
- **Detection:** Missing keys, invalid values
- **Handling:** Clear error messages with next steps
- **Guidance:** Shows exact commands to fix

### 4. Platform Differences
- **Windows:** All paths use `Path()` objects
- **Linux:** Tested on Ubuntu 22.04
- **macOS:** Should work (not tested yet)

---

## Performance Baselines

From Day 5 benchmarks:

| Operation | Target | Acceptable Range |
|-----------|--------|------------------|
| Sandbox execution | 3ms | 2-10ms |
| Code generation (LLM) | 3s | 2-5s |
| Simple task (2+2) | 4s | 3-6s |
| Multi-step workflow (2 steps) | 8s | 6-12s |

Smoke test validates these are met.

---

## Documentation

### For Users
1. **README.md** - Installation and quick start
2. **USER_GUIDE.md** - Complete tutorial with testing
3. **TROUBLESHOOTING.md** - Common issues and solutions
4. **API_REFERENCE.md** - Detailed API docs
5. **CONFIGURATION.md** - Environment variables

### For Developers
1. **TESTING_GUIDE.md** (this file) - Testing infrastructure
2. **tests/** - 88 unit/integration tests
3. **examples/** - 3 working examples
4. **benchmark_performance.py** - Performance validation

---

## Rollout Strategy

### Phase 1: Alpha Testing (Current)
- Internal testing only
- Fix critical bugs
- Validate testing tools work

### Phase 2: Beta Testing
- Share with 5-10 early adopters
- Collect feedback on:
  - Installation experience
  - Documentation clarity
  - Common stumbling blocks
- Iterate on testing tools

### Phase 3: Public Release
- Publish to PyPI
- Announce to broader audience
- Monitor GitHub issues
- Provide support

---

## Support Checklist

For users who report issues, ask for:

1. **System info:**
   ```bash
   python --version
   pip show jarviscore
   ```

2. **Diagnostic output:**
   ```bash
   python -m jarviscore.cli.check --verbose
   python -m jarviscore.cli.smoketest --verbose
   ```

3. **Logs:**
   ```bash
   ls -la logs/
   cat logs/<latest>.log
   ```

4. **Minimal reproduction:**
   - Smallest code that shows the problem
   - Expected vs actual behavior

---

## Testing Metrics

Track these for release:

- ✅ **Installation success rate:** Target >95%
- ✅ **First-run success rate:** Target >90%
- ✅ **Avg time to first success:** Target <15 min
- ✅ **Support tickets per user:** Target <0.1
- ✅ **Documentation clarity:** User survey score >4/5

---

*Last updated: 2026-01-13*
*Framework version: 0.1.0*
*Testing tools version: 1.0*
