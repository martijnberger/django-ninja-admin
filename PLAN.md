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

- Scaffold packaging with `django>=5.0,<6.1`, `django-ninja>=1.6.2,<2`, `pydantic>=2,<3`, Python `>=3.12`, pytest/ruff dev tooling, and MIT plus Django BSD attribution.
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
- Registry coverage now includes option-based registration, duplicate/unregistered errors, abstract-model rejection, swapped-model skipping, and the public `@register` decorator.
- Core site/model routes for apps, context, permissions, history, autocomplete, view-on-site, changelist, detail, add/change/delete, actions, and bulk updates.
- Context metadata honors custom site title/header/url/sidebar settings and uses `NinjaAdminSite.has_permission()` for permission status.
- Permissions metadata includes site-level `has_permission` and is covered for default staff-session and explicit `auth=None` sites.
- Default `SessionAuthIsStaff`, explicit `auth=None`, custom auth callable, and multiple Ninja auth callable support.
- Basic Pydantic request envelopes and typed response schemas.
- Dynamic Pydantic output schemas with FK labels, many-to-many IDs, and `schema_field_overrides`.
- `schema_field_overrides` now serialize computed `ModelAdmin` methods, matching the documented Ninja-native output customization pattern.
- Dynamic per-model Pydantic request schemas for create, replace, partial update, and list-editable bulk update payloads.
- Dynamic per-inline Pydantic operation schemas for add/change/delete payloads, exposed under the real `app.model` inline wire keys.
- Disabled Django form fields remain visible in form metadata but are not required by generated parent or inline Pydantic write schemas.
- Dynamic per-model action payload schemas with OpenAPI enums for registered/global action names.
- Custom actions can now declare Pydantic/Ninja input and response schemas through `@action(input_schema=..., response_schema=...)`; input schemas are validated before dispatch and exposed as discriminated per-action OpenAPI payload variants.
- Action system checks now validate `allowed_permissions` entries while preserving custom `has_<permission>_permission()` hooks.
- Global action changes now invalidate the lazy Ninja API/OpenAPI cache so action payload schemas stay current after initial API construction.
- Built-in site routes now advertise typed OpenAPI auth-error responses, while omitting auth-only responses for explicit `auth=None` sites.
- Model routes now advertise richer OpenAPI response maps for typed error bodies, including conditional `401` auth failures and normalized `422` request-validation responses.
- Pydantic/Ninja request validation errors are normalized into typed API error bodies.
- Django `ModelForm` and inline formset validation for create/update/inline mutations.
- Mounted-route tests now cover `save_form`, `save_model`, `save_related`, `response_add`, `response_change`, `delete_model`, `delete_queryset`, and `response_delete` hooks during add/change/delete mutations, plus `save_form` skipping for unchanged bulk rows.
- `response_add` and `response_change` hooks can return Ninja `Status` values for custom success status/body responses, and model mutation routes advertise common alternate success responses in OpenAPI.
- Inline mutations reject duplicate change/delete PKs and rows that attempt to change and delete the same inline object.
- Inline mutation tests now cover unknown inline objects and transaction rollback of parent saves when inline validation fails.
- Inline mutations now distinguish unknown inline IDs from configured-but-forbidden inline operations, returning permission errors for forbidden add/change/delete attempts.
- Inline mutations reject unknown or readonly row fields before formset save so ignored client input cannot silently pass.
- Inline mutations now aggregate server-side add/change/delete row errors before any parent or inline writes occur.
- Admin system checks now reject non-sequence `inlines` configurations before validating individual inline classes.
- Admin system checks now validate inline `extra`, `min_num`, and `max_num` option types before formset construction.
- Inline admins now support custom `formset` classes and validate that they inherit from Django's `BaseInlineFormSet`.
- Inline admin checks now reject `exclude` entries that remove the parent foreign key field from inline forms.
- Inline formset mutation rows now normalize Pydantic-cleaned values before
  Django form binding, including `MultiValueField` expansion for custom inline
  forms.
