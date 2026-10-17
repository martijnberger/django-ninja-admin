# Core API

Install the transport-neutral engine when another integration will own the
protocol boundary:

```bash
python -m pip install django-veo-admin-api
```

The base distribution depends on Django and Pydantic. It does not import
Django Ninja or the MCP SDK and does not create HTTP routes.

## Site and registration

`CoreAdminSite` owns the registry, site-wide permissions, global actions, and
the operation-service instances:

```python
from django_veo_admin_api import ModelAdmin
from django_veo_admin_api.core import CoreAdminSite

from shop.models import Product


class ProductAdmin(ModelAdmin):
    list_display = ("name", "price")
    search_fields = ("name",)


admin_site = CoreAdminSite(include_auth=False)
admin_site.register(Product, ProductAdmin)
```

The site is transport neutral. `include_auth` controls registration of
Django's auth models; it does not install an authentication protocol.

## Operation boundary

Adapters call the services exposed by the site, including
`discovery_operations`, `changelist_operations`, `object_operations`,
`form_operations`, `mutation_operations`, `bulk_mutation_operations`,
`action_operations`, `deletion_operations`, `history_operations`, and
`autocomplete_operations`.

Every call receives an `AdminRequestContext` containing a Django
`HttpRequest`. That request is intentionally part of the core contract because
admin hooks, permissions, querysets, forms, locale, and serialization can all
be request-aware. The adapter is responsible for supplying authenticated and
trusted request state.

Successful services return `OperationResult(data, status_code)`. Expected
validation, permission, lookup, and conflict failures use the core exception
vocabulary or an `OperationResult` containing the shared `ErrorResponse`.
Adapters translate those values to their protocol; they must not repeat the
query, permission, form, transaction, or audit logic.

## Contracts and validation

Shared contracts inherit directly from Pydantic `BaseModel`, use closed object
schemas by default, and are generated from explicit model fields and
request-aware Django forms. Pydantic parses and documents payloads. Django
`ModelForm` and formsets remain authoritative for persistence validation.

The public core seam is the site, admin classes, Pydantic contracts, field
resolver registration, and operation services. Internal compiler and helper
module paths may change during alpha; integrations should prefer those public
objects over importing private helpers.
