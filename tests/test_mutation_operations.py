from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from django_veo_admin_api import NinjaAdminSite
from django_veo_admin_api.core.exceptions import AdminPermissionError
from django_veo_admin_api.core.operations import AdminRequestContext, OperationResult
from django_veo_admin_api.models import ADDITION, LogEntry
from tests.testapp.admin import ProductAdmin
from tests.testapp.models import Product, ProductImage


def _request_for(user, method="post"):
    request = getattr(RequestFactory(), method)("/admin-api/testapp/product")
    request.user = user
    return request


def _mutation_site():
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ProductAdmin)
    return admin_site


def test_mutation_operations_create_and_update_with_forms_inlines_and_audit_log(db, sample):
    user = get_user_model().objects.create_superuser("mutation-operations-admin", password="pw")
    admin_site = _mutation_site()
    model_admin = admin_site.get_model_admin(Product)
    create_payload = model_admin.get_mutation_payload_schema(None, change=False, partial=False).model_validate(
        {
            "data": {
                "name": "Gamma",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "description": "Created",
            },
            "inlines": {"testapp.productimage": {"add": [{"title": "Side"}]}},
        }
    )

    created = admin_site.mutation_operations.create(
        AdminRequestContext(_request_for(user)),
        model_admin,
        create_payload,
    )
    created_id = created.data["data"]["id"]

    assert isinstance(created, OperationResult)
    assert created.status_code == 201
    assert ProductImage.objects.filter(product_id=created_id, title="Side").exists()
    assert LogEntry.objects.filter(object_id=str(created_id), action_flag=ADDITION).exists()

    update_payload = model_admin.get_mutation_payload_schema(None, change=True, partial=True).model_validate(
        {"data": {"price": "11.00"}}
    )
    updated = admin_site.mutation_operations.update(
        AdminRequestContext(_request_for(user, "patch")),
        model_admin,
        str(created_id),
        update_payload,
        partial=True,
    )

    assert updated.status_code == 200
    assert Product.objects.get(pk=created_id).price == 11


def test_create_operation_checks_permission_before_constructing_form(db, sample):
    user = get_user_model().objects.create_user("mutation-operations-staff", password="pw", is_staff=True)
    admin_site = _mutation_site()
    model_admin = admin_site.get_model_admin(Product)
    model_admin.get_form_class = Mock(side_effect=AssertionError("form must not be constructed"))

    with pytest.raises(AdminPermissionError):
        admin_site.mutation_operations.create(
            AdminRequestContext(_request_for(user)),
            model_admin,
            object(),
        )

    model_admin.get_form_class.assert_not_called()