- Bulk list-editable updates use strict row schemas, reject duplicate PKs, and validate all rows before writing.
- Bulk list-editable updates now resolve target rows through the filtered
  changelist queryset so active filters/search constrain editable rows before
  any writes occur.
- Changelist responses now expose structured list-editing row metadata with
  row indexes, primary keys, primary-key field names, and editable field
  descriptions for frontend bulk formset rendering.
- List-editable row metadata and bulk updates now honor changelist `_to_field`
  row identity so editable rows can use validated alternate object fields.
- Bulk list-editable updates now skip save hooks and empty change-log entries for unchanged rows, and changed rows also skip log creation when `construct_change_message()` returns no messages.
- Bulk list-editable updates now aggregate server-side row errors before writing.
- Direct delete and default `delete_selected` return structured protected-object and permission-needed details.
- Collected-object delete permission checks now honor object-level delete hooks, including the default `delete_selected` action.
- Direct delete now returns structured permission-needed details when object-level delete hooks deny the target row.
- Model detail/form/update/delete routes now support allowed `_to_field`
  lookups and reject bad `_to_field` references with typed validation errors.
- Changelist routes now support allowed `_to_field` lookups by validating the
  requested field and emitting row IDs/object links that use the alternate
  object field.
- History listing now filters by caller-visible models before pagination and supports app/model/object/action filters plus client-controlled page/page-size pagination, typed bad-param handling, structured model identity, and object detail/form links on each viewable row.
- Autocomplete now returns typed not-found responses for invalid pages, exposes richer pagination metadata, and has coverage for many-to-many source fields.
- View-on-site route coverage now includes callable hooks that return absolute or protocol-relative external URLs.
- View-on-site now returns absolute URLs from the configured Site domain and falls back to the request host when that Site row is missing.
- Change messages include field labels and inline add/change/delete entries for history/log consumers.
- Inline deletion change messages now preserve deleted object display text instead of falling back to primary keys.
- Actions cover custom return values, empty-selection validation, and `select_across` behavior over filtered changelists.
- Changelist action metadata now includes declared permission names and hides
  actions whose permission hooks deny the current user.
- Admin system checks now reject non-sequence `actions` configurations before validating registered action names and permission hooks.
- Changelist responses expose action UI placement and selection-counter metadata for frontend action controls.
- Changelist responses expose filter state and clear-all-filters query-string
  metadata for frontend reset controls.
- Changelist responses expose facet optionality plus add/remove facet
  query-string metadata for frontend count toggles.
- Changelist responses expose active search state and clear-search query-string
  metadata for frontend search controls.
- Changelist responses now honor `show_full_result_count` and expose `show_admin_actions` metadata.
- Changelist responses now expose admin-style pagination state with `multi_page`, `pagination_required`, and an elided `page_range`.
- Changelist pagination now honors `ModelAdmin.get_paginator()` overrides in
  addition to custom `paginator` classes.
- Changelist ordering metadata now reflects default `ModelAdmin.ordering` and
  marks default-sorted columns when no explicit `?o=` parameter is present.
- Changelist responses now support callable `list_display` entries with stable response keys, labels, display metadata, admin checks, and `admin_order_field` sorting.
- Form descriptions include richer widget, validator, relation, numeric-bound, decimal-precision, choice, disabled, readonly, model `blank`/`null`, uniqueness/index, default, and upload metadata.
- Form descriptions now expose structured `SelectDateWidget` metadata for
  split date-select rendering, including order, generated field names, choices,
  empty choices, and selected values.
- Form descriptions now expose stable model-field identity metadata, including
  field class, internal type, attname, and database column when available.
- Form descriptions now expose aggregated custom form/widget media assets for
  frontend clients.
- Inline form descriptions now expose formset media assets and use
  `formfield_for_dbfield()` customizations from inline admins.
