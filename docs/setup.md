# Setup

Install the package into a Django 5.2, 6.0, or 6.1 project and add the app so the admin log
model migration is available:

```bash
python -m pip install 'django-veo-admin-api[ninja]'
```

```python
INSTALLED_APPS = [
    # ...
    "django_veo_admin_api",
]
```

Run migrations after installation:

```bash
python manage.py migrate
```

For an existing `django-ninja-admin` database, follow the
[package upgrade procedure](migration-ninja-extra.md#upgrading-from-django-ninja-admin)
before running this command. It preserves existing audit history and permissions.

Register models with the default site and mount the generated Ninja API:

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

With the route above, the interactive docs are available at
`/admin-api/docs`, and the OpenAPI document is available at
`/admin-api/openapi.json`. Both use the configured site auth. The default auth
is `SessionAuthIsStaff`, so anonymous users cannot read the schema.

## Development Checks

The repository uses `just` for local workflows:

```bash
just check
just docs-check
just sample-project-smoke
just generated-client-smoke
```

`just check` runs linting, formatting, type checks, tests with coverage, wheel
checks, installed-project smokes, OpenAPI snapshot checks, generated-client
smoke, private Django API audit, and documentation navigation/link checks.

See [Migrating To The Ninja Extra](migration-ninja-extra.md) for the base-wheel
contract and compatibility import window.
