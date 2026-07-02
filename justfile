set dotenv-load := false

test *args:
    UV_CACHE_DIR=.uv-cache uv run pytest {{args}}

coverage-test *args:
    UV_CACHE_DIR=.uv-cache uv run pytest --cov=django_ninja_admin --cov-report=term-missing --cov-report=xml {{args}}

postgres-test *args:
    DJANGO_NINJA_ADMIN_TEST_DATABASE=postgres UV_CACHE_DIR=.uv-cache uv run pytest {{args}}

lint:
    UV_CACHE_DIR=.uv-cache uv run ruff check .

format:
    UV_CACHE_DIR=.uv-cache uv run ruff format .

format-check:
    UV_CACHE_DIR=.uv-cache uv run ruff format --check .

package-smoke:
    UV_CACHE_DIR=.uv-cache uv run python scripts/package_smoke.py

sample-project-smoke:
    UV_CACHE_DIR=.uv-cache uv run python scripts/sample_project_smoke.py

sample-project-full:
    UV_CACHE_DIR=.uv-cache uv run python scripts/sample_project_smoke.py --full

generated-client-smoke:
    UV_CACHE_DIR=.uv-cache uv run python scripts/generated_client_smoke.py

dist-check:
    UV_CACHE_DIR=.uv-cache uv run python scripts/dist_check.py

parity-report *args:
    UV_CACHE_DIR=.uv-cache uv run python scripts/parity_report.py {{args}}

openapi-diff *args:
    UV_CACHE_DIR=.uv-cache uv run python scripts/openapi_diff.py {{args}}

check: lint format-check coverage-test dist-check package-smoke sample-project-smoke generated-client-smoke

ci: check
