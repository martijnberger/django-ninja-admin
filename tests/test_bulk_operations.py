from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from django_veo_admin_api import NinjaAdminSite
from django_veo_admin_api.core.exceptions import AdminPermissionError
from django_veo_admin_api.core.operations import AdminRequestContext, OperationResult
from tests.testapp.admin import ProductAdmin
from tests.testapp.models import Product


def _request_for(user):
    request = RequestFactory().put("/admin-api/testapp/product/bulk")
    request.user = user
    return request


def _bulk_site():
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ProductAdmin)
    return admin_site


def test_bulk_operation_uses_changelist_formset_and_returns_typed_result(db, sample):
    user = get_user_model().objects.create_superuser("bulk-operations-admin", password="pw")
    admin_site = _bulk_site()
    model_admin = admin_site.get_model_admin(Product)
    payload = model_admin.get_bulk_payload_schema(None).model_validate(
        {"data": [{"pk": sample.pk, "stock_status": "out_of_stock"}]}
    )

    result = admin_site.bulk_mutation_operations.update(
        AdminRequestContext(_request_for(user)),
        model_admin,
        payload,
    )

    assert isinstance(result, OperationResult)
    assert result.data.data["0"].stock_status == "out_of_stock"
    sample.refresh_from_db()
    assert sample.stock_status == "out_of_stock"


def test_bulk_operation_checks_global_permission_before_changelist(db, sample):
    user = get_user_model().objects.create_user("bulk-operations-staff", password="pw", is_staff=True)
    admin_site = _bulk_site()
    model_admin = admin_site.get_model_admin(Product)
    model_admin.get_changelist_instance = Mock(side_effect=AssertionError("changelist must not be constructed"))

    with pytest.raises(AdminPermissionError):
        admin_site.bulk_mutation_operations.update(
            AdminRequestContext(_request_for(user)),
            model_admin,
            object(),
        )

    model_admin.get_changelist_instance.assert_not_called()
