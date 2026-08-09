# Migrating To The Ninja Extra

Django Ninja is no longer an unconditional dependency. Existing HTTP/OpenAPI
users should change their installation command from:

```bash
python -m pip install django-veo-admin-api
```

to:

```bash
python -m pip install 'django-veo-admin-api[ninja]'
```

The base installation contains Django-admin semantics, Pydantic contracts,
schema compilers, serialization, error contracts, and operation services. It
does not construct REST routes or generate OpenAPI by itself.

## Imports

Use the integration namespace for Ninja transport objects:

```python
from django_veo_admin_api import ModelAdmin
from django_veo_admin_api.integrations.ninja import NinjaAdminSite, site
```

The pre-beta compatibility window keeps these imports lazy:

```python
from django_veo_admin_api import NinjaAdminSite, site
```

They still require the `[ninja]` extra. Accessing either object without it
raises an `ImportError` that includes the exact installation command. Importing
the package, core admin classes, schemas, or operation services does not import
Django Ninja.

There is intentionally no plain-Django HTTP fallback. Routing, parsing,
response handling, authentication, docs, and OpenAPI remain the responsibility
of the Ninja adapter.
