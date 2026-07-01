# Changelog

All notable changes to this project will be documented in this file.

This project follows semantic versioning once it leaves alpha. While it remains
pre-release, minor versions may still adjust public API and wire contracts.

## Unreleased

- Added Pydantic-backed custom action input/response schemas through
  `@action(input_schema=..., response_schema=...)`.
- Added discriminated per-action request payload variants for action OpenAPI
  schemas.
- Hardened inline mutations so configured-but-forbidden inline operations
  return permission errors instead of unknown-inline validation errors.
- Hardened inline mutations so unknown or readonly inline row fields return
  validation errors instead of being silently ignored.
- Improved bulk list-editable updates so unchanged rows are validated and
  returned without invoking save hooks or writing empty change-log entries.
- Tightened `_to_field` validation to follow Django-admin relation-target
  semantics instead of allowing arbitrary fields from related models.
- Hardened history listing with permission-aware querysets, app/model/action
  filters, and typed errors for invalid history parameters.
- Hardened autocomplete pagination and added coverage for many-to-many source
  fields using the same endpoint contract.
- Added mounted-route coverage for callable `view_on_site` hooks returning
  absolute and protocol-relative external URLs.
- Added custom admin route coverage for named Ninja response schemas alongside
  route-level auth overrides.
- Added an admin check that rejects direct many-to-many fields in
  `list_display`, matching Django-admin semantics.
- Added explicit registry contract tests for option-based registration,
  duplicate/unregistered errors, abstract-model rejection, and `@register`.
- Added property-aware changelist display metadata so model properties can
  carry labels, boolean flags, and empty-value text from their getter.
- Improved inline deletion change messages so logs preserve the deleted
  inline object's display text while keeping public mutation responses stable.
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