- Inline admins now honor custom `form_class` definitions for formset metadata,
  Pydantic inline payload schemas, and ModelForm validation.
- Add-form descriptions now honor `get_changeform_initial_data()` and
  querystring-derived initial values, including selected relation labels.
- Pydantic request schemas now use native JSON, UUID, and generic IP address
  types for matching Django form fields.
- Pydantic request schemas now use native duration types, and form descriptions
  expose temporal input formats.
- Pydantic request schemas now use structured date/time tuple payloads for
  Django `SplitDateTimeField`, with mutation normalization into Django
  `MultiWidget` form data.
- Pydantic request schemas now recursively derive fixed tuple payloads for
  generic Django `MultiValueField` subfields, including subfield constraints,
  and normalize them into Django `MultiWidget` form data.
- Pydantic request schemas now cover `FilePathField` fixed filesystem choices,
  and form descriptions expose path, match, recursion, and allow-files/folders
  metadata for frontend renderers.
- Pydantic request schemas now validate `ComboField` values through Django's
  stacked subfield cleaners while exposing representable string constraints,
  and form descriptions expose structured combo subfield metadata.
- Form descriptions now expose grouped choice metadata while preserving
  flattened choice values for simple clients.
- Pydantic request schemas now validate numeric `step_size` constraints and
  expose OpenAPI `multipleOf` hints when they are not offset, while form
  descriptions include step size and offset metadata.
- Pydantic request schemas now run Django date/time/datetime cleaners before
  type validation so custom temporal `input_formats` are accepted by request
  payloads.
- Pydantic request schemas now preserve enum/member validation for typed
  choice fields whose `coerce` hooks produce float, decimal, or UUID values.
- Mutation handling now preserves Pydantic-cleaned Python values when binding
  payloads to Django forms, with targeted normalization for string-oriented
  URL, IP address, and UUID form fields plus mounted-route coverage for those
  scalar form-field bindings.
- Pydantic request schemas now infer typed list entries for multiple-choice
  fields from declared choice values.
- Pydantic request schemas now constrain concrete Django choice values with
  enum-style `Literal` schemas where possible, including grouped choices.
- Pydantic request schemas now infer Django typed choice fields from concrete
  `coerce` hooks such as `int`.
- Pydantic request schemas now validate typed choice fields against declared
  values after coercion while preserving OpenAPI enum metadata.
- Pydantic request schemas now validate Django email form fields using Django's
  email validator.
- Pydantic request schemas now use native URL validation for Django URL form
  fields.
- Pydantic request schemas now carry Django form string length, field/validator
  regex pattern, numeric bound, and decimal precision constraints into
  generated validation/OpenAPI schemas.
- Form descriptions now expose widget template, fieldset, format, and
  `MultiWidget` subwidget metadata for richer frontend rendering.
- Raw-id form field descriptions now include structured lookup request metadata.
- Filter-horizontal and filter-vertical form field descriptions now include
  structured selector metadata.
- Form descriptions now expose JSON-safe field error messages, localization
  flags, and structured radio/prepopulated field metadata.
- Form descriptions now expose structured validator metadata, including limit
  values and regex patterns, alongside existing validator names.
- Form descriptions now support callable `readonly_fields`, exposing stable string names, labels, values, and display metadata while accepting them in admin checks.
- Explicit `fields` and `fieldsets` layouts now treat callable readonly fields
  by their stable display names when validating checks and generating
  `ModelForm` classes.
- Permission hardening for actions, autocomplete, view-on-site, and object-level bulk updates; autocomplete now uses the remote model admin's paginator and search-field hooks.
- Autocomplete now resolves related option IDs from the source relation's
  actual target field, including `ForeignKey(to_field=...)` relations to unique
  non-primary-key fields.
