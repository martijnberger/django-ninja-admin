import json

from django import forms
from django.test import RequestFactory, override_settings

from django_ninja_admin import NinjaAdminSite, TabularInline
from django_ninja_admin.models import CHANGE, LogEntry
from tests.testapp.models import Product, ProductImage

RENDERED_FIELD_ATTR_KEYS = {
    "auto_id",
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


def test_form_description_uses_inline_count_hooks(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    def get_extra(self, request, obj=None, **kwargs):
        return 2 if obj is not None else 4

    def get_min_num(self, request, obj=None, **kwargs):
        return 1

    def get_max_num(self, request, obj=None, **kwargs):
        return 5

    monkeypatch.setattr(ProductImageInline, "get_extra", get_extra)
    monkeypatch.setattr(ProductImageInline, "get_min_num", get_min_num)
    monkeypatch.setattr(ProductImageInline, "get_max_num", get_max_num)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 200
    inline = next(item for item in response.json()["inlines"] if item["model"] == "testapp.productimage")
    assert inline["extra"] == 2
    assert inline["min_num"] == 1
    assert inline["max_num"] == 5
    assert inline["prepopulated"] == {}
    assert inline["fieldset_layout"] == [
        {
            "name": None,
            "classes": [],
            "description": None,
            "fields": ["id", "product", "title"],
            "rows": [{"fields": ["id"]}, {"fields": ["product"]}, {"fields": ["title"]}],
        }
    ]
    assert inline["formset_prefix"] == "images"
    assert inline["total_form_count"] == 3
    assert inline["initial_form_count"] == 1
    management_fields = {field["name"]: field for field in inline["management_form"]}
    assert_no_rendered_field_attrs(management_fields["TOTAL_FORMS"]["attrs"])
    assert management_fields["TOTAL_FORMS"]["attrs"]["value"] == 3
    assert_no_rendered_field_attrs(management_fields["INITIAL_FORMS"]["attrs"])
    assert management_fields["INITIAL_FORMS"]["attrs"]["value"] == 1
    assert management_fields["MIN_NUM_FORMS"]["attrs"]["value"] == 1
    assert management_fields["MAX_NUM_FORMS"]["attrs"]["value"] == 5
    assert [row["prefix"] for row in inline["formset_row_metadata"]] == ["images-0", "images-1", "images-2"]
    assert [row["is_initial"] for row in inline["formset_row_metadata"]] == [True, False, False]
    assert inline["formset_row_metadata"][0]["object_id"] == str(ProductImage.objects.get(product=sample).pk)
    title_values = [
        next(field for field in row if field["name"] == "title")["attrs"].get("value") for row in inline["formset"]
    ]
    assert title_values == ["Front", None, None]
    first_row_fields = {field["name"]: field for field in inline["formset"][0]}
    assert_no_rendered_field_attrs(first_row_fields["title"]["attrs"])
    assert_no_rendered_field_attrs(first_row_fields["id"]["attrs"])
    assert_no_rendered_field_attrs(first_row_fields["DELETE"]["attrs"])
    assert_no_rendered_field_attrs(first_row_fields["product"]["attrs"])
    assert inline["empty_form_prefix"] == "images-__prefix__"
    empty_form_fields = {field["name"]: field for field in inline["empty_form"]}
    assert_no_rendered_field_attrs(empty_form_fields["title"]["attrs"])

    add_response = admin_client.get("/admin-api/testapp/product/form")

    assert add_response.status_code == 200
    add_inline = next(item for item in add_response.json()["inlines"] if item["model"] == "testapp.productimage")
    assert add_inline["extra"] == 4
    assert add_inline["min_num"] == 1
    assert add_inline["formset_prefix"] == "images"
    assert add_inline["total_form_count"] == 5
    assert add_inline["initial_form_count"] == 0
    assert len(add_inline["formset"]) == 5
    assert [row["prefix"] for row in add_inline["formset_row_metadata"]] == [
        "images-0",
        "images-1",
        "images-2",
        "images-3",
        "images-4",
    ]
    assert all(row["is_initial"] is False for row in add_inline["formset_row_metadata"])


def test_form_description_rejects_invalid_dynamic_inline_count_hooks(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    def negative_extra(self, request, obj=None, **kwargs):
        return -1

    monkeypatch.setattr(ProductImageInline, "get_extra", negative_extra)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 400
    assert response.json()["errors"] == [
        {
            "message": "Inline 'extra' must not be negative.",
            "param": "inlines.testapp.productimage.extra",
        }
    ]

    def zero_extra(self, request, obj=None, **kwargs):
        return 0

    def min_num(self, request, obj=None, **kwargs):
        return 3

    def max_num(self, request, obj=None, **kwargs):
        return 1

    monkeypatch.setattr(ProductImageInline, "get_extra", zero_extra)
    monkeypatch.setattr(ProductImageInline, "get_min_num", min_num)
    monkeypatch.setattr(ProductImageInline, "get_max_num", max_num)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 400
    assert response.json()["errors"] == [
        {
            "message": "Inline 'min_num' must not exceed 'max_num'.",
            "param": "inlines.testapp.productimage.min_num",
        }
    ]


def test_inline_descriptions_use_formfield_hooks_and_media(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    class InlineTitleWidget(forms.TextInput):
        class Media:
            css = {"all": ("admin/inline-title.css",)}
            js = ("admin/inline-title.js",)

    original_formfield_for_dbfield = ProductImageInline.formfield_for_dbfield

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "title":
            kwargs["help_text"] = "Inline title from formfield hook."
            kwargs["widget"] = InlineTitleWidget(attrs={"data-inline": "title"})
        return original_formfield_for_dbfield(self, db_field, request, **kwargs)

    monkeypatch.setattr(ProductImageInline, "formfield_for_dbfield", formfield_for_dbfield)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 200
    inline = next(item for item in response.json()["inlines"] if item["model"] == "testapp.productimage")
    assert inline["media"] == {
        "css": {"all": ["admin/inline-title.css"]},
        "js": ["admin/inline-title.js"],
    }
    title_fields = [field for row in inline["formset"] for field in row if field["name"] == "title"]
    assert title_fields
    assert all(field["attrs"]["help_text"] == "Inline title from formfield hook." for field in title_fields)
    assert all(field["attrs"]["widget_attrs"]["data-inline"] == "title" for field in title_fields)


def test_inline_admin_form_class_drives_metadata_and_validation(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    class ProductImageAdminForm(forms.ModelForm):
        title = forms.CharField(
            max_length=100,
            required=False,
            help_text="Inline title from custom form.",
            widget=forms.TextInput(attrs={"data-form": "inline"}),
        )

        class Meta:
            model = ProductImage
            fields = ("title",)

        def clean_title(self):
            title = self.cleaned_data["title"]
            if title == "Forbidden":
                raise forms.ValidationError("Forbidden inline title.")
            return title

    monkeypatch.setattr(ProductImageInline, "form_class", ProductImageAdminForm)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 200
    inline = next(item for item in response.json()["inlines"] if item["model"] == "testapp.productimage")
    title_fields = [field for row in inline["formset"] for field in row if field["name"] == "title"]
    assert title_fields
    assert all(field["attrs"]["required"] is False for field in title_fields)
    assert all(field["attrs"]["help_text"] == "Inline title from custom form." for field in title_fields)
    assert all(field["attrs"]["widget_attrs"]["data-form"] == "inline" for field in title_fields)
    inline_admin = ProductImageInline(Product, NinjaAdminSite(include_auth=False))
    row_schema = inline_admin.get_inline_row_schema(RequestFactory().get("/"), sample)
    assert "title" not in row_schema.model_json_schema().get("required", [])

    invalid = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": "Forbidden"}]}}},
        content_type="application/json",
    )

    assert invalid.status_code == 400
    assert "Forbidden inline title." in str(invalid.json()["errors"])
    assert not ProductImage.objects.filter(product=sample, title="Forbidden").exists()

    valid = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": "Allowed inline"}]}}},
        content_type="application/json",
    )

    assert valid.status_code == 200
    assert ProductImage.objects.filter(product=sample, title="Allowed inline").exists()


def test_disabled_inline_form_fields_are_optional_in_write_schema(db, sample):
    class DisabledProductImageForm(forms.ModelForm):
        title = forms.CharField(disabled=True, initial="Generated image title", max_length=100)

        class Meta:
            model = ProductImage
            fields = ("title",)

    class DisabledProductImageInline(TabularInline):
        model = ProductImage
        form_class = DisabledProductImageForm

    inline_admin = DisabledProductImageInline(Product, NinjaAdminSite(include_auth=False))
    request = RequestFactory().get(f"/admin-api/testapp/product/{sample.pk}/form")
    field = inline_admin.get_form_fields_description(request, None)[0]
    row_schema = inline_admin.get_inline_row_schema(request, sample)

    assert field["name"] == "title"
    assert field["attrs"]["required"] is True
    assert field["attrs"]["disabled"] is True
    assert field["attrs"]["initial"] == "Generated image title"
    assert "title" not in row_schema.model_json_schema().get("required", [])


def test_inline_payload_uses_pydantic_request_validation(admin_client, sample):
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{}]}}},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["param"] == "inlines.testapp.productimage.add.0.title"


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_inline_multivalue_payload_uses_pydantic_and_formset_normalization(admin_client, sample):
    product = Product.objects.create(
        name="Inline coded",
        category=sample.category,
        price="4.00",
        stock_status="in_stock",
    )

    invalid = admin_client.patch(
        f"/inline-multivalue-admin/testapp/product/{product.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": ["abc", 4]}]}}},
        content_type="application/json",
    )
    assert invalid.status_code == 422
    assert invalid.json()["errors"][0]["param"] == "inlines.testapp.productimage.add.0.title.0"
    assert not ProductImage.objects.filter(product=product).exists()

    created = admin_client.patch(
        f"/inline-multivalue-admin/testapp/product/{product.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": ["ABC", "4"]}]}}},
        content_type="application/json",
    )
    assert created.status_code == 200, created.json()
    image = ProductImage.objects.get(product=product)
    assert image.title == "ABC:4"
    assert created.json()["inlines"]["testapp.productimage"]["add"][0]["title"] == "ABC:4"

    changed = admin_client.patch(
        f"/inline-multivalue-admin/testapp/product/{product.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"change": [{"pk": image.pk, "title": ["XYZ", 9]}]}}},
        content_type="application/json",
    )
    assert changed.status_code == 200, changed.json()
    image.refresh_from_db()
    assert image.title == "XYZ:9"
    assert changed.json()["inlines"]["testapp.productimage"]["change"][0]["title"] == "XYZ:9"


