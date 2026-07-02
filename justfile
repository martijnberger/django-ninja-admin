set dotenv-load := false

test *args:
    UV_CACHE_DIR=.uv-cache uv run pytest {{args}}

postgres-test *args:
    DJANGO_NINJA_ADMIN_TEST_DATABASE=postgres UV_CACHE_DIR=.uv-cache uv run pytest {{args}}

lint:
    UV_CACHE_DIR=.uv-cache uv run ruff check .

package-smoke:
    UV_CACHE_DIR=.uv-cache uv run python scripts/package_smoke.py

sample-project-smoke:
    UV_CACHE_DIR=.uv-cache uv run python scripts/sample_project_smoke.py

parity-report *args:
    UV_CACHE_DIR=.uv-cache uv run python scripts/parity_report.py {{args}}

openapi-diff *args:
    UV_CACHE_DIR=.uv-cache uv run python scripts/openapi_diff.py {{args}}

check: lint test package-smoke sample-project-smoke

ci: check
