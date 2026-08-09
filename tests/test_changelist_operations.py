from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from django_veo_admin_api import ModelAdmin, NinjaAdminSite
from django_veo_admin_api.core.exceptions import AdminPermissionError
from django_veo_admin_api.core.operations import AdminRequestContext, OperationResult
from django_veo_admin_api.schemas import ChangelistResponse
from tests.testapp.models import Product


def _request_for(user, query=None):
    request = RequestFactory().get("/admin-api/testapp/product", data=query or {})
    request.user = user
    return request


def test_changelist_operation_returns_typed_permission_filtered_data(db, sample):
    user = get_user_model().objects.create_superuser("changelist-operations-admin", password="pw")
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ModelAdmin, list_display=("name", "price"), search_fields=("name",))

    result = admin_site.changelist_operations.list(
        AdminRequestContext(_request_for(user, {"q": "Alpha"})),
        admin_site.get_model_admin(Product),
    )

    assert isinstance(result, OperationResult)
    assert isinstance(result.data, ChangelistResponse)
    assert result.data.config.result_count == 1
    assert result.data.rows[0].cells["name"] == "Alpha"


def test_changelist_operation_checks_permission_before_constructing_changelist(db, sample):
    user = get_user_model().objects.create_user("changelist-operations-staff", password="pw", is_staff=True)
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ModelAdmin)
    model_admin = admin_site.get_model_admin(Product)
    model_admin.get_changelist_instance = Mock(side_effect=AssertionError("changelist must not be constructed"))

    with pytest.raises(AdminPermissionError):
        admin_site.changelist_operations.list(AdminRequestContext(_request_for(user)), model_admin)

    model_admin.get_changelist_instance.assert_not_called()
