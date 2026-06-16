.PHONY: lint fmt typecheck security check test clean sync

# --- Environment ---

sync:
	uv sync --all-extras

# --- Quality ---

lint:
	uv run ruff check src/

fmt:
	uv run ruff format src/ --check

fmt-fix:
	uv run ruff format src/

typecheck:
	uv run mypy src/

check: lint fmt typecheck
	@echo "---"
	@echo "All checks passed."

# --- Testing ---

test:
	uv run python -m pytest tests/ --cov=src/opener -v

test-verbose:
	uv run python -m pytest tests/ -v --tb=long --cov=src/opener --cov-report=term-missing

# --- Cleanup ---

clean:
	rm -rf .venv/ __pycache__/ .pytest_cache/ .ruff_cache/ *.egg-info
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
