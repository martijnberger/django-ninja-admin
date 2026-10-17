import json
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory

from django_veo_admin_api import ModelAdmin, NinjaAdminSite
from django_veo_admin_api.core.exceptions import AdminPermissionError
from django_veo_admin_api.core.operations import AdminRequestContext, OperationResult
from django_veo_admin_api.models import CHANGE, LogEntry
from django_veo_admin_api.schemas import HistoryResponse
from tests.testapp.models import Product


def _request_for(user):
    request = RequestFactory().get("/admin-api/history")
    request.user = user
    return request


def test_history_operation_returns_typed_permission_filtered_entries(db, sample):
    user = get_user_model().objects.create_superuser("history-operations-admin", password="pw")
    content_type = ContentType.objects.get_for_model(Product, for_concrete_model=False)
    entry = LogEntry.objects.create(
        user=user,
        content_type=content_type,
        object_id=str(sample.pk),
        object_repr=str(sample),
        action_flag=CHANGE,
        change_message=json.dumps([{"changed": {"fields": ["Name"]}}]),
    )
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ModelAdmin)

    result = admin_site.history_operations.list(
        AdminRequestContext(_request_for(user)),
        app_label="testapp",
        model_name="product",
    )

    assert isinstance(result, OperationResult)
    assert isinstance(result.data, HistoryResponse)
    assert [item.id for item in result.data.results] == [entry.pk]
    assert result.data.results[0].change_message_text == "Changed Name."
    assert result.data.pagination.count == 1


def test_history_operation_checks_model_permission_before_log_query(db, sample, monkeypatch):
    user = get_user_model().objects.create_user("history-operations-staff", password="pw", is_staff=True)
    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Product, ModelAdmin)
    filter_entries = Mock(side_effect=AssertionError("history log must not be queried"))
    monkeypatch.setattr(LogEntry.objects, "filter", filter_entries)

    with pytest.raises(AdminPermissionError):
        admin_site.history_operations.list(
            AdminRequestContext(_request_for(user)),
            app_label="testapp",
            model_name="product",
        )

    filter_entries.assert_not_called()
