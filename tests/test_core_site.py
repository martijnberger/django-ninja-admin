from django_veo_admin_api import ModelAdmin
from django_veo_admin_api.core import CoreAdminSite
from django_veo_admin_api.integrations.ninja import NinjaAdminSite
from tests.testapp.models import Product


def test_core_site_owns_the_transport_neutral_registry_and_operations():
    admin_site = CoreAdminSite(include_auth=False)

    admin_site.register(Product, ModelAdmin)

    assert admin_site.is_registered(Product)
    assert admin_site.get_model_admin(Product).model is Product
    assert dict(admin_site.get_registered_model_admins())[Product].admin_site is admin_site
    assert admin_site.discovery_operations.admin_site is admin_site
    assert admin_site.mutation_operations.status_resolver is None


def test_ninja_site_extends_the_core_site():
    assert issubclass(NinjaAdminSite, CoreAdminSite)