- Ninja-native `ChangeList` foundation for validated lookup params, shared action/changelist querysets, search, ordering, pagination, show-all behavior, `list_select_related`, `date_hierarchy`, and facet counts.
- Date hierarchy metadata now exposes field type and active timezone for
  `DateTimeField` buckets, and changelist bucketing explicitly uses the active
  timezone.
- Changelist search now applies distinct results for duplicate-prone many-to-many search paths.
- Changelist search now covers Django-style prefix and lookup-suffix behavior, including non-text `__exact` searches that cast field values to text.
- Package-owned list filter classes for simple, field, choices, related, related-only, boolean, date, all-values, and empty-value filters, with Pydantic-safe filter metadata.
- Date list filters now use Django-admin-style bounded ranges and clear stale grouped date params when switching choices.
- Choices list filters now support explicit `NULL` choices with `__isnull` query behavior.
- All-values list filters now support explicit `NULL` choices with `__isnull` query behavior.
- List filters now reject malformed `__isnull` boolean values with typed lookup errors.
- Related list filters now hide when they have only one non-empty choice, still apply hidden-filter query params, and expose their real lookup keys, matching Django admin's output threshold.
- Related list filters now expose many-to-many empty-relation choices and related-only filters preserve related-admin ordering while limiting choices to used relations.
- Empty-value list filters now validate `__isempty` values and return typed lookup errors for invalid input.
- Simple list filters now hide when `lookups()` returns no choices, matching Django admin.
- Changelist facet handling now has mounted-route coverage for `ShowFacets.NEVER`, `ALLOW`, and `ALWAYS`.
- Field-based `list_filter` tuple entries now validate as two-item `(field, FieldListFilter)` declarations at check and runtime boundaries.
- Invalid changelist lookup values now return typed API errors for both declared filters and direct field lookups.
- `lookup_allowed()` now allows local field lookup suffixes and Django-style `limit_choices_to` reverse-FK lookup parameters while continuing to reject unapproved relational lookups.
- Expanded changelist metadata for display links, sortable columns, multi-column sort state/query strings, selected ordering, search fields, pagination state, facets, and date hierarchy choices.
- Generated changelist query strings now reset stale page parameters for
  filter, ordering, and date hierarchy links while preserving explicit page-size
  state.
- Changelist rows now expose detail, change-form, delete, view-on-site, and object-permission metadata for frontend action rendering.
- Changelist columns now support single-valued relation paths in `list_display`,
  including row values and ordering metadata.
- Date hierarchy metadata now includes clear/back navigation query strings and validates impossible year/month/day combinations.
- Date hierarchy checks and changelist metadata/filtering now support relation paths such as `product__created_at`.
- Date hierarchy navigation now starts at the lowest useful initial level when
  all filtered results share a year or month, matching Django admin's
  drill-down behavior.
- Initial N+1 hardening through automatic `select_related()` for direct relation fields in `list_display`.
- Changelist N+1 hardening now infers `select_related()` paths from single-valued
  relation paths in `list_display`, independent of sortability.
- Changelist N+1 hardening now also infers `select_related()` paths from display callables/methods whose `admin_order_field` traverses FK or one-to-one relations.
- Phase 0 parity matrix at `docs/parity-matrix.md`.
- Initial admin system checks for display, form layout, filters, search/order fields, relation widgets, radio fields, widget-option conflicts, date hierarchy, actions, and inlines.
- Relation widget checks now reject reverse relations in `autocomplete_fields` and `raw_id_fields`, preventing frontend metadata for unsupported admin widget targets.
- Autocomplete checks now require related models to be registered with
  `search_fields`, catching endpoint misconfiguration before runtime.
- `prepopulated_fields` system checks now validate dict shape, target field suitability, source-field list shape, and source-field existence.
- `readonly_fields` system checks now reject duplicate string or callable
  entries before they can duplicate form metadata.
