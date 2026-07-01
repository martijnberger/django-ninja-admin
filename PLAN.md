# Django Ninja Admin v2 Reimplementation Plan

## Summary

- Build a new Ninja-native package from the empty workspace: distribution `django-ninja-admin`, import package `django_ninja_admin`.
- Target full feature parity with `daemon-bixia/django-api-admin` 1.3.0 before release, but do not preserve DRF imports or old wire shapes.
- Use `django-ninja` 1.6.2 and Pydantic v2; remove `djangorestframework` and `drf-spectacular`.
- Keep Django-admin concepts: site registry, model admins, filters, actions, changelists, inlines, history, autocomplete, view-on-site, checks, and admin log model.

## Public API And Contracts

- Export `site`, `NinjaAdminSite`, `ModelAdmin`, `InlineModelAdmin`, `TabularInline`, `StackedInline`, `action`, `display`, `register`, and admin filter classes from `django_ninja_admin`.
- Usage target:

```python
from django.urls import path
from django_ninja_admin import ModelAdmin, site

from shop.models import Product


class ProductAdmin(ModelAdmin):
    list_display = ("name", "price")
    search_fields = ("name",)


site.register(Product, ProductAdmin)

urlpatterns = [path("admin-api/", site.urls)]
```

- Replace DRF customization with Ninja/Django-native hooks: `form_class`, `output_schema`, `schema_field_overrides`, `get_form_class()`, `get_output_schema()`, `get_form_description()`, plus existing permission/save/queryset/action hooks.
- Serialization and deserialization should use Pydantic where feasible, while preserving Django `ModelForm`/formset validation where it gives admin-grade behavior.
- Default auth is `ninja.security.SessionAuthIsStaff`; `NinjaAdminSite(auth=...)` accepts any Ninja auth callable, sequence, or explicit `None`.
- Use REST-style routes: `GET /apps`, `GET /apps/{app_label}`, `GET /context`, `GET /permissions`, `GET /history`, `GET /autocomplete`, `GET /view-on-site/{content_type_id}/{object_id}`, and model routes under `/{app_label}/{model_name}` for list, detail, create, update, delete, actions, and bulk list-editable updates.
- Use HTTP status codes instead of a required top-level `status` field. Success and error bodies are typed Pydantic schemas; mutation requests use `{data: {...}, inlines?: {app.model: {add: [], change: [], delete: []}}}`.

## Implementation Changes

- Scaffold packaging with `django>=4.2,<6.1`, `django-ninja>=1.6.2,<2`, `pydantic>=2,<3`, Python `>=3.12`, pytest/ruff dev tooling, and MIT plus Django BSD attribution.
- Port reusable admin logic first: registry, decorators, checks, filters, changelist/query handling, quote utilities, deleted-object collection, action dispatch, inline operation validation, and custom `LogEntry` migration/table.
- Build a lazy `NinjaAdminSite` that constructs a `NinjaAPI` and per-model routers after registration/autodiscovery; registration invalidates router/OpenAPI schema caches.
- Generate Pydantic schemas per registered model/operation for OpenAPI and response serialization; use Django `ModelForm`/formset validation internally for admin-grade create/update/inline behavior.
- Implement all site and model endpoints with Ninja function views, transactions around mutations, existing `has_*_permission` checks, `to_field` validation, protected-delete handling, model action execution, list-editable bulk updates, autocomplete pagination, history filtering, and view-on-site URL resolution.
- Register Ninja exception handlers for auth, permission denied, not found, validation, protected delete, suspicious lookup/to-field errors, and unexpected errors, returning consistent typed error bodies.
- Use Ninja's built-in OpenAPI/docs support, stable operation IDs, model tags, dynamic schemas, and rich response maps instead of drf-spectacular hooks.

## Current Parity Status

The package is currently a functional Ninja-native foundation, not a full upstream-parity implementation.

Completed or mostly complete:

