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

