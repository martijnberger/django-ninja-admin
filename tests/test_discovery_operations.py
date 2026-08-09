import pytest
from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import RequestFactory

from django_veo_admin_api import NinjaAdminSite
from django_veo_admin_api.core.operations import AdminRequestContext, OperationResult
from django_veo_admin_api.schemas import AppSummary, PermissionsResponse, SiteContext
from tests.testapp.models import Product


def _request_for(user, *, script_name=""):
    request = RequestFactory().get("/", SCRIPT_NAME=script_name)
    request.user = user
    return request


def test_discovery_operations_return_validated_permission_filtered_contracts(db):
    user = get_user_model().objects.create_superuser("operations-admin", password="pw")
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product)
    context = AdminRequestContext(_request_for(user, script_name="/control"))

    apps_result = admin_site.discovery_operations.list_apps(context)
    site_result = admin_site.discovery_operations.site_context(context)
    permissions_result = admin_site.discovery_operations.permissions(context)

    assert isinstance(apps_result, OperationResult)
    assert apps_result.status_code == 200
    assert isinstance(apps_result.data[0], AppSummary)
    assert apps_result.data[0].models[0].model_name == "product"
    assert isinstance(site_result.data, SiteContext)
    assert site_result.data.site_url == "/control"
    assert isinstance(permissions_result.data, PermissionsResponse)
    assert permissions_result.data.has_permission is True
    assert permissions_result.data.models[0].perms.has_view_permission is True


def test_discovery_operations_hide_models_without_permissions(db):
    user = get_user_model().objects.create_user("operations-staff", password="pw", is_staff=True)
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product)
    context = AdminRequestContext(_request_for(user))

    assert admin_site.discovery_operations.list_apps(context).data == []
    assert admin_site.discovery_operations.permissions(context).data.models == []


def test_discovery_operations_raise_not_found_for_hidden_or_unknown_apps(db):
    user = get_user_model().objects.create_user("operations-hidden", password="pw", is_staff=True)
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product)

    with pytest.raises(Http404):
        admin_site.discovery_operations.list_apps(AdminRequestContext(_request_for(user)), "testapp")
