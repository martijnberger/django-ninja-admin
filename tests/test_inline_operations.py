from django.contrib.auth import get_user_model
from django.test import RequestFactory

from django_veo_admin_api import NinjaAdminSite
from django_veo_admin_api.core.operations.inlines import InlineMutationProcessor
from tests.testapp.admin import ProductAdmin
from tests.testapp.models import Product, ProductImage


def test_inline_processor_uses_authoritative_formset_and_serializes_results(db, sample):
    user = get_user_model().objects.create_superuser("inline-operations-admin", password="pw")
    request = RequestFactory().post(f"/admin-api/testapp/product/{sample.pk}")
    request.user = user
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ProductAdmin)

    results = InlineMutationProcessor().process(
        request,
        admin_site.get_model_admin(Product),
        sample,
        {"testapp.productimage": {"add": [{"title": "Side"}]}},
        change=True,
    )

    assert ProductImage.objects.filter(product=sample, title="Side").exists()
    assert results["testapp.productimage"]["add"][0]["title"] == "Side"