- Package scaffold, dependency policy, licenses, app config, default site, lazy API construction, and basic documentation.
- Public exports for `site`, `NinjaAdminSite`, `ModelAdmin`, inlines, decorators, registration, and package-owned admin filter classes.
- Core site/model routes for apps, context, permissions, history, autocomplete, view-on-site, changelist, detail, add/change/delete, actions, and bulk updates.
- Default `SessionAuthIsStaff`, explicit `auth=None`, and custom auth callable support.
- Basic Pydantic request envelopes and typed response schemas.
- Dynamic Pydantic output schemas with FK labels, many-to-many IDs, and `schema_field_overrides`.
- Dynamic per-model Pydantic request schemas for create, replace, partial update, and list-editable bulk update payloads.
- Dynamic per-inline Pydantic operation schemas for add/change/delete payloads, exposed under the real `app.model` inline wire keys.
- Dynamic per-model action payload schemas with OpenAPI enums for registered/global action names.
- Custom actions can now declare Pydantic/Ninja input and response schemas through `@action(input_schema=..., response_schema=...)`; input schemas are validated before dispatch and exposed as discriminated per-action OpenAPI payload variants.
- Model routes now advertise richer OpenAPI response maps for typed error bodies, including normalized `422` request-validation responses.
- Pydantic/Ninja request validation errors are normalized into typed API error bodies.
- Django `ModelForm` and inline formset validation for create/update/inline mutations.
- Mounted-route tests now cover `save_model`, `save_related`, `response_add`, `response_change`, `delete_model`, `delete_queryset`, and `response_delete` hooks during add/change/delete mutations.
- Inline mutations reject duplicate change/delete PKs and rows that attempt to change and delete the same inline object.
- Inline mutation tests now cover unknown inline objects and transaction rollback of parent saves when inline validation fails.
- Inline mutations now distinguish unknown inline IDs from configured-but-forbidden inline operations, returning permission errors for forbidden add/change/delete attempts.
- Inline mutations reject unknown or readonly row fields before formset save so ignored client input cannot silently pass.
- Bulk list-editable updates use strict row schemas, reject duplicate PKs, and validate all rows before writing.
- Bulk list-editable updates now skip save hooks and empty change-log entries for unchanged rows while still returning validated row data.
- Direct delete and default `delete_selected` return structured protected-object and permission-needed details.
- Model detail/form/delete routes now reject bad `_to_field` references with typed validation errors.
- History listing now filters by caller-visible models before pagination and supports app/model/object/action filters with typed bad-param handling.
- Autocomplete now returns typed not-found responses for invalid pages and has coverage for many-to-many source fields.
- View-on-site route coverage now includes callable hooks that return absolute or protocol-relative external URLs.
- Change messages include field labels and inline add/change/delete entries for history/log consumers.
- Actions cover custom return values, empty-selection validation, and `select_across` behavior over filtered changelists.
- Form descriptions include richer widget, validator, relation, numeric-bound, decimal-precision, choice, disabled, readonly, model `blank`/`null`, uniqueness/index, default, and upload metadata.
- Permission hardening for actions, autocomplete, view-on-site, and object-level bulk updates.
- Ninja-native `ChangeList` foundation for validated lookup params, shared action/changelist querysets, search, ordering, pagination, show-all behavior, `list_select_related`, `date_hierarchy`, and facet counts.
- Package-owned list filter classes for simple, field, choices, related, related-only, boolean, date, all-values, and empty-value filters, with Pydantic-safe filter metadata.
- Expanded changelist metadata for display links, sortable columns, sort query strings, selected ordering, search fields, pagination state, facets, and date hierarchy choices.
- Initial N+1 hardening through automatic `select_related()` for direct relation fields in `list_display`.
- Phase 0 parity matrix at `docs/parity-matrix.md`.
- Initial admin system checks for display, form layout, filters, search/order fields, relation widgets, radio fields, widget-option conflicts, date hierarchy, actions, and inlines.
- `get_changelist()` and `get_changelist_instance()` hooks for changelist customization.
- Initial site/model custom view support through `admin_view()`, `get_urls()`, and `route()` helpers, including OpenAPI registration, raw bound method wrapping, route tags/descriptions, hidden routes, and explicit route-level `auth=None`.
- Custom admin view tests now cover named Ninja response schemas together with route-level auth overrides.
- Display decorator metadata for descriptions, ordering, booleans, and per-field empty values is reflected in changelist columns/results.
- File field read serialization now uses typed Pydantic metadata (`name`, `url`) and form descriptions expose multipart/current-file hints.
- Existing file fields can be cleared in JSON mutations by sending explicit `null`, using Django's form clear semantics and recording change messages.
- Many-to-many fields now have Pydantic write schemas, JSON-safe change-form values, form relation metadata, output serialization, and create/update persistence coverage.
- Form field descriptions now expose per-field admin widget intent for autocomplete, raw-id, radio, filter-horizontal/filter-vertical, and prepopulated fields.
- Custom `form_class` is covered through mounted Ninja routes for write-schema generation, custom widget attributes, Django form validation, and mutation persistence.
- Semantic OpenAPI contract tests now cover model-route operation IDs, tags, security, request body schemas, success response schemas, and typed error response maps.
- Migration and authentication docs now cover replacing DRF serializer hooks with `form_class`, `output_schema`, and `schema_field_overrides`, plus default/custom/disabled auth patterns.
- Local release gates now use `just` for lint, tests, package smoke, and aggregate checks.
- Package smoke tooling builds the wheel, installs it into an isolated target, verifies public API imports, and checks dependency metadata for absent DRF/drf-spectacular dependencies.
- Sample-project smoke tooling installs the built wheel into a temporary Django project, registers a model, mounts `site.urls`, opens docs/OpenAPI, and exercises the registered model app list/changelist.
- Release hardening docs now include a changelog and explicit alpha/beta/stable checklist.
- GitHub Actions now runs the `just` gates across Django 4.2, 5.0, 5.1, 5.2, and an experimental 6.0 lane.
- CI now has a PostgreSQL lane using env-driven test database settings and `just postgres-test`.
- An initial copyright/license audit records MIT package licensing, Django BSD attribution, upstream parity references, and no-DRF dependency checks.
- Initial behavioral tests and no DRF/drf-spectacular runtime dependency.

