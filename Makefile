# ZYKO — developer tasks (Linux / macOS / Termux / WSL)
.PHONY: help install install-dev test coverage lint format security bench-demo docker-build clean

help:
	@echo "ZYKO developer tasks:"
	@echo "  make install      install into the current environment"
	@echo "  make install-dev  install with test/lint tooling"
	@echo "  make test         run the test suite"
	@echo "  make coverage     test suite with coverage report"
	@echo "  make lint         ruff check (config in pyproject.toml)"
	@echo "  make format       ruff format + import sorting"
	@echo "  make security     bandit static analysis + pip-audit"
	@echo "  make bench-demo   reproducible benchmark in offline demo mode"
	@echo "  make docker-build build the gateway container image"

install:
	pip install .

install-dev:
	pip install -e .[dev]

test:
	pytest -q

coverage:
	pytest -q --cov=src/zyko --cov-report=term-missing

lint:
	ruff check src tests benchmarks
	ruff format --check src tests benchmarks

format:
	ruff format src tests benchmarks
	ruff check --fix src tests benchmarks

security:
	bandit -c pyproject.toml -r src/zyko
	pip-audit --skip-editable

bench-demo:
	zyko bench --demo --update-ledger

docker-build:
	docker build -t zyko:latest .

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache .coverage
	find . -name __pycache__ -type d -exec rm -rf {} +
