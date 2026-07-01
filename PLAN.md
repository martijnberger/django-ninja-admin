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
