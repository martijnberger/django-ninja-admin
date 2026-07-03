# API And Authentication

This package is a v2 API, not a wire-compatible replacement for
`django-api-admin` clients. It keeps Django admin concepts, but uses Django
Ninja, Pydantic v2, Django `ModelForm`s, and HTTP status codes instead of DRF
serializers, viewsets, and response envelopes.

## Registering Admin APIs

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

The mounted API exposes `/docs` and `/openapi.json` under the mounted prefix.
For example, the snippet above exposes `/admin-api/docs`. These schema and docs
routes use the site auth unless the site is explicitly created with
`auth=None`.

## Ninja-Native Customization Hooks

DRF-style `serializer_class` customizations are intentionally not part of this
API. Use one or more of these Ninja/Django-native hooks instead.

### Input Validation: `form_class`

Use a Django `ModelForm` when you need custom create/update validation or custom
write fields. The generated Pydantic request schemas are derived from the form
fields, then the form remains the authoritative persistence validator.

```python
from django import forms
from django_ninja_admin import ModelAdmin

from shop.models import Product


class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ("name", "category", "price", "status")

    def clean_name(self):
        name = self.cleaned_data["name"]
        if name == "Forbidden":
            raise forms.ValidationError("Choose a different name.")
        return name


class ProductAdmin(ModelAdmin):
    form_class = ProductAdminForm
```

### Input Field Types: `form_schema_field_overrides`

Use `form_schema_field_overrides` when a form field needs a more precise
Pydantic request/OpenAPI type than the package can infer automatically. Django
`ModelForm` validation still remains authoritative for persistence. Form
descriptions expose the override under `attrs.input_schema_override.schema` so
frontends can render the same input contract that OpenAPI advertises.

```python
from django import forms
from django_ninja_admin import ModelAdmin

from shop.models import Product


class ProductAdminForm(forms.ModelForm):
    metadata = forms.CharField(required=False)

    class Meta:
        model = Product
        fields = ("name", "category", "price", "metadata")


class ProductAdmin(ModelAdmin):
    form_class = ProductAdminForm
    form_schema_field_overrides = {"metadata": dict[str, int]}
```

### Custom Model Fields: `register_field`

Use Ninja's `register_field()` when a custom Django model field has a stable
Python/OpenAPI type that should apply anywhere that field is exposed through
model-derived schemas, relation IDs, or form-derived relation inputs.

```python
from ninja.orm import register_field


register_field("MoneyField", str)
```

Use `schema_field_overrides` or `form_schema_field_overrides` instead when the
admin endpoint needs a different read or write contract from the model field's
general project-wide type.

### Output Shape: `output_schema`

Use a Pydantic/Ninja schema when you want to own the whole response shape.

```python
from ninja import Schema
from django_ninja_admin import ModelAdmin


class ProductOut(Schema):
    id: int
    name: str
    price: str


class ProductAdmin(ModelAdmin):
    output_schema = ProductOut
```

### Extra Output Fields: `schema_field_overrides`

Use `schema_field_overrides` for computed fields or fields that need an explicit
Pydantic type.

```python
from django_ninja_admin import ModelAdmin, display


class ProductAdmin(ModelAdmin):
    list_display = ("name", "display_price")
    schema_field_overrides = {"display_price": (str, None)}

    @display(description="Display price", ordering="price")
    def display_price(self, obj):
        return f"${obj.price}"
```

### Runtime Hooks

Use Django-admin-style hooks for behavior:

- `get_form_class(request, obj=None, change=False)`
- `get_form_schema_field_overrides(request, obj=None, change=False)`
- `get_output_schema(request=None)`
- `get_form_description(request, obj=None, **kwargs)`
- `get_queryset(request)`
- `list_prefetch_related` / `get_list_prefetch_related(request)` for
  changelist columns that intentionally touch many-valued relations. Entries
  may be lookup strings or Django `Prefetch` objects.
- `save_form(request, form, change)`
- `save_model(request, obj, form, change)`
- `save_related(request, form, inline_results, change)`
- `delete_model(request, obj)`
- `delete_queryset(request, queryset)`

### Action Input Schemas

Actions can declare extra JSON input with Pydantic/Ninja schemas:

```python
from typing import Literal

from ninja import Schema

from django_ninja_admin import ModelAdmin, action


class StockStatusActionData(Schema):
    status: Literal["in_stock", "out_of_stock"]
    note: str | None = None


class StockStatusActionResult(Schema):
    status: str
    note: str | None = None


class ProductAdmin(ModelAdmin):
    actions = ["set_stock_status"]

    @action(
        input_schema=StockStatusActionData,
        response_schema=StockStatusActionResult,
        permissions=["change"],
    )
    def set_stock_status(self, request, queryset, data):
        queryset.update(stock_status=data.status)
        return {"status": data.status, "note": data.note}
```

The action route keeps the normal action envelope and adds `data` for the
custom payload:

```json
{
  "action": "set_stock_status",
  "selected_ids": [1, 2],
  "data": {
    "status": "out_of_stock",
    "note": "seasonal"
  }
}
```

