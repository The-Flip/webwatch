# Webwatch Makefile — all commands run through `uv`, which manages the .venv.
# Override the runner with e.g. `make test UV="uv run --no-sync"`.
UV ?= uv run

.PHONY: help
help:
	@echo "Webwatch project Makefile commands:"
	@echo ""
	@echo "Setup:"
	@echo "  make bootstrap      - Install everything needed for development"
	@echo "  make install        - Sync dependencies into the venv (uv sync)"
	@echo ""
	@echo "Running:"
	@echo "  make check          - Run all checks against live sites (webwatch check --all)"
	@echo ""
	@echo "Testing:"
	@echo "  make test           - Run the fast test suite (excludes integration)"
	@echo "  make test-all       - Run the full suite (includes integration)"
	@echo "  make test-cov       - Run tests with a coverage report"
	@echo "  make test-module M= - Run a single test module/class/test"
	@echo "                        e.g. make test-module M=tests/test_result.py"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint           - Format and lint code (auto-fixes issues)"
	@echo "  make typecheck      - Check Python types with mypy"
	@echo "  make quality        - Lint + typecheck (run before committing)"
	@echo "  make precommit      - Run all pre-commit hooks"
	@echo ""
	@echo "Documentation & plans:"
	@echo "  make agent-docs       - Regenerate CLAUDE.md and AGENTS.md from source"
	@echo "  make review-plan PLAN= - Review a plan doc with the agy CLI"
	@echo "                          e.g. make review-plan PLAN=docs/plans/phase-b.md"

.PHONY: bootstrap
bootstrap: install
	$(UV) pre-commit install
	@test -f .env || cp .env.example .env
	@echo "Bootstrap complete. Edit .env to configure SMTP and runtime options."

.PHONY: install
install:
	uv sync

.PHONY: check
check:
	$(UV) webwatch check --all

.PHONY: test
test:
	$(UV) pytest -m "not integration"

.PHONY: test-all
test-all:
	$(UV) pytest

.PHONY: test-cov
test-cov:
	$(UV) pytest -m "not integration" --cov --cov-report=term-missing

.PHONY: test-module
test-module:
ifndef M
	$(error Usage: make test-module M=tests/test_result.py)
endif
	$(UV) pytest $(M)

.PHONY: lint
lint:
	$(UV) ruff format .
	$(UV) ruff check . --fix

.PHONY: typecheck
typecheck:
	$(UV) mypy webwatch

.PHONY: quality
quality: lint typecheck
	@echo "All quality checks passed!"

.PHONY: precommit
precommit:
	@echo "Running pre-commit checks..."
	$(UV) pre-commit run --all-files

.PHONY: agent-docs
agent-docs:
	$(UV) python scripts/build_agent_docs.py

# Review a plan doc with Google Antigravity's `agy` CLI before implementing it.
# See docs/plans/README.md for the workflow.
.PHONY: review-plan
review-plan:
ifndef PLAN
	$(error Usage: make review-plan PLAN=docs/plans/phase-b.md)
endif
	agy --add-dir "$(dir $(abspath $(PLAN)))" -p "You are a distinguished engineer doing a critical design review. Read $(abspath $(PLAN)) and critique it for soundness, gaps, and risks — especially extraction robustness and the avoidance of false positives/negatives. Do NOT modify any files; provide a written critique only."