Known non-parity areas:

- Changelist behavior is still not fully equivalent to upstream `ChangeList`; deeper query-string behavior, result rendering metadata, list-editable formset parity, and broader N+1 hardening still need work.
- Filter handling now covers common Django admin filter families plus initial facets, but it still needs semantic comparison against Django/upstream edge cases and richer facet/count behavior.
- System checks now cover common invalid configurations and relation/widget option conflicts, but they do not yet match Django's complete check coverage or IDs.
- Action payload schemas now advertise action names, discriminated per-action input payload variants, and optional custom response schema unions.
- Field metadata now covers common widget, custom widget attrs, relation, choice, validator, numeric, decimal, readonly, model `blank`/`null`/default/index/unique/editable attributes, initial file attributes, basic file clearing, basic many-to-many values/widgets, and admin widget intent for raw-id/radio/prepopulated/autocomplete/filter-horizontal/filter-vertical fields, but multipart file uploads, image-specific behavior, custom model fields, and advanced widget behavior still need deeper parity.
- Save/delete and response hooks, inline formsets, typed operation schemas, protected-delete details, history permission filtering, autocomplete pagination, `_to_field` validation, inline permission checks, readonly/unknown inline field rejection, unchanged bulk-row handling, and stricter bulk validation are now used, but upstream-style error semantics and edge-case coverage are not exhaustive.
- OpenAPI generation works and now has semantic contract coverage for core model routes and custom action input/response schemas, but broader snapshots and example coverage are still needed before release.
- Admin extensibility is still young: custom view routing, route metadata/auth overrides, named response-schema coverage, and display metadata exist, but deeper multi-auth and override-hook parity need work.
- Release hardening has local/CI `just` gates, wheel import smoke, a clean sample-project smoke, initial PostgreSQL CI coverage, and an initial copyright audit; remaining work is to confirm CI results and repeat the audit before release candidates.
- Upstream fixture parity and contract comparisons have not been ported beyond the initial parity matrix.

## Implementation Phases

### Phase 0: Parity Baseline And Fixture Port

Goal: make upstream parity measurable before adding more behavior.

- Build a parity matrix from `django-api-admin` 1.3.0 modules and `tests/mock_app/tests.py`, grouped by site routes, model routes, changelist, filters, forms, actions, inlines, deletion, logs, OpenAPI, and checks.
- Port the upstream mock app into local tests using Django Ninja Admin names and v2 JSON envelopes.
- Mark each upstream behavior as `implemented`, `intentionally changed`, `not applicable`, or `missing`.
- Add regression tests for every already-implemented behavior so later phases do not drift.
- Add CI commands for `ruff`, `pytest`, package build, import smoke, and no-DRF/no-drf-spectacular import checks.

