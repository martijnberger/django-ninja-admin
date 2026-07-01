set dotenv-load := false

test:
    UV_CACHE_DIR=.uv-cache uv run pytest

lint:
    UV_CACHE_DIR=.uv-cache uv run ruff check .

package-smoke:
    UV_CACHE_DIR=.uv-cache uv run python scripts/package_smoke.py

check: lint test package-smoke

ci: check
