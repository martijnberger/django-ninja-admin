import pytest

from django_ninja_admin import ModelAdmin, NinjaAdminSite


@pytest.fixture
def make_site():
    def factory(model, admin_class=ModelAdmin, **admin_attrs):
        admin_site = NinjaAdminSite(include_auth=False)
        admin_site.register(model, admin_class, **admin_attrs)
        return admin_site

    return factory