def test_inline_mutations_check_inline_permissions(staff_client, sample):
    client = staff_client("change_product")
    image = ProductImage.objects.get(product=sample)

    add_response = client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": "Side"}]}}},
        content_type="application/json",
    )
    assert add_response.status_code == 403
    assert ProductImage.objects.filter(product=sample).count() == 1

    change_response = client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"change": [{"pk": image.pk, "title": "Side"}]}}},
        content_type="application/json",
    )
    assert change_response.status_code == 403
    image.refresh_from_db()
    assert image.title == "Front"

    delete_response = client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"delete": [image.pk]}}},
        content_type="application/json",
    )
    assert delete_response.status_code == 403
    assert ProductImage.objects.filter(pk=image.pk).exists()


def test_inline_mutations_reject_unknown_and_readonly_fields(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    image = sample.images.get()
    unknown_response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {"testapp.productimage": {"change": [{"pk": image.pk, "title": "Side", "bogus": "x"}]}},
        },
        content_type="application/json",
    )
    assert unknown_response.status_code == 422
    assert unknown_response.json()["errors"] == [
        {"message": "Extra inputs are not permitted", "param": "inlines.testapp.productimage.change.0.bogus"}
    ]

    monkeypatch.setattr(ProductImageInline, "readonly_fields", ("title",))
    readonly_response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"change": [{"pk": image.pk, "title": "Side"}]}}},
        content_type="application/json",
    )
    assert readonly_response.status_code == 400
    assert readonly_response.json()["errors"] == [
        {
            "message": "Unknown or readonly inline field.",
            "param": "inlines.testapp.productimage.change.0.title",
        }
    ]
    image.refresh_from_db()
    assert image.title == "Front"


