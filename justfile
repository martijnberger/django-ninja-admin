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

typecheck-package:
    UV_CACHE_DIR=.uv-cache uv run ty check django_ninja_admin

typecheck-scripts:
    UV_CACHE_DIR=.uv-cache uv run ty check scripts/dist_check.py scripts/generated_client_smoke.py scripts/openapi_diff.py scripts/openapi_snapshot.py scripts/package_smoke.py scripts/parity_report.py scripts/sample_project_full.py scripts/sample_project_smoke.py scripts/smoke_utils.py

typecheck: typecheck-package typecheck-scripts

pre-commit:
    UV_CACHE_DIR=.uv-cache uv run pre-commit run --all-files

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

openapi-snapshot-check:
    UV_CACHE_DIR=.uv-cache uv run python scripts/openapi_snapshot.py --check

openapi-snapshot-update:
    UV_CACHE_DIR=.uv-cache uv run python scripts/openapi_snapshot.py --update

check: lint format-check typecheck coverage-test dist-check package-smoke sample-project-smoke openapi-snapshot-check generated-client-smoke

ci: check
