# Changelog

All notable changes to this project will be documented in this file.

This project follows semantic versioning once it leaves alpha. While it remains
pre-release, minor versions may still adjust public API and wire contracts.

## Unreleased

- Added changelist row URL and object-permission metadata for detail, change
  form, delete, and view-on-site frontend actions.
- Added image-specific response schema and form metadata for Django
  `ImageField` values, including upload hints and width/height field names.

## 0.1.2 - 2026-07-01

- Aligned date list-filter ranges with Django admin by adding upper bounds for
  date-time choices and clearing stale date filter params when switching ranges.
- Invalidated the lazy Ninja API/OpenAPI cache when global admin actions are
  added or disabled after initial API construction.
- Exposed changelist action placement and selection-counter metadata in the
  typed response config for frontend parity with Django admin action controls.
- Added admin system checks for invalid `list_select_related` types and
  relation paths.
- Added `show_full_result_count` and `show_admin_actions` changelist metadata,
  with `full_count` omitted when full counts are disabled.
- Normalized invalid changelist lookup values into typed 400 responses instead
  of leaking Django ORM conversion errors.
- Added Django-admin-style `NULL` choice handling for choices list filters via
  `__isnull` query strings.
- Matched Django admin related-filter visibility by hiding related filters that
  have only one non-empty choice while still applying their query params, and
  exposing the real related lookup key.
- Rejected invalid `EmptyFieldListFilter` values with typed changelist lookup
  errors instead of treating arbitrary strings as false.
- Hid `SimpleListFilter` instances with no lookup choices, matching Django
  admin's filter output threshold.
- Improved inline mutations so server-side add/change/delete validation returns
  row-indexed errors across the payload before any parent or inline writes occur.
- Added multipart create/update routes for file-field forms, validating the
  JSON `data`/`inlines` parts with generated Pydantic schemas before passing
  uploads to Django `ModelForm` file handling.
- Hardened view-on-site URL resolution so relative model URLs fall back to the
  request host when the configured `Site` row is missing.
- Added Django-admin-style formfield customization hooks for generated forms,
  including `formfield_overrides`, `formfield_for_dbfield()`,
  `formfield_for_foreignkey()`, `formfield_for_manytomany()`, and
  `formfield_for_choice_field()`.
- Added an admin system check that rejects `list_editable` fields omitted from
  the generated admin form by `fields`, `fieldsets`, or `exclude`.
- Expanded date hierarchy metadata with clear/back navigation query strings and
  validation for impossible year/month/day combinations.
- Aligned changelist search `__exact` handling for non-text fields with
  Django admin by casting field values to text instead of coercing search terms.
- Added multi-column ordering state metadata and sort links that preserve other
  active sort columns.
- Corrected the package repository URL to the canonical GitHub remote.

## 0.1.1 - 2026-07-01

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
- Improved changelist search so many-to-many search paths are treated as
  duplicate-prone and automatically return distinct rows.
- Improved bulk list-editable updates so server-side validation collects
  row-indexed errors across the payload before any write occurs.
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
