.PHONY: preflight sync run clean screenshots test test-backend test-ui lint format typecheck check

preflight:
	bash scripts/preflight.sh

clean:
	rm -f manygameshow.db

screenshots:
	uv run python scripts/screenshots.py

sync:
	uv sync --extra dev

run:
	uv run uvicorn manygameshow.main:app --reload

test: test-backend test-ui

test-backend:
	uv run pytest tests/test_api tests/test_models --cov=manygameshow --cov-report=term-missing

test-ui:
	uv run playwright install --with-deps chromium
	uv run pytest tests/test_ui

lint:
	uv run ruff check .
	uv run djlint src/manygameshow/static --check

format:
	uv run ruff format .

typecheck:
	uv run mypy src/

check: lint typecheck test
