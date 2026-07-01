from django.http import HttpResponse
from django.urls import path

from django_ninja_admin import site

urlpatterns = [
    path("admin-api/", site.urls),
    path("products/<int:pk>/", lambda request, pk: HttpResponse(str(pk)), name="product-detail"),
]
