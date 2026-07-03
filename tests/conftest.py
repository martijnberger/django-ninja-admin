import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client

from django_ninja_admin import ModelAdmin, NinjaAdminSite
from tests.testapp.models import Category, Product, ProductImage, Tag


@pytest.fixture
def make_site():
    def factory(model, admin_class=ModelAdmin, **admin_attrs):
        admin_site = NinjaAdminSite(include_auth=False)
        admin_site.register(model, admin_class, **admin_attrs)
        return admin_site

    return factory


@pytest.fixture
def admin_client(db):
    user = get_user_model().objects.create_user("admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def staff_client(db):
    user_count = 0

    def make_client(*permission_codenames):
        nonlocal user_count
        user_count += 1
        user = get_user_model().objects.create_user(f"staff-{user_count}", password="pw", is_staff=True)
        user.user_permissions.set(Permission.objects.filter(codename__in=permission_codenames))
        client = Client()
        client.force_login(user)
        return client

    return make_client


@pytest.fixture
def sample(db):
    category = Category.objects.create(name="Cameras")
    featured = Tag.objects.create(name="Featured")
    compact = Tag.objects.create(name="Compact")
    product = Product.objects.create(
        name="Alpha",
        category=category,
        price="12.50",
        description="Nice camera",
        manual="manuals/alpha.pdf",
    )
    product.tags.set([featured, compact])
    Product.objects.create(name="Beta", category=category, price="3.00", stock_status="out_of_stock")
    ProductImage.objects.create(product=product, title="Front")
    return product
