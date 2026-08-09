from django.contrib.auth import get_user_model
from django.test import RequestFactory

from django_veo_admin_api import NinjaAdminSite
from django_veo_admin_api.core.operations import AdminRequestContext, OperationResult
from django_veo_admin_api.schemas import DeletionPreview, ErrorResponse
from tests.testapp.admin import ProductAdmin
from tests.testapp.models import Product, ProductReview


def _request_for(user):
    request = RequestFactory().delete("/admin-api/testapp/product/1")
    request.user = user
    return request


def _deletion_site():
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ProductAdmin)
    return admin_site


def test_deletion_operations_preview_and_delete_with_audit_log(db, sample):
    user = get_user_model().objects.create_superuser("deletion-operations-admin", password="pw")
    admin_site = _deletion_site()
    model_admin = admin_site.get_model_admin(Product)
    context = AdminRequestContext(_request_for(user))

    preview = admin_site.deletion_operations.preview(context, model_admin, str(sample.pk))

    assert isinstance(preview, OperationResult)
    assert isinstance(preview.data, DeletionPreview)
    assert preview.data.can_delete is True
    assert preview.data.deleted_objects[0] == "Alpha"

    result = admin_site.deletion_operations.delete(context, model_admin, str(sample.pk))

    assert result.status_code == 204
    assert not Product.objects.filter(pk=sample.pk).exists()


def test_deletion_operations_report_protected_objects_without_deleting(db, sample):
    user = get_user_model().objects.create_superuser("deletion-operations-protected", password="pw")
    ProductReview.objects.create(product=sample, note="Pinned review")
    admin_site = _deletion_site()
    model_admin = admin_site.get_model_admin(Product)
    context = AdminRequestContext(_request_for(user))

    preview = admin_site.deletion_operations.preview(context, model_admin, str(sample.pk))
    result = admin_site.deletion_operations.delete(context, model_admin, str(sample.pk))

    assert preview.data.can_delete is False
    assert preview.data.protected == ["Pinned review"]
    assert result.status_code == 409
    assert isinstance(result.data, ErrorResponse)
    assert result.data.protected == ["Pinned review"]
    assert Product.objects.filter(pk=sample.pk).exists()
