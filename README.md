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

## Development Checks

This repository uses `just` for local workflow commands:

```bash
just lint
just test
just package-smoke
just check
```

`just package-smoke` builds the wheel, installs it into a temporary target,
imports the public API, and confirms the wheel metadata does not depend on DRF
or drf-spectacular.

See [Migration And Authentication](docs/migration-and-auth.md) for guidance on
moving DRF serializer customizations to `form_class`, `output_schema`, and
`schema_field_overrides`, plus examples for default, custom, and disabled auth.
