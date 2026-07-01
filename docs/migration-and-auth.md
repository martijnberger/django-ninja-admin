# Migration And Authentication

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
For example, the snippet above exposes `/admin-api/docs`.

## Replacing DRF Serializer Hooks

Old DRF-style `serializer_class` customizations should move to one or more of
these hooks.

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
- `get_output_schema(request=None)`
- `get_form_description(request, obj=None, **kwargs)`
- `get_queryset(request)`
- `save_form(request, form, change)`
- `save_model(request, obj, form, change)`
- `save_related(request, form, inline_results, change)`
- `delete_model(request, obj)`
- `delete_queryset(request, queryset)`

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

## Authentication

The default auth is `ninja.security.SessionAuthIsStaff`. It accepts active staff
users authenticated through Django sessions.

```python
from django_ninja_admin import NinjaAdminSite

admin_site = NinjaAdminSite()
```

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