- `sortable_by` system checks now validate sequence shape, item types, and membership in `list_display` before changelist sorting runs.
- Admin system checks now reject `ordering` configurations that combine random ordering (`"?"`) with other fields.
- Admin system checks now allow Django ORM ordering expressions and validate `F("field")` references when possible.
- Admin system checks now validate `list_per_page` and `list_max_show_all` types before changelist pagination runs.
- Admin system checks now validate custom `paginator` classes before changelist pagination runs.
- Admin system checks now validate `save_as`, `save_on_top`, and `view_on_site` option types before form/config metadata generation.
- Admin system checks now validate `save_as_continue`, action placement/counter flags, and `show_full_result_count` option types before form/changelist metadata generation.
- `ShowFacets` is exported from the package root and admin system checks now reject malformed `show_facets` values before changelist facet metadata generation.
- Admin system checks now validate `search_help_text` before changelist metadata serialization.
- Admin system checks now reject empty `list_display` configurations before changelist runtime.
- Custom `form_class` system checks now validate `ModelForm` inheritance and catch forms whose declared `Meta.model` does not match the registered admin model.
- `formfield_overrides` system checks now validate field-class keys, mapping-shaped overrides, and string formfield keyword names.
- Admin system checks now reject direct many-to-many and reverse relation fields in `list_display`, preventing raw related managers from leaking into changelist cells.
- Admin system checks now reject `list_editable` fields removed from generated forms by `fields`, `fieldsets`, or `exclude`, preventing silent bulk-update no-ops.
- Admin system checks now reject manual-through many-to-many fields in explicit `fields` and `fieldsets` form layouts.
- Admin system checks now reject first-column `list_editable` fields unless an explicit `list_display_links` target is configured.
- Admin system checks now reject duplicate entries in `list_display_links` and
  `exclude`, plus non-string/non-callable `list_display_links` entries.
- Admin system checks now validate `list_select_related` types and relation paths before changelist runtime.
- Admin system checks now reject `filter_horizontal`/`filter_vertical` on many-to-many fields with custom through models.
- `get_changelist()` and `get_changelist_instance()` hooks for changelist customization.
- Initial site/model custom view support through `admin_view()`, `get_urls()`, and `route()` helpers, including OpenAPI registration, typed custom-route error response maps, raw bound method wrapping, route tags/descriptions, hidden routes, explicit route-level `auth=None`, route-level auth sequence overrides, decorator-style route registration, and stable unique operation IDs for generated and explicit multi-method custom routes.
- Custom admin view tests now cover named Ninja response schemas together with route-level auth overrides.
- Display decorator metadata for descriptions, ordering, booleans, and per-field empty values is reflected in changelist columns/results.
- Changelist display metadata now also recognizes labels, boolean flags, and empty-value text attached to model property getters.
- File field read serialization now uses typed Pydantic metadata (`name`, `url`) and form descriptions expose multipart/current-file hints.
- Image field read serialization now uses typed Pydantic metadata (`name`, `url`, `width`, `height`) and form descriptions expose image/upload hints plus configured width/height field names.
- Existing file fields can be cleared in JSON mutations by sending explicit `null`, using Django's form clear semantics and recording change messages.
- File fields can now be written through multipart create/update routes whose JSON form parts are validated by the generated Pydantic mutation schemas before Django `ModelForm` file handling runs.
- Image fields now have mounted multipart validation coverage for invalid files
  and valid PNG uploads, including persisted dimensions and typed response/form
  metadata.
- Generated Pydantic write schemas now expose file and image fields as
  string-or-null JSON values instead of untyped payload slots, with runtime
  request-validation coverage for malformed JSON values and image clear
  mutations.
- Multipart file parts now satisfy required file fields during Pydantic request
  validation so clients do not need to duplicate uploaded filenames inside the
  JSON `data` part.
- Form descriptions now expose file-extension validator metadata for upload
  controls, with multipart rejection coverage for disallowed extensions.
