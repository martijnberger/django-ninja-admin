import pytest
from django import forms
from django.db import models
from django.test import override_settings
from django.test.utils import isolate_apps
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

import django_ninja_admin.admins.base as base_module
import django_ninja_admin.admins.inline as inline_module
import django_ninja_admin.admins.model as model_module
import django_ninja_admin.changelist as changelist_module
import django_ninja_admin.sites as sites_module
from django_ninja_admin import ModelAdmin, NinjaAdminSite
from django_ninja_admin.schemas import ErrorResponse
from tests.testapp.models import Category


def _translate(message):
    return f"translated:{message}"


def _first_error(response, status):
    assert response.status_code == status
    body = response.json()
    ErrorResponse.model_validate(body)
    return body["errors"][0]


def test_core_site_error_messages_use_gettext(monkeypatch, admin_client, staff_client):
    monkeypatch.setattr(sites_module, "_", _translate)

    denied = staff_client().get("/admin-api/testapp/product")
    missing_app = admin_client.get("/admin-api/history", {"model": "product"})

    assert _first_error(denied, 403) == {
        "message": "translated:Permission denied.",
        "param": "non_field_errors",
    }
    assert _first_error(missing_app, 400) == {
        "message": "translated:app_label is required when model is provided.",
        "param": "app_label",
    }


def test_default_site_labels_use_gettext(monkeypatch, admin_client):
    monkeypatch.setattr(sites_module, "_", _translate)

    response = admin_client.get("/admin-api/context")
    fresh_site = NinjaAdminSite(name="translated_labels", auth=None, include_auth=False)

    assert response.status_code == 200
    assert response.json()["site_title"] == "translated:Django Ninja site admin"
    assert response.json()["site_header"] == "translated:Django Ninja administration"
    assert fresh_site.api.title == "translated:Django Ninja administration"


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_custom_site_labels_are_not_translated_by_package_gettext(monkeypatch, admin_client):
    monkeypatch.setattr(sites_module, "_", _translate)

    response = admin_client.get("/context-admin/context")

    assert response.status_code == 200
    assert response.json()["site_title"] == "Custom Context Title"
    assert response.json()["site_header"] == "Custom Context Header"


def test_changelist_error_messages_use_gettext(monkeypatch, admin_client):
    monkeypatch.setattr(changelist_module, "_", _translate)

    response = admin_client.get("/admin-api/testapp/product", {"created_at__day": "32"})

    assert _first_error(response, 400) == {
        "message": "translated:Invalid day.",
        "param": "created_at__day",
    }


def test_mutation_helper_error_messages_use_gettext(monkeypatch, admin_client, sample):
    monkeypatch.setattr(sites_module, "_", _translate)

    inline_response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {"testapp.productimage": {"change": [{"pk": 999999, "title": "Ghost"}]}},
        },
        content_type="application/json",
    )
    bulk_response = admin_client.put(
        "/admin-api/testapp/product/bulk",
        data={"data": [{"pk": 999999, "stock_status": "in_stock"}]},
        content_type="application/json",
    )

    assert _first_error(inline_response, 400) == {
        "message": "translated:Unknown inline object.",
        "param": "inlines.testapp.productimage.change.0.pk",
    }
    assert _first_error(bulk_response, 400) == {
        "message": "translated:Object not found.",
        "param": "data.0.pk",
    }


def test_inline_count_error_messages_use_gettext(monkeypatch, admin_client, sample):
    from tests.testapp.admin import ProductImageInline

    monkeypatch.setattr(inline_module, "_", _translate)

    def negative_extra(self, request, obj=None, **kwargs):
        return -1

    monkeypatch.setattr(ProductImageInline, "get_extra", negative_extra)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert _first_error(response, 400) == {
        "message": "translated:Inline 'extra' must not be negative.",
        "param": "inlines.testapp.productimage.extra",
    }


def test_default_custom_action_message_uses_gettext(monkeypatch, admin_client, sample):
    monkeypatch.setattr(model_module, "_", _translate)

    response = admin_client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "mark_out_of_stock", "selected_ids": [sample.pk]},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json() == {"detail": "translated:Action completed.", "deleted": None}


@isolate_apps("tests.testapp")
def test_radio_choice_blank_label_uses_gettext(monkeypatch):
    class StatusModel(models.Model):
        status = models.CharField(blank=True, choices=[("active", "Active")], max_length=20)

        class Meta:
            app_label = "testapp"

    class StatusAdmin(ModelAdmin):
        radio_fields = {"status": 1}

    monkeypatch.setattr(base_module, "_", _translate)
    admin = StatusAdmin(StatusModel, NinjaAdminSite(include_auth=False))
    form = admin.get_form_class(None)()

    assert next(iter(form.fields["status"].choices)) == ("", "translated:None")


def test_pydantic_choice_validation_message_uses_gettext(monkeypatch):
    monkeypatch.setattr(base_module, "_", _translate)
    admin = ModelAdmin(Category, NinjaAdminSite(include_auth=False))
    field_type = admin.get_pydantic_type_for_form_field(forms.TypedChoiceField(choices=[("1", "One")], coerce=int))

    with pytest.raises(PydanticValidationError) as exc_info:
        TypeAdapter(field_type).validate_python(2)

    assert "translated:Input should be one of: 1" in str(exc_info.value)