Input schemas are included in OpenAPI as per-action payload variants selected
by an `action` discriminator. Response schemas are included under the model
action response component alongside the built-in default action response:

```json
{
  "detail": "Action completed."
}
```

Actions that return custom objects should declare `response_schema`. This also
applies when an action returns `ninja.Status(...)` with a custom success status,
because the route response map is generated when the admin site builds its
routers.

## Request And Error Shapes

Mutation requests use a data envelope:

```json
{
  "data": {
    "name": "Tripod",
    "price": "9.00"
  },
  "inlines": {
    "shop.productimage": {
      "add": [{"title": "Front"}],
      "change": [{"pk": 1, "title": "Profile"}],
      "delete": [2]
    }
  }
}
```

Validation failures return HTTP status codes with typed error bodies instead of
a required top-level status field:

```json
{
  "errors": [
    {"message": "Field required", "param": "data.name"}
  ]
}
```

`response_add()` and `response_change()` should return the standard typed
mutation response shape unless they return a `ninja.Status` with a custom
status/body. The standard shape is serialized through the model admin output
schema and is typed as:

```json
{
  "data": {
    "id": 1,
    "name": "Tripod"
  },
  "inlines": null
}
```

For custom `Status(...)` bodies, declare response schemas so OpenAPI can stay
typed:

```python
from ninja import Schema, Status


class DeleteHookResponse(Schema):
    deleted_id: str
    deleted_display: str
    response_hook: str


class ProductAdmin(ModelAdmin):
    response_delete_schema = DeleteHookResponse

    def response_delete(self, request, obj_display, obj_id):
        return Status(
            200,
            {
                "deleted_id": obj_id,
                "deleted_display": obj_display,
                "response_hook": "delete",
            },
        )
```

The same pattern is available as `response_add_schema` and
`response_change_schema`. A schema value is advertised for the conventional
custom hook statuses (`200`/`202` for add and delete, `201`/`202` for change).
Use a status-to-schema mapping when a hook needs different schemas per status.

## Permissions Metadata

`GET /permissions` returns the current user's site-level permission state plus
registered model permission summaries. The model entries use the same
`has_add_permission()`, `has_change_permission()`, `has_delete_permission()`,
and `has_view_permission()` hooks as Django admin, so custom model-admin
permission overrides are reflected in the response.

Object-specific UI state is exposed on object-bearing responses such as
changelist rows and change forms, where those same hooks can receive the
current object.

## Authentication

The default auth is `ninja.security.SessionAuthIsStaff`. It accepts active staff
users authenticated through Django sessions.

```python
from django_ninja_admin import NinjaAdminSite

admin_site = NinjaAdminSite()
```

For browser clients using the default session auth, the built-in bootstrap
routes are:

- `GET /csrf`: returns `{csrf_token}` and asks Django to issue a CSRF cookie.
- `POST /login`: accepts `{username, password}`, logs in an active staff user,
  and returns the current permission state plus a fresh `csrf_token`.
- `POST /logout`: logs out the current authenticated session.

Use the returned CSRF token as `X-CSRFToken` on session-authenticated mutation
requests. Projects should keep Django's session middleware, authentication
middleware, and CSRF middleware enabled for browser deployments.

Pass any Django Ninja auth callable or sequence of auth callables to customize
authentication:

```python
from ninja.security import APIKeyHeader
from django_ninja_admin import NinjaAdminSite


class InternalTokenAuth(APIKeyHeader):
    param_name = "X-Admin-Token"

    def authenticate(self, request, key):
        if key == "expected-token":
            return "internal-admin"
        return None


admin_site = NinjaAdminSite(auth=InternalTokenAuth())
```

Use a sequence when more than one Ninja auth method may authenticate the same
admin API:

```python
from ninja.security import APIKeyHeader
from django_ninja_admin import NinjaAdminSite


class PrimaryTokenAuth(APIKeyHeader):
    param_name = "X-Primary-Token"

    def authenticate(self, request, key):
        if key == "primary-token":
            return "primary-admin"
        return None


class SecondaryTokenAuth(APIKeyHeader):
    param_name = "X-Secondary-Token"

    def authenticate(self, request, key):
        if key == "secondary-token":
            return "secondary-admin"
        return None


admin_site = NinjaAdminSite(auth=[PrimaryTokenAuth(), SecondaryTokenAuth()])
```

Use `auth=None` only for deliberately unauthenticated APIs, such as local tests
or a separately protected internal mount:

```python
from django_ninja_admin import NinjaAdminSite

admin_site = NinjaAdminSite(auth=None)
```

Custom site and model routes can use the site auth, provide a route-level auth
override, or explicitly disable auth. Wrap views with `admin_view()` when they
should also enforce admin permissions:

```python
from django_ninja_admin import ModelAdmin


class ProductAdmin(ModelAdmin):
    def stats(self, request):
        return {"count": self.model.objects.count()}

    def get_urls(self):
        return [
            self.route(
                "/stats",
                self.admin_view(self.stats),
                response=dict[str, int],
                operation_id="product_stats",
            )
        ]
```