- Multipart create-route OpenAPI schemas now mark required file parts as
  required alongside the JSON `data` part.
- Many-to-many fields now have Pydantic write schemas, JSON-safe change-form values, form relation metadata, output serialization, and create/update persistence coverage.
- Form field descriptions now expose per-field admin widget intent for autocomplete, raw-id, radio, filter-horizontal/filter-vertical, and prepopulated fields.
- Relation form field descriptions now include structured related-model identity and autocomplete request parameters for frontend clients.
- Relation form field descriptions now include selected option labels for existing foreign-key and many-to-many values.
- Relation form field descriptions now expose model `limit_choices_to` constraints,
  including callable constraints and structured `Q` objects.
- Readonly form descriptions now expose display labels, values, boolean flags, and empty-value fallbacks for admin methods and model properties.
- Custom `form_class` and generated-form `formfield_*` customization hooks are covered through mounted Ninja routes for write-schema generation, custom widget attributes, Django form validation, and mutation persistence.
- History responses now include Django-style human-readable change-message text for parent and inline add/change/delete operations, plus model identity and object-link metadata for frontend routing/rendering.
- Semantic OpenAPI contract tests now cover core site/model route operation IDs, tags, security, request body schemas, success response schemas, and typed error response maps.
- Multipart OpenAPI schemas now mark JSON-encoded `data` and `inlines` form
  parts with `contentMediaType: application/json`.
- API and authentication docs now cover Ninja-native customization hooks such as `form_class`, `output_schema`, and `schema_field_overrides`, plus default/custom/disabled auth patterns.
- Local release gates now use `just` for lint, tests, package smoke, and aggregate checks.
- Package smoke tooling builds the wheel, installs it into an isolated target, verifies public API imports, and checks dependency metadata for absent DRF/drf-spectacular dependencies.
- Sample-project smoke tooling installs the built wheel into a temporary Django project, registers a model, mounts `site.urls`, opens docs/OpenAPI, and exercises the registered model app list/changelist.
- Release hardening docs now include a changelog and explicit alpha/beta/stable checklist.
- GitHub Actions now runs the `just` gates across Django 5.0, 5.1, 5.2, and an experimental 6.0 lane on Python 3.12+.
- CI now has a PostgreSQL lane using env-driven test database settings and `just postgres-test`.
- An initial copyright/license audit records MIT package licensing, Django BSD attribution, upstream parity references, and no-DRF dependency checks.
- Initial behavioral tests and no DRF/drf-spectacular runtime dependency.

Known non-parity areas:

