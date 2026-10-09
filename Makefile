.PHONY: install test test-security test-full test-cov lint format clean run dev help check check-all build

PYTHON ?= python3
PIP ?= pip
VENV ?= .venv

help:
	@echo "Targets:"
	@echo "  install     Install package and deps (editable)"
	@echo "  install-dev Install with dev extras"
	@echo "  test        Run tests with pytest"
	@echo "  test-security Run security + CLI parser tests only"
	@echo "  test-full   Run full suite with coverage gate (>=90%)"
	@echo "  test-cov    Run tests with coverage"
	@echo "  lint        Run ruff lint"
	@echo "  format      Run ruff format"
	@echo "  clean       Remove build artifacts"
	@echo "  run         Run launcher TUI"
	@echo "  run-list    Run --list"
	@echo "  check       Lint + tests"
	@echo "  check-all   Lint + full suite with coverage gate"
	@echo "  build       Build standalone Linux binary (dist/)"
	@echo "  dev         Install dev deps and run tests"

install:
	$(PYTHON) -m pip install -e .

install-dev:
	$(PYTHON) -m pip install -e ".[dev,watch]"
	$(PYTHON) -m pip install textual watchdog

test:
	uv run pytest tests -v

test-security:
	uv run pytest tests/test_security.py tests/test_cli.py -v

test-full:
	uv run pytest tests -v --cov=e_app_launcher --cov-report=term-missing --cov-fail-under=90

test-cov:
	uv run pytest tests -v --cov=e_app_launcher --cov-report=term-missing

lint:
	uv run ruff check e_app_launcher tests

format:
	uv run ruff check --fix e_app_launcher tests
	uv run ruff format e_app_launcher tests

clean:
	rm -rf build dist *.egg-info e_app_launcher.egg-info
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

run:
	$(PYTHON) -m e_app_launcher

run-list:
	$(PYTHON) -m e_app_launcher --list

run-verbose:
	$(PYTHON) -m e_app_launcher --verbose --list

check:
	$(MAKE) lint
	$(MAKE) test

check-all:
	$(MAKE) lint
	$(MAKE) test-full

build:
	uv run --with pyinstaller pyinstaller --noconfirm --clean e-applauncher.spec
	./dist/e-applauncher --version
