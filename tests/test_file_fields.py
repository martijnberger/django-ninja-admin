import json
from io import BytesIO

from django.core.files.storage import Storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from PIL import Image

from django_ninja_admin.models import CHANGE, LogEntry
from django_ninja_admin.schemas import ErrorResponse
from tests.testapp.models import Product

RENDERED_FIELD_ATTR_KEYS = {
    "aria_describedby",
    "auto_id",
    "bound_subwidgets",
    "clear_checkbox_id",
    "clear_checkbox_name",
    "css_classes",
    "form_prefix",
    "hidden_initial_id",
    "hidden_initial_name",
    "hidden_initial_widget",
    "html_initial_id",
    "html_initial_name",
    "html_name",
    "id_for_label",
    "option_template_name",
    "rendered_attrs",
    "rendered_optgroups",
    "rendered_subwidgets",
    "show_hidden_initial",
    "template_name",
}


def assert_no_rendered_field_attrs(attrs):
    assert RENDERED_FIELD_ATTR_KEYS.isdisjoint(attrs)


def _uploaded_png(name="photo.png", *, size=(2, 3), color=(255, 0, 0)):
    stream = BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")


def test_file_field_can_be_cleared_with_null_payload(admin_client, sample):
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"manual": None}},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["manual"] is None
    sample.refresh_from_db()
    assert sample.manual.name == ""

    detail = admin_client.get(f"/admin-api/testapp/product/{sample.pk}")
    assert detail.status_code == 200
    assert detail.json()["manual"] is None

    change_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
    manual_attrs = next(field["attrs"] for field in change_form.json()["form"]["fields"] if field["name"] == "manual")
    assert "current_file" not in manual_attrs

    change_entry = LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).latest("action_time")
    assert json.loads(change_entry.change_message) == [{"changed": {"fields": ["Manual"]}}]


def test_file_and_image_fields_reject_non_string_json_payloads(admin_client, sample):
    invalid_manual = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"manual": {"name": "manual.txt"}}},
        content_type="application/json",
    )
    invalid_photo = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"photo": ["photo.png"]}},
        content_type="application/json",
    )

    assert invalid_manual.status_code == 422
    assert invalid_manual.json()["errors"][0]["param"] == "data.manual"
    assert invalid_photo.status_code == 422
    assert invalid_photo.json()["errors"][0]["param"] == "data.photo"


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_multipart_file_parts_satisfy_required_file_schema_fields(admin_client, sample, tmp_path):
    schema = admin_client.get("/required-file-admin/openapi.json").json()
    create_data_schema = schema["components"]["schemas"]["ProductAdminCreateData"]

    assert "manual" in create_data_schema["required"]
    assert create_data_schema["properties"]["manual"] == {"title": "Manual", "type": "string"}
    multipart_schema = schema["paths"]["/required-file-admin/testapp/product/multipart"]["post"]["requestBody"][
        "content"
    ]["multipart/form-data"]["schema"]
    assert multipart_schema["required"] == ["data", "manual"]

    form = admin_client.get("/required-file-admin/testapp/product/form")
    manual_attrs = next(field["attrs"] for field in form.json()["form"]["fields"] if field["name"] == "manual")
    assert manual_attrs["allowed_extensions"] == ["pdf", "txt"]
    assert manual_attrs["accepted_extensions"] == [".pdf", ".txt"]

    with override_settings(MEDIA_ROOT=tmp_path):
        invalid = admin_client.post(
            "/required-file-admin/testapp/product/multipart",
            data={
                "data": json.dumps(
                    {
                        "name": "Invalid manual extension",
                        "category": sample.category_id,
                        "price": "5.00",
                        "stock_status": "in_stock",
                    }
                ),
                "manual": SimpleUploadedFile("required.exe", b"required", content_type="application/octet-stream"),
            },
        )

        assert invalid.status_code == 400
        ErrorResponse.model_validate(invalid.json())
        assert invalid.json()["errors"][0]["param"] == "manual"
        assert not Product.objects.filter(name="Invalid manual extension").exists()

        created = admin_client.post(
            "/required-file-admin/testapp/product/multipart",
            data={
                "data": json.dumps(
                    {
                        "name": "Required manual",
                        "category": sample.category_id,
                        "price": "5.00",
                        "stock_status": "in_stock",
                    }
                ),
                "manual": SimpleUploadedFile("required.txt", b"required", content_type="text/plain"),
            },
        )

        assert created.status_code == 201, created.json()
        product = Product.objects.get(pk=created.json()["data"]["id"])
        assert product.manual.name.startswith("manuals/required")
        assert (tmp_path / product.manual.name).read_bytes() == b"required"
        assert created.json()["data"]["manual"] == {
            "name": product.manual.name,
            "url": f"/media/{product.manual.name}",
        }


