from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from django_veo_admin_api import NinjaAdminSite
from django_veo_admin_api.core.exceptions import AdminPermissionError
from django_veo_admin_api.core.operations import AdminRequestContext, OperationResult
from django_veo_admin_api.schemas import FormResponse
from tests.testapp.admin import ProductAdmin
from tests.testapp.models import Product


def _request_for(user, path="/admin-api/testapp/product/form"):
    request = RequestFactory().get(path)
    request.user = user
    return request


def test_form_operation_builds_validated_parent_and_inline_contracts(db, sample):
    user = get_user_model().objects.create_superuser("form-operations-admin", password="pw")
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ProductAdmin)
    model_admin = admin_site.get_model_admin(Product)

    result = admin_site.form_operations.describe(
        AdminRequestContext(_request_for(user, f"/admin-api/testapp/product/{sample.pk}/form")),
        model_admin,
        sample,
    )

    assert isinstance(result, OperationResult)
    assert isinstance(result.data, FormResponse)
    assert result.data.form.model == "testapp.product"
    assert result.data.form.permissions.has_view_permission is True
    assert result.data.inlines[0].model == "testapp.productimage"
    assert result.data.inlines[0].initial_form_count == 1


def test_form_operation_checks_permission_before_constructing_forms(db):
    user = get_user_model().objects.create_user("form-operations-staff", password="pw", is_staff=True)
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ProductAdmin)
    model_admin = admin_site.get_model_admin(Product)
    get_form_description = Mock(side_effect=AssertionError("form construction must not run"))
    model_admin.get_form_description = get_form_description

    with pytest.raises(AdminPermissionError):
        admin_site.form_operations.describe(AdminRequestContext(_request_for(user)), model_admin, None)

    get_form_description.assert_not_called()