- Changelist behavior now supports `_to_field` validation/row identity, custom paginator hooks, default ordering metadata including visible custom queryset `order_by()` columns, deterministic primary-key fallback ordering, last-page pagination, row/result indexes, page-result/range metadata, page-choice metadata, presence-style show-all handling, pagination/show-all query strings, search/filter-state clear metadata, facet toggle links, bounded date hierarchy filtering including maximum-year bounds, lowest-useful initial date hierarchy levels, and preservation of unrelated lookup params when resetting stale page/order links, but is still not fully equivalent to upstream `ChangeList`; remaining query-string edge cases, richer result rendering metadata, list-editable formset parity, additional date hierarchy edge cases, and broader N+1 hardening still need work.
- Filter handling now covers common Django admin filter families, bounded date filter ranges, and initial facets, but it still needs semantic comparison against Django/upstream edge cases and richer facet/count behavior.
- System checks now cover common invalid configurations, many-to-many `list_display` mistakes, `list_display_links` item-type conflicts, `list_editable` item-type/form-layout conflicts, duplicate `list_editable`/`readonly_fields`, callable readonly field layout names, `list_select_related` mistakes, `date_hierarchy` type/path/field mistakes, autocomplete target registration/searchability, and relation/widget option conflicts, but they do not yet match Django's complete check coverage or IDs.
- Action metadata and payload schemas now advertise action names, permission requirements, discriminated per-action input payload variants, and optional custom response schema unions.
- Field metadata now covers common widget, custom widget attrs, disabled form fields, relation, flat/grouped choice, typed raw choice values, structured validator details, error-message, localization, numeric, decimal, readonly display values, model `blank`/`null`/default/index/unique/editable attributes, initial file/image attributes including storage backends without public URLs, typed file/image JSON write schemas, file-extension upload constraints, basic file/image clearing, multipart file uploads, mounted image validation/dimension persistence, generated-form `formfield_*` customizations, dynamic inline extra form descriptions, basic many-to-many values/widgets, and admin widget intent for raw-id/radio/prepopulated/autocomplete/filter-horizontal/filter-vertical fields, but deeper storage edge cases, custom model fields, and advanced widget behavior still need deeper parity.
- Save/delete and response hooks, including custom `Status` responses from add/change/delete hooks, inline formsets, typed operation schemas, inline multivalue normalization, protected-delete details, history permission filtering, autocomplete pagination/paginator/search-field hooks, `_to_field` changelist/detail/update/delete lookup support, object-level permission checks for custom actions, inline permission checks, readonly/unknown inline field rejection, richer inline delete messages, unchanged and empty-log bulk-row handling, row-indexed inline/bulk errors including permission denials, and stricter bulk validation are now used, but upstream-style error semantics and edge-case coverage are not exhaustive.
- OpenAPI generation works and now has semantic contract coverage for core site/model routes, multipart JSON form parts and required file parts, generated/explicit custom-route operation IDs including multi-method uniqueness, custom-route typed error maps, custom action input/response schemas, and global action cache invalidation, but broader snapshots and example coverage are still needed before release.
- Admin extensibility is still young: custom view routing, direct/decorator route registration, stable generated route operation IDs, route metadata/auth overrides, named response-schema coverage, site/route-level multi-auth coverage, and display metadata exist, but deeper override-hook parity still needs work.
- Release hardening has local/CI `just` gates, wheel import smoke, a clean sample-project smoke, initial PostgreSQL CI coverage, and an initial copyright audit; remaining work is to confirm CI results and repeat the audit before release candidates.
- Upstream fixture parity and contract comparisons have not been ported beyond the initial parity matrix and targeted local registry/route contracts.

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
- Align direct update logging with Django admin by skipping empty change-log entries while preserving save hooks.
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
- Ensure form descriptions use dynamic inline hooks such as `get_extra()`, `get_min_num()`, and `get_max_num()`.

Acceptance:

- A frontend can render add/change forms for common Django model field types without hardcoded per-model knowledge.
- File/image field tests pass for create, update, clear, and response serialization.

### Phase 6: OpenAPI, Docs, And Contract Stability

Goal: make generated docs a release-quality contract.

- Stabilize operation IDs, tags, response maps, error schemas, pagination schemas, inline schemas, and model component names.
- Document every built-in route with examples for success and error responses.
- Add snapshot or semantic OpenAPI tests that tolerate ordering differences but catch contract regressions.
- Document that DRF `serializer_class` hooks are unsupported and provide Ninja-native customization hooks: `form_class`, `output_schema`, and `schema_field_overrides`.
- Document authentication choices: default staff-session auth, custom Ninja auth, multiple auth callables, and explicit unauthenticated APIs with `auth=None`.

Acceptance:

- `/admin-api/docs` is useful for client generation.
- OpenAPI changes are intentional and reviewed through tests.

### Phase 7: Release Hardening

Goal: reach the original "no public release until full parity" bar.

- Run the full local test suite across Django 5.0, 5.1, 5.2, and supported Django 6.0.x when practical.
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
- DRF `serializer_class` customizations are intentionally unsupported; use `form_class`, `output_schema`, and/or `schema_field_overrides`.
- The implementation may reuse/port Django-derived logic with BSD notices and upstream MIT-attributed logic where appropriate.
