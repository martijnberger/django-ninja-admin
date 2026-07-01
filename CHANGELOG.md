# Changelog

All notable changes to this project will be documented in this file.

This project follows semantic versioning once it leaves alpha. While it remains
pre-release, minor versions may still adjust public API and wire contracts.

## Unreleased

- Added Pydantic-backed custom action input/response schemas through
  `@action(input_schema=..., response_schema=...)`.
- Added support for passing pytest selectors through `just test` and
  `just postgres-test`.
- Added a `just` command surface for local lint, test, package smoke, and full
  check workflows.
- Added a package smoke script that builds the wheel, installs it into an
  isolated target, verifies public API imports, and checks dependency metadata
  for absent DRF/drf-spectacular dependencies.
- Added a sample-project smoke script that installs the wheel into a temporary
  Django project and exercises docs, OpenAPI, app discovery, and a model
  changelist.
- Added env-driven PostgreSQL test settings and a CI PostgreSQL lane.
- Added an initial copyright/license audit document for release hardening.
- Added a release checklist with alpha, beta, and stable readiness criteria.