Acceptance:

- A `docs/parity-matrix.md` or equivalent test manifest exists.
- Existing local behavior is mapped to upstream behaviors.
- Test count is broad enough that a changelist/filter/action regression cannot pass unnoticed.

### Phase 1: Changelist And Filter Parity

Goal: replace the simplified changelist/filter path with Django-admin-grade behavior.

- Port a Ninja-native `ChangeList` equivalent with validated lookup params, `lookup_allowed()`, `to_field`, ordering, search, pagination, show-all behavior, result counts, `list_select_related`, `sortable_by`, and `date_hierarchy`.
- Implement or adapt admin filter classes instead of only re-exporting Django's classes: `SimpleListFilter`, `FieldListFilter`, `RelatedFieldListFilter`, `RelatedOnlyFieldListFilter`, `BooleanFieldListFilter`, `ChoicesFieldListFilter`, `DateFieldListFilter`, `AllValuesFieldListFilter`, and `EmptyFieldListFilter`.
- Preserve query-string behavior for filter choices and ordering links.
- Add facet support for `ShowFacets.NEVER`, `ALLOW`, and `ALWAYS`.
- Ensure invalid lookups, suspicious lookup params, bad pages, and invalid ordering return typed errors.
- Expand changelist response schemas for result metadata, display links, editable fields, filters, facets, ordering columns, and action UI metadata.

Acceptance:

- Upstream changelist/filter/search/order/pagination tests have Ninja equivalents.
- Common Django admin list filters produce equivalent choices and query behavior.
- Large changelists do not issue avoidable N+1 queries for common FK/list-display cases.

### Phase 2: Pydantic Request/Response Schema Generation

Goal: make serialization/deserialization Pydantic-first where feasible, without losing Django form semantics.

- Generate per-model Pydantic request schemas for create, replace, partial update, bulk list-editable update, action payloads, and inline operations.
- Keep Django `ModelForm`/formset validation as the authoritative persistence validator, but use Pydantic to parse, coerce, and document request bodies before forms run.
- Support field-type overrides for model fields, form fields, computed display fields, file/image URL fields, and custom admin fields.
- Distinguish read schemas from write schemas, including readonly fields, excluded fields, password fields, m2m fields, FK labels, and custom output fields.
- Make OpenAPI components stable and deterministic across registrations.
- Add schema cache invalidation when admins are registered/unregistered or output hooks change.

Acceptance:

- OpenAPI shows concrete per-model payloads instead of only `dict[str, Any]`.
- Pydantic validation errors return consistent typed error bodies.
- File/image/custom fields have explicit schema tests.

### Phase 3: Mutation, Inline, And Delete Semantics

Goal: match Django admin and upstream mutation behavior under real-world edge cases.

- Complete add/change/delete parity for `save_form`, `save_model`, `save_related`, `delete_model`, `delete_queryset`, and response hooks.
- Expand inline operation support for partial changes, unknown objects, duplicate PKs, deleted changed rows, min/max, readonly fields, parent permission constraints, nested validation errors, and transaction rollback.
- Improve list-editable bulk updates to follow changelist formset semantics, including per-row errors and unchanged rows.
- Finish protected-delete semantics for direct delete and `delete_selected`, including returned protected object descriptions and permission-needed details.
- Improve change-message construction to include field labels and inline additions/changes/deletions.
- Add tests for bad `_to_field`, protected delete, invalid actions, `select_across`, empty selections, and custom action return values.

Acceptance:

- Mutation routes are atomic across parent and inline work.
- Log entries and change messages match Django-admin semantics where the v2 API has equivalent concepts.
- Direct delete and default bulk delete are covered by protected object and permission tests.

### Phase 4: Admin API Surface, Checks, And Extensibility

Goal: support mature Django-admin customizations, not just basic model CRUD.

