# JarvisCore developer tasks. Run `make` or `make help` to list targets.
#
# Overridable variables:
#   PYTHON=python3.12   interpreter used to create the venv
#   T=tests/test_x.py   test path(s) for `make test`, `make test-linux`
#   ARGS="-k redis -x"  extra pytest arguments
#   PY_VERSIONS="3.10 3.11 3.12"  versions for `make test-matrix`
#   BASE=origin/main    ref `make lint-changed` diffs against
#   BIN_DIR=~/bin       where `make install-cli` links the CLI (default: first writable dir on PATH)

PYTHON      ?= python3
VENV        ?= .venv
T           ?= tests
ARGS        ?=
PY_VERSIONS ?= 3.10 3.11 3.12
BASE        ?= origin/main
LINUX_PY    ?= 3.12
BIN_DIR     ?=

PY      := $(VENV)/bin/python
PIP     := $(PY) -m pip
RESULTS := .test-results

.DEFAULT_GOAL := help

.PHONY: help venv install install-full reinstall install-cli uninstall-cli \
        test test-cov baseline regress test-linux test-matrix test-images \
        lint lint-changed build wheel-smoke verify verify-all clean

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Setup ────────────────────────────────────────────────────────────────

$(PY):
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -q --upgrade pip

venv: $(PY) ## Create .venv if missing

install: $(PY) ## Editable dev install (.[dev]) into .venv
	$(PIP) install -q -e ".[dev]"
	@$(PY) -c "from importlib.metadata import version; print('jarviscore-framework', version('jarviscore-framework'), 'installed (editable)')"

install-full: $(PY) ## Editable install with every extra (.[full,dev])
	$(PIP) install -q -e ".[full,dev]"

reinstall: ## Recreate .venv from scratch and install
	rm -rf $(VENV)
	$(MAKE) install

install-cli: install ## Put the dev `jarviscore` and `jc` CLIs on your PATH (symlinks to .venv; code edits apply instantly)
	@dir="$(BIN_DIR)"; \
	if [ -z "$$dir" ]; then \
	  for d in "$$HOME/.local/bin" /opt/homebrew/bin /usr/local/bin; do \
	    case ":$$PATH:" in *":$$d:"*) [ -w "$$d" ] && { dir="$$d"; break; } ;; esac; \
	  done; \
	fi; \
	[ -n "$$dir" ] || { echo "No writable directory on PATH. Run: make install-cli BIN_DIR=~/bin (and add it to PATH)"; exit 1; }; \
	mkdir -p "$$dir"; \
	for name in jarviscore jc; do \
	  target="$(CURDIR)/$(VENV)/bin/$$name"; \
	  if [ -e "$$dir/$$name" ] && [ "$$(readlink "$$dir/$$name")" != "$$target" ]; then \
	    echo "$$dir/$$name exists and is not this dev build; skipping (remove it to link)"; continue; \
	  fi; \
	  ln -sf "$$target" "$$dir/$$name"; \
	  echo "Linked $$dir/$$name -> $$target"; \
	done; \
	case ":$$PATH:" in *":$$dir:"*) ;; *) echo "Add $$dir to your PATH";; esac

uninstall-cli: ## Remove the dev `jarviscore`/`jc` symlinks created by install-cli
	@for name in jarviscore jc; do \
	  target="$(CURDIR)/$(VENV)/bin/$$name"; \
	  for d in $(BIN_DIR) "$$HOME/.local/bin" /opt/homebrew/bin /usr/local/bin; do \
	    if [ "$$(readlink "$$d/$$name" 2>/dev/null)" = "$$target" ]; then rm "$$d/$$name"; echo "Removed $$d/$$name"; fi; \
	  done; \
	done

# ── Tests ────────────────────────────────────────────────────────────────

test: ## Run tests (T=path ARGS="-k name")
	$(PY) -m pytest $(T) -q $(ARGS)

test-cov: ## Run tests with coverage report in htmlcov/
	$(PY) -m pytest $(T) -q --cov=jarviscore --cov-report=term-missing:skip-covered --cov-report=html $(ARGS)

baseline: ## Record which tests pass now (run before starting a milestone)
	$(PY) scripts/test_regress.py baseline $(ARGS)

regress: ## Fail if any test that passed in the baseline now fails
	$(PY) scripts/test_regress.py compare $(ARGS)

