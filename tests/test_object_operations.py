from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import RequestFactory

from django_veo_admin_api import ModelAdmin, NinjaAdminSite
from django_veo_admin_api.core.exceptions import AdminPermissionError, AdminValidationError
from django_veo_admin_api.core.operations import AdminRequestContext, OperationResult
from tests.testapp.models import Product


def _request_for(user):
    request = RequestFactory().get("/admin-api/testapp/product/1")
    request.user = user
    return request


def test_detail_operation_resolves_permissions_and_serializes(db, sample):
    user = get_user_model().objects.create_superuser("object-operations-admin", password="pw")
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ModelAdmin)
    result = admin_site.object_operations.detail(
        AdminRequestContext(_request_for(user)),
        admin_site.get_model_admin(Product),
        str(sample.pk),
    )

    assert isinstance(result, OperationResult)
    assert result.data["id"] == sample.pk
    assert result.data["name"] == "Alpha"


def test_detail_operation_checks_permission_before_serialization(db, sample):
    user = get_user_model().objects.create_user("object-operations-staff", password="pw", is_staff=True)
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ModelAdmin)
    model_admin = admin_site.get_model_admin(Product)
    serialize_object = Mock(side_effect=AssertionError("serialization must not run"))
    model_admin.serialize_object = serialize_object

    with pytest.raises(AdminPermissionError):
        admin_site.object_operations.detail(
            AdminRequestContext(_request_for(user)),
            model_admin,
            str(sample.pk),
        )

    serialize_object.assert_not_called()


def test_object_operation_rejects_disallowed_alternate_fields_and_missing_objects(db, sample):
    user = get_user_model().objects.create_superuser("object-operations-lookup", password="pw")
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ModelAdmin)
    model_admin = admin_site.get_model_admin(Product)
    context = AdminRequestContext(_request_for(user))

    with pytest.raises(AdminValidationError):
        admin_site.object_operations.get_object(context, model_admin, str(sample.pk), "name")
    with pytest.raises(Http404):
        admin_site.object_operations.get_object(context, model_admin, "999999")