- Port/administer real checks for `list_display`, `list_display_links`, `list_editable`, `fieldsets`, `fields`, `exclude`, readonly fields, inlines, autocomplete fields, raw-id fields, filters, search fields, ordering, actions, and custom forms.
- Implement site/model custom view support: `admin_view`, site `get_urls()`, model admin `get_urls()`, and safe route registration into the Ninja API.
- Support per-view/per-route tags, operation IDs, permissions, auth overrides, and response schemas for custom admin views.
- Expand decorators to cover Django admin display semantics such as boolean display, ordering, empty values, descriptions, and admin action permissions.
- Add `get_changelist()`, `get_changelist_instance()`, and related hooks where useful for compatibility with Django-admin mental models.

Acceptance:

- Invalid admin configurations fail through Django checks rather than runtime surprises.
- A project can add custom site/model admin endpoints without bypassing auth, permission checks, or OpenAPI generation.

### Phase 5: Field, Form, And Media Parity

Goal: make forms rich enough for a frontend to render a serious admin UI.

- Expand form-field descriptions for widgets, choices, validators, help text, initial values, required/blank/null, disabled/readonly, max/min, decimal precision, upload constraints, and relation metadata.
- Add file and image field handling for reads, writes, clear/delete behavior, existing file URLs, storage errors, and multipart request support where Ninja supports it.
- Support many-to-many, raw ID, radio fields, filter-horizontal/filter-vertical, prepopulated fields, autocomplete fields, and readonly/display values in form descriptions.
- Add support for custom `form_class`, custom field widgets, and per-field schema overrides in both forms and OpenAPI.

Acceptance:

- A frontend can render add/change forms for common Django model field types without hardcoded per-model knowledge.
- File/image field tests pass for create, update, clear, and response serialization.

### Phase 6: OpenAPI, Docs, And Contract Stability

Goal: make generated docs a release-quality contract.

- Stabilize operation IDs, tags, response maps, error schemas, pagination schemas, inline schemas, and model component names.
- Document every built-in route with examples for success and error responses.
- Add snapshot or semantic OpenAPI tests that tolerate ordering differences but catch contract regressions.
- Add docs for migrating DRF `serializer_class` customizations to `form_class`, `output_schema`, and `schema_field_overrides`.
- Document authentication choices: default staff-session auth, custom Ninja auth, multiple auth callables, and explicit unauthenticated APIs with `auth=None`.

Acceptance:

- `/admin-api/docs` is useful for client generation.
- OpenAPI changes are intentional and reviewed through tests.

### Phase 7: Release Hardening

Goal: reach the original "no public release until full parity" bar.

- Run the full local test suite across Django 4.2, 5.0, 5.1, 5.2, and the latest supported 6.0 pre-release when practical.
- Test against SQLite and PostgreSQL.
- Add package build checks and install smoke tests in a clean sample Django project.
- Audit copyright notices for Django-derived and upstream-derived code.
- Add `CHANGELOG.md`, release checklist, version policy, and explicit alpha/beta/stable criteria.
- Confirm no DRF or drf-spectacular imports at runtime or in dependency metadata.

Acceptance:

- A clean Django project can install the package, register realistic models, mount `site.urls`, open docs, and complete the parity matrix.
- All parity gaps are either implemented or explicitly documented as v2 intentional differences.

## Test Plan

- Port upstream behavioral coverage: registration, app list/index/context, permission denial, view-on-site, autocomplete, detail, actions, default delete action, select-across, invalid actions, delete/protected delete/bad `to_field`, add/change forms, add/change mutations, pagination, changelist, schema generation, and inline add/change/delete/error cases.
- Add Ninja-specific tests for OpenAPI generation, docs availability, Pydantic request validation, custom auth callables, `SessionAuthIsStaff`, error response shapes, file/image fields, and no imports from DRF or drf-spectacular.
- Run contract-style semantic comparisons against upstream fixtures where practical: same registered model behavior, permissions, filtering/search/order results, inline constraints, log entries, and change messages, without requiring identical JSON envelopes.
- Acceptance: a clean Django project can install the package, add `django_ninja_admin` to `INSTALLED_APPS`, register models, mount `site.urls`, open `/admin-api/docs`, and exercise every parity feature successfully.

## Assumptions

- This is a v2 package, not a drop-in replacement for existing DRF clients.
- No public release happens until full parity is implemented and tested.
- Existing DRF `serializer_class` customizations migrate to `form_class` and/or `output_schema`.
- The implementation may reuse/port Django-derived logic with BSD notices and upstream MIT-attributed logic where appropriate.
