# Django Ninja Admin

`django-ninja-admin` is a Ninja-native API surface for Django admin concepts.
It exposes registered models, changelists, forms, actions, inlines, history,
autocomplete, and view-on-site metadata for custom admin frontends.

```python
from django.urls import path
from django_ninja_admin import ModelAdmin, site

from shop.models import Product


class ProductAdmin(ModelAdmin):
    list_display = ("name", "price")
    search_fields = ("name",)


site.register(Product, ProductAdmin)

urlpatterns = [
    path("admin-api/", site.urls),
]
```

This package intentionally uses Django Ninja and Pydantic instead of Django
REST Framework or drf-spectacular.

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

`just package-smoke` builds the wheel, installs it into a temporary target,
imports the public API, and confirms the wheel metadata does not depend on DRF
or drf-spectacular. `just sample-project-smoke` installs the built wheel into a
temporary Django project, mounts `site.urls`, opens docs/OpenAPI, and exercises
the registered model app list. `just postgres-test` expects PostgreSQL
connection env vars and is used by CI. `just test` and `just postgres-test`
accept pytest selectors. `just ci` is an alias for the full local gate.

See [API And Authentication](docs/api-and-auth.md) for Ninja-native
customization hooks (`form_class`, `output_schema`, and
`schema_field_overrides`) plus examples for default, custom, and disabled auth.
See [API Versioning And Deprecation](docs/versioning.md) for the OpenAPI
contract review and release compatibility policy.