def test_inline_mutations_reject_unknown_inline_keys(admin_client, sample):
    unknown_inline = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.unknown": {"add": []}}},
        content_type="application/json",
    )
    assert unknown_inline.status_code == 422
    assert unknown_inline.json()["errors"] == [
        {"message": "Extra inputs are not permitted", "param": "inlines.testapp.unknown"}
    ]

    unknown_operation = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"replace": []}}},
        content_type="application/json",
    )
    assert unknown_operation.status_code == 422
    assert unknown_operation.json()["errors"] == [
        {"message": "Extra inputs are not permitted", "param": "inlines.testapp.productimage.replace"}
    ]


def test_inline_formset_enforces_max_num(admin_client, sample):
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {
                "testapp.productimage": {
                    "add": [
                        {"title": "Side"},
                        {"title": "Back"},
                        {"title": "Detail"},
                    ]
                }
            },
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    assert ProductImage.objects.filter(product=sample).count() == 1


def test_inline_formset_honors_can_delete(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    image = sample.images.get()
    monkeypatch.setattr(ProductImageInline, "can_delete", False)
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"delete": [image.pk]}}},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert ProductImage.objects.filter(pk=image.pk).exists()


def test_inline_change_message_includes_inline_operations(admin_client, sample):
    image = sample.images.get()
    deleted_image = ProductImage.objects.create(product=sample, title="Back")
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {
                "testapp.productimage": {
                    "change": [{"pk": image.pk, "title": "Profile"}],
                    "add": [{"title": "Side"}],
                    "delete": [deleted_image.pk],
                }
            },
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    inline_response = response.json()["inlines"]["testapp.productimage"]
    assert "_changed_fields" not in inline_response["change"][0]
    assert inline_response["delete"] == [deleted_image.pk]
    change_entry = LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).latest("action_time")
    change_message = json.loads(change_entry.change_message)
    assert {"added": {"name": "product image", "object": "Side"}} in change_message
    assert {"changed": {"name": "product image", "object": "Profile", "fields": ["title"]}} in change_message
    assert {"deleted": {"name": "product image", "object": "Back"}} in change_message
    history = admin_client.get(
        "/admin-api/history",
        {"app_label": "testapp", "model": "product", "object_id": str(sample.pk), "action_flag": CHANGE},
    )
    assert history.status_code == 200
    assert history.json()["results"][0]["change_message_text"] == (
        "Added product image \u201cSide\u201d. "
        "Changed title for product image \u201cProfile\u201d. "
        "Deleted product image \u201cBack\u201d."
    )