# Dependencies live in a cached image (rebuilt only when pyproject.toml changes); each run
# streams just the git-visible source into the container. The security opts let bubblewrap
# create namespaces so the real confinement paths are exercised.
test-image-%:
	@docker build -q -f docker/test/Dockerfile --build-arg PY=$* -t jarviscore-test:$* . >/dev/null
	@echo "test image jarviscore-test:$* ready"

test-linux-%: test-image-%
	@git ls-files -co --exclude-standard | while read -r f; do [ -e "$$f" ] && echo "$$f"; done \
	| COPYFILE_DISABLE=1 tar -cf - -T - \
	| docker run --rm -i \
	    --security-opt seccomp=unconfined --security-opt systempaths=unconfined \
	    jarviscore-test:$* bash -ec '\
	      tar -xf - && pip install -q --no-deps --no-build-isolation -e . \
	      && python -m pytest $(T) -q $(ARGS)'

test-linux: test-linux-$(LINUX_PY) ## Run tests on Linux in Docker as non-root, with bubblewrap available (LINUX_PY=3.12)

test-matrix: $(addprefix test-linux-,$(PY_VERSIONS)) ## Run tests in Docker on each PY_VERSIONS (mirrors CI); add -j3 to run in parallel

test-images: $(addprefix test-image-,$(PY_VERSIONS)) ## Pre-build the cached test images

# ── Quality ──────────────────────────────────────────────────────────────

lint: ## ruff over the whole package (noisy on legacy code)
	$(PY) -m ruff check jarviscore scripts

lint-changed: ## ruff only on .py files changed vs BASE (default origin/main)
	@files=$$(git diff --name-only --diff-filter=AM $(BASE)... -- '*.py'; git ls-files --others --exclude-standard -- '*.py'); \
	if [ -n "$$files" ]; then echo "$$files" | sort -u | xargs $(PY) -m ruff check; else echo "No changed Python files"; fi

# ── Build ────────────────────────────────────────────────────────────────

build: $(PY) ## Build sdist + wheel into dist/ and validate metadata
	$(PIP) install -q build twine
	rm -rf dist build *.egg-info
	$(PY) -m build
	$(PY) -m twine check dist/*

wheel-smoke: build ## Install the built wheel into a fresh venv and check CLI + packaged data
	rm -rf $(RESULTS)/wheel-venv
	$(PYTHON) -m venv $(RESULTS)/wheel-venv
	$(RESULTS)/wheel-venv/bin/pip install -q dist/*.whl
	cd /tmp && $(CURDIR)/$(RESULTS)/wheel-venv/bin/python -c "\
	import jarviscore; \
	from importlib.resources import files; \
	from importlib.metadata import version; \
	assert files('jarviscore.data').joinpath('.env.minimal').is_file(), 'packaged data missing'; \
	assert files('jarviscore.data').joinpath('templates/_common/gitignore').is_file(), 'init templates missing'; \
	print('wheel ok:', version('jarviscore-framework'))"
	$(RESULTS)/wheel-venv/bin/jarviscore check --help >/dev/null && echo "CLI ok"
	rm -rf $(RESULTS)/wheel-init && mkdir -p $(RESULTS)/wheel-init
	cd $(RESULTS)/wheel-init && $(CURDIR)/$(RESULTS)/wheel-venv/bin/jarviscore init demo --template support --provider claude </dev/null >/dev/null
	cd $(RESULTS)/wheel-init/demo && $(CURDIR)/$(RESULTS)/wheel-venv/bin/python -c "\
	from jarviscore.project import load_project; \
	assert set(load_project().project.agents) == {'triage', 'responder'}; \
	print('init from wheel ok')"

# ── Milestone gates ──────────────────────────────────────────────────────

verify: lint-changed regress wheel-smoke test-linux ## Gate after each step: lint changes, no regressions, wheel works, Linux passes

verify-all: verify test-matrix ## Gate after each milestone: verify + full Python version matrix

clean: ## Remove build, test and cache artifacts (keeps .venv and the baseline)
	rm -rf dist build *.egg-info $(RESULTS) .pytest_cache htmlcov .coverage
	find . -name __pycache__ -type d -not -path './$(VENV)/*' -prune -exec rm -rf {} +
