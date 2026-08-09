# Django Veo Admin API

`django-veo-admin-api` is a typed Django admin engine with optional transport
integrations. Its Django Ninja integration exposes registered models,
changelists, forms, actions, inlines, history, autocomplete, and view-on-site
metadata for custom admin frontends.

Install the Ninja HTTP/OpenAPI integration explicitly:

```bash
python -m pip install 'django-veo-admin-api[ninja]'
```

```python
from django.urls import path
from django_veo_admin_api import ModelAdmin
from django_veo_admin_api.integrations.ninja import site

from shop.models import Product


class ProductAdmin(ModelAdmin):
    list_display = ("name", "price")
    search_fields = ("name",)


site.register(Product, ProductAdmin)

urlpatterns = [
    path("admin-api/", site.urls),
]
```

The core depends directly on Django and Pydantic. The optional HTTP/OpenAPI
adapter intentionally uses Django Ninja instead of Django REST Framework or
drf-spectacular.

Supported versions are Python 3.12+ and Django 5.0+.

## Development Checks

This repository uses `just` for local workflow commands:

```bash
just lint
just test
just postgres-test
just package-smoke
just sample-project-smoke
just check
just ci
```

`just package-smoke` builds the wheel, installs its base profile into a clean
environment, imports the core API without Ninja, and verifies the optional
dependency metadata and missing-extra error. `just sample-project-smoke`
installs the built wheel with `[ninja]` into a temporary Django project, mounts
`site.urls`, opens docs/OpenAPI, and exercises the registered model app list.
`just postgres-test` expects PostgreSQL
connection env vars and is used by CI. `just test` and `just postgres-test`
accept pytest selectors. `just ci` is an alias for the full local gate.

See [API And Authentication](docs/api-and-auth.md) for Ninja-native
customization hooks (`form_class`, `output_schema`, and
`schema_field_overrides`) plus examples for default, custom, and disabled auth.
The MkDocs documentation site is configured by `mkdocs.yml`; run
`just docs-check` to validate the docs navigation and local links, and
`just docs-build` to run a strict local site build.
See [API Versioning And Deprecation](docs/versioning.md) for the OpenAPI
contract review and release compatibility policy.