def test_inline_mutation_rejects_duplicate_and_conflicting_rows(admin_client, sample):
    image = sample.images.get()

    duplicate_change = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {
                "testapp.productimage": {
                    "change": [
                        {"pk": image.pk, "title": "Front A"},
                        {"pk": image.pk, "title": "Front B"},
                    ]
                }
            },
        },
        content_type="application/json",
    )
    assert duplicate_change.status_code == 400
    assert ProductImage.objects.get(pk=image.pk).title == "Front"

    changed_and_deleted = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {
                "testapp.productimage": {
                    "change": [{"pk": image.pk, "title": "Front A"}],
                    "delete": [image.pk],
                }
            },
        },
        content_type="application/json",
    )
    assert changed_and_deleted.status_code == 400
    assert ProductImage.objects.filter(pk=image.pk, title="Front").exists()

    duplicate_delete = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"delete": [image.pk, image.pk]}}},
        content_type="application/json",
    )
    assert duplicate_delete.status_code == 400
    assert ProductImage.objects.filter(pk=image.pk).exists()


def test_inline_mutation_aggregates_server_side_row_errors(admin_client, sample):
    image = sample.images.get()
    other = ProductImage.objects.create(product=sample, title="Back")

    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {"price": "99.00"},
            "inlines": {
                "testapp.productimage": {
                    "change": [
                        {"pk": image.pk, "title": "Profile"},
                        {"pk": other.pk, "title": "Back A"},
                        {"pk": other.pk, "title": "Back B"},
                        {"pk": 999999, "title": "Ghost"},
                    ],
                    "delete": [image.pk, 999999],
                }
            },
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    errors = response.json()["errors"]
    assert {
        "message": "Inline object cannot be changed and deleted in the same request.",
        "param": "inlines.testapp.productimage.change.0.pk",
    } in errors
    assert {
        "message": "Duplicate inline change pk.",
        "param": "inlines.testapp.productimage.change.2.pk",
    } in errors
    assert {
        "message": "Unknown inline object.",
        "param": "inlines.testapp.productimage.change.3.pk",
    } in errors
    assert {
        "message": "Unknown inline object.",
        "param": "inlines.testapp.productimage.delete.1.pk",
    } in errors
    assert len(errors) == 4
    image.refresh_from_db()
    other.refresh_from_db()
    sample.refresh_from_db()
    assert image.title == "Front"
    assert other.title == "Back"
    assert str(sample.price) == "12.50"
    assert not LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).exists()


def test_inline_mutation_rolls_back_parent_save_for_unknown_inline_object(admin_client, sample):
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {"price": "99.00"},
            "inlines": {"testapp.productimage": {"change": [{"pk": 999999, "title": "Ghost"}]}},
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["errors"] == [
        {"message": "Unknown inline object.", "param": "inlines.testapp.productimage.change.0.pk"}
    ]
    sample.refresh_from_db()
    assert str(sample.price) == "12.50"
    assert not LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).exists()
