# JarvisCore Dogfooding Log

## Overview
Issues and improvements discovered while using JarvisCore internally
at Prescott Data for Finance and Marketing operations (Team Treasury + Team Signal).

---

### [ISSUE-001] CLI scaffold fails — missing `jarviscore.data` module
- **Discovered**: 2026-04-15
- **System**: Setup / Foundation
- **Severity**: Major
- **Component**: CLI (`jarviscore.cli.scaffold`)
- **Description**: `python -m jarviscore.cli.scaffold --examples` crashes with `ModuleNotFoundError: No module named 'jarviscore.data'`. The `get_data_path()` function in `scaffold.py` calls `resources.files('jarviscore.data')` but the `jarviscore/data/` directory doesn't exist in the repository. The `pyproject.toml` references `jarviscore = ["docs/*.md", "data/.env.example", "data/examples/*.py"]` in `[tool.setuptools.package-data]` but the actual data directory was never committed.
- **Expected**: Scaffold should create `.env.example` and example files in the target directory.
- **Workaround**: Manually copy `.env.example` from repo root and create project structure by hand.
- **Fix**: Create `jarviscore/data/` directory with `__init__.py`, `.env.example`, and `examples/` subdirectory containing the example scripts. Or update `scaffold.py` to use `Path(__file__).parent.parent / '.env.example'` as fallback.
- **Status**: Open
- **PR**: —