def test_file_field_can_be_uploaded_with_multipart_payload(admin_client, sample, tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        created = admin_client.post(
            "/admin-api/testapp/product/multipart",
            data={
                "data": json.dumps(
                    {
                        "name": "Upload",
                        "category": sample.category_id,
                        "tags": list(sample.tags.values_list("pk", flat=True)),
                        "price": "7.00",
                        "stock_status": "in_stock",
                        "description": "Created with upload",
                    }
                ),
                "manual": SimpleUploadedFile("manual.txt", b"hello", content_type="text/plain"),
            },
        )

        assert created.status_code == 201
        created_body = created.json()["data"]
        product = Product.objects.get(pk=created_body["id"])
        assert product.manual.name.startswith("manuals/manual")
        assert (tmp_path / product.manual.name).read_bytes() == b"hello"
        assert created_body["manual"] == {
            "name": product.manual.name,
            "url": f"/media/{product.manual.name}",
        }

        changed = admin_client.patch(
            f"/admin-api/testapp/product/{product.pk}/multipart",
            data=encode_multipart(
                BOUNDARY,
                {
                    "data": json.dumps({"description": "Updated with upload"}),
                    "manual": SimpleUploadedFile("replacement.txt", b"updated", content_type="text/plain"),
                },
            ),
            content_type=MULTIPART_CONTENT,
        )

        assert changed.status_code == 200
        product.refresh_from_db()
        assert product.description == "Updated with upload"
        assert product.manual.name.startswith("manuals/replacement")
        assert (tmp_path / product.manual.name).read_bytes() == b"updated"
        change_entry = LogEntry.objects.filter(object_id=str(product.pk), action_flag=CHANGE).latest("action_time")
        changed_fields = json.loads(change_entry.change_message)[0]["changed"]["fields"]
        assert set(changed_fields) == {"Description", "Manual"}


def test_multipart_file_fields_reject_duplicate_file_parts(admin_client, sample, tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        response = admin_client.post(
            "/admin-api/testapp/product/multipart",
            data={
                "data": json.dumps(
                    {
                        "name": "Duplicate upload",
                        "category": sample.category_id,
                        "tags": list(sample.tags.values_list("pk", flat=True)),
                        "price": "7.00",
                        "stock_status": "in_stock",
                    }
                ),
                "manual": [
                    SimpleUploadedFile("first.txt", b"first", content_type="text/plain"),
                    SimpleUploadedFile("second.txt", b"second", content_type="text/plain"),
                ],
            },
        )

        assert response.status_code == 422
        body = response.json()
        ErrorResponse.model_validate(body)
        assert body["errors"][0] == {
            "message": "Input should contain at most one file",
            "param": "manual",
        }
        assert not Product.objects.filter(name="Duplicate upload").exists()
        assert not any(tmp_path.rglob("*.txt"))


def test_image_field_validates_and_uploads_with_multipart_payload(admin_client, sample, tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        invalid = admin_client.patch(
            f"/admin-api/testapp/product/{sample.pk}/multipart",
            data=encode_multipart(
                BOUNDARY,
                {
                    "data": json.dumps({"description": "Invalid image upload"}),
                    "photo": SimpleUploadedFile("not-image.txt", b"not an image", content_type="text/plain"),
                },
            ),
            content_type=MULTIPART_CONTENT,
        )

        assert invalid.status_code == 400
        invalid_body = invalid.json()
        ErrorResponse.model_validate(invalid_body)
        assert invalid_body["errors"][0]["param"] == "photo"
        assert Product.objects.get(pk=sample.pk).photo.name == ""

        uploaded = _uploaded_png("cover.png", size=(2, 3))
        changed = admin_client.patch(
            f"/admin-api/testapp/product/{sample.pk}/multipart",
            data=encode_multipart(
                BOUNDARY,
                {
                    "data": json.dumps({"description": "Image uploaded"}),
                    "photo": uploaded,
                },
            ),
            content_type=MULTIPART_CONTENT,
        )

        assert changed.status_code == 200, changed.json()
        sample.refresh_from_db()
        assert sample.description == "Image uploaded"
        assert sample.photo.name.startswith("photos/cover")
        assert sample.photo_width == 2
        assert sample.photo_height == 3
        assert (tmp_path / sample.photo.name).exists()
        assert changed.json()["data"]["photo"] == {
            "name": sample.photo.name,
            "url": f"/media/{sample.photo.name}",
            "width": 2,
            "height": 3,
        }

        detail = admin_client.get(f"/admin-api/testapp/product/{sample.pk}")
        assert detail.status_code == 200
        assert detail.json()["photo"] == {
            "name": sample.photo.name,
            "url": f"/media/{sample.photo.name}",
            "width": 2,
            "height": 3,
        }

        change_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
        photo_attrs = next(field["attrs"] for field in change_form.json()["form"]["fields"] if field["name"] == "photo")
        assert photo_attrs["current_file"] == {
            "name": sample.photo.name,
            "url": f"/media/{sample.photo.name}",
            "width": 2,
            "height": 3,
        }

        cleared = admin_client.patch(
            f"/admin-api/testapp/product/{sample.pk}",
            data={"data": {"photo": None}},
            content_type="application/json",
        )

        assert cleared.status_code == 200, cleared.json()
        assert cleared.json()["data"]["photo"] is None
        sample.refresh_from_db()
        assert sample.photo.name == ""
        assert sample.photo_width is None
        assert sample.photo_height is None
        cleared_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
        cleared_photo_attrs = next(
            field["attrs"] for field in cleared_form.json()["form"]["fields"] if field["name"] == "photo"
        )
        assert "current_file" not in cleared_photo_attrs
        clear_entry = LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).latest("action_time")
        assert json.loads(clear_entry.change_message) == [{"changed": {"fields": ["Photo"]}}]


def test_file_field_metadata_handles_storage_without_public_url(admin_client, sample, monkeypatch):
    manual_field = Product._meta.get_field("manual")
    monkeypatch.setattr(manual_field, "storage", Storage())

    detail = admin_client.get(f"/admin-api/testapp/product/{sample.pk}")

    assert detail.status_code == 200
    assert detail.json()["manual"] == {"name": "manuals/alpha.pdf", "url": None}

    change_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
    manual_attrs = next(field["attrs"] for field in change_form.json()["form"]["fields"] if field["name"] == "manual")

    assert change_form.status_code == 200
    assert manual_attrs["current_file"] == {"name": "manuals/alpha.pdf", "url": None}
    assert manual_attrs["clearable_file_input"] is True
    assert_no_rendered_field_attrs(manual_attrs)
