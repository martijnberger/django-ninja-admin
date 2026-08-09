from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from django_veo_admin_api import ModelAdmin, NinjaAdminSite
from django_veo_admin_api.core.exceptions import AdminPermissionError
from django_veo_admin_api.core.operations import AdminRequestContext, OperationResult
from django_veo_admin_api.schemas import AutocompleteResponse
from tests.testapp.models import Category, Product


def _request_for(user):
    request = RequestFactory().get("/admin-api/autocomplete")
    request.user = user
    return request


def _autocomplete_site():
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ModelAdmin, autocomplete_fields=("category",))
    admin_site.register(Category, ModelAdmin, search_fields=("name",))
    return admin_site


def test_autocomplete_operation_returns_typed_search_results(db, sample):
    user = get_user_model().objects.create_superuser("autocomplete-operations-admin", password="pw")
    admin_site = _autocomplete_site()

    result = admin_site.autocomplete_operations.search(
        AdminRequestContext(_request_for(user)),
        app_label="testapp",
        model_name="product",
        field_name="category",
        term="Cam",
    )

    assert isinstance(result, OperationResult)
    assert isinstance(result.data, AutocompleteResponse)
    assert [item.model_dump() for item in result.data.results] == [{"id": str(sample.category_id), "text": "Cameras"}]
    assert result.data.pagination.count == 1


def test_autocomplete_operation_checks_source_permission_before_remote_search(db, sample):
    user = get_user_model().objects.create_user("autocomplete-operations-staff", password="pw", is_staff=True)
    admin_site = _autocomplete_site()
    remote_admin = admin_site.get_model_admin(Category)
    remote_admin.get_search_fields = Mock(side_effect=AssertionError("remote search configuration must not be read"))

    with pytest.raises(AdminPermissionError):
        admin_site.autocomplete_operations.search(
            AdminRequestContext(_request_for(user)),
            app_label="testapp",
            model_name="product",
            field_name="category",
        )

    remote_admin.get_search_fields.assert_not_called()
