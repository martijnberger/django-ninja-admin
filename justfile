set dotenv-load := false

test:
    UV_CACHE_DIR=.uv-cache uv run pytest

lint:
    UV_CACHE_DIR=.uv-cache uv run ruff check .

package-smoke:
    UV_CACHE_DIR=.uv-cache uv run python scripts/package_smoke.py

sample-project-smoke:
    UV_CACHE_DIR=.uv-cache uv run python scripts/sample_project_smoke.py

check: lint test package-smoke sample-project-smoke

ci: check
