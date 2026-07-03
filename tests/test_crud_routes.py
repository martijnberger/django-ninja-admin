import json

from django_ninja_admin import VERTICAL, site
from django_ninja_admin.models import ADDITION, CHANGE, LogEntry
from tests.testapp.models import Product, ProductImage, Tag

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


def test_forms_create_update_delete_and_history(admin_client, sample):
    category = sample.category
    form = admin_client.get("/admin-api/testapp/product/form")
    assert form.status_code == 200
    assert form.json()["form"]["model"] == "testapp.product"
    fields_by_name = {field["name"]: field for field in form.json()["form"]["fields"]}
    assert fields_by_name["name"]["attrs"]["error_messages"]["required"] == "This field is required."
    assert fields_by_name["name"]["attrs"]["localize"] is False
    assert fields_by_name["name"]["attrs"]["is_localized"] is False
    assert fields_by_name["category"]["attrs"]["related_model"] == "testapp.category"
    assert fields_by_name["category"]["attrs"]["related_app_label"] == "testapp"
    assert fields_by_name["category"]["attrs"]["related_model_name"] == "category"
    assert fields_by_name["category"]["attrs"]["related_object_name"] == "Category"
    assert fields_by_name["category"]["attrs"]["related_verbose_name"] == "category"
    assert fields_by_name["category"]["attrs"]["to_field_name"] == "id"
    assert fields_by_name["category"]["attrs"]["to_field_class"] == "BigAutoField"
    assert fields_by_name["category"]["attrs"]["to_field_internal_type"] == "BigAutoField"
    assert fields_by_name["category"]["attrs"]["to_field_attname"] == "id"
    assert fields_by_name["category"]["attrs"]["model_field_name"] == "category"
    assert fields_by_name["category"]["attrs"]["model_field_class"] == "ForeignKey"
    assert fields_by_name["category"]["attrs"]["internal_type"] == "ForeignKey"
    assert fields_by_name["category"]["attrs"]["attname"] == "category_id"
    assert fields_by_name["category"]["attrs"]["column"] == "category_id"
    assert fields_by_name["category"]["attrs"]["blank"] is False
    assert fields_by_name["category"]["attrs"]["null"] is False
    assert fields_by_name["category"]["attrs"]["editable"] is True
    assert fields_by_name["price"]["attrs"]["max_digits"] == 8
    assert fields_by_name["price"]["attrs"]["decimal_places"] == 2
    assert fields_by_name["price"]["attrs"]["blank"] is False
    assert fields_by_name["price"]["attrs"]["unique"] is False
    assert fields_by_name["stock_status"]["attrs"]["choices"] == [
        ["in_stock", "In Stock"],
        ["out_of_stock", "Out of Stock"],
    ]
    assert fields_by_name["stock_status"]["attrs"]["default"] == "in_stock"
    assert fields_by_name["stock_status"]["attrs"]["admin_widget"] == "radio"
    assert fields_by_name["stock_status"]["attrs"]["add_id_index"] is True
    assert fields_by_name["stock_status"]["attrs"]["checked_attribute"] == {"checked": True}
    assert_no_rendered_field_attrs(fields_by_name["stock_status"]["attrs"])
    assert fields_by_name["stock_status"]["attrs"]["radio_orientation"] == VERTICAL
    assert fields_by_name["stock_status"]["attrs"]["radio"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "stock_status",
        "orientation": VERTICAL,
    }
    assert fields_by_name["category"]["attrs"]["admin_widget"] == "autocomplete"
    assert fields_by_name["category"]["attrs"]["autocomplete"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "category",
        "related_model": "testapp.category",
        "related_app_label": "testapp",
        "related_model_name": "category",
        "related_object_name": "Category",
        "related_verbose_name": "category",
        "related_verbose_name_plural": "categorys",
        "to_field_name": "id",
        "to_field_class": "BigAutoField",
        "to_field_internal_type": "BigAutoField",
        "to_field_attname": "id",
        "multiple": False,
        "url": "/admin-api/autocomplete",
        "query": {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "category",
        },
    }
    assert fields_by_name["description"]["attrs"]["blank"] is True
    assert fields_by_name["description"]["attrs"]["null"] is False
    assert fields_by_name["description"]["attrs"]["prepopulated_from"] == ["name"]
    assert fields_by_name["description"]["attrs"]["prepopulated"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "description",
        "sources": [{"field_name": "name", "label": "name", "internal_type": "CharField"}],
    }
    assert fields_by_name["manual"]["type"] == "FileField"
    assert fields_by_name["manual"]["attrs"]["needs_multipart_form"] is True
    assert fields_by_name["manual"]["attrs"]["blank"] is True
    assert fields_by_name["manual"]["attrs"]["upload_to"] == "manuals"
    assert fields_by_name["manual"]["attrs"]["clearable_file_input"] is True
    assert fields_by_name["manual"]["attrs"]["initial_text"] == "Currently"
    assert fields_by_name["manual"]["attrs"]["input_text"] == "Change"
    assert fields_by_name["manual"]["attrs"]["clear_checkbox_label"] == "Clear"
    assert_no_rendered_field_attrs(fields_by_name["manual"]["attrs"])
    assert fields_by_name["photo"]["type"] == "ImageField"
    assert fields_by_name["photo"]["attrs"]["needs_multipart_form"] is True
    assert fields_by_name["photo"]["attrs"]["image"] is True
    assert fields_by_name["photo"]["attrs"]["accepted_content_types"] == ["image/*"]
    assert_no_rendered_field_attrs(fields_by_name["photo"]["attrs"])
    assert fields_by_name["photo"]["attrs"]["upload_to"] == "photos"
    assert fields_by_name["photo"]["attrs"]["width_field"] == "photo_width"
    assert fields_by_name["photo"]["attrs"]["height_field"] == "photo_height"
    assert fields_by_name["tags"]["type"] == "ModelMultipleChoiceField"
    assert fields_by_name["tags"]["attrs"]["related_model"] == "testapp.tag"
    assert fields_by_name["tags"]["attrs"]["related_app_label"] == "testapp"
    assert fields_by_name["tags"]["attrs"]["related_model_name"] == "tag"
    assert fields_by_name["tags"]["attrs"]["related_object_name"] == "Tag"
    assert fields_by_name["tags"]["attrs"]["model_field_name"] == "tags"
    assert fields_by_name["tags"]["attrs"]["model_field_class"] == "ManyToManyField"
    assert fields_by_name["tags"]["attrs"]["internal_type"] == "ManyToManyField"
    assert fields_by_name["tags"]["attrs"]["multiple"] is True
    assert fields_by_name["tags"]["attrs"]["blank"] is True
    assert fields_by_name["tags"]["attrs"]["admin_widget"] == "filter_horizontal"
    assert fields_by_name["tags"]["attrs"]["filtered_select"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "tags",
        "direction": "horizontal",
        "is_stacked": False,
        "verbose_name": "tags",
        "related_model": "testapp.tag",
        "related_app_label": "testapp",
        "related_model_name": "tag",
        "related_verbose_name": "tag",
        "related_verbose_name_plural": "tags",
        "to_field_name": "id",
        "to_field_class": "BigAutoField",
        "to_field_internal_type": "BigAutoField",
        "to_field_attname": "id",
    }
    assert form.json()["form"]["filter_horizontal"] == ["tags"]

    change_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
    assert change_form.status_code == 200
    change_fields_by_name = {field["name"]: field for field in change_form.json()["form"]["fields"]}
    assert change_fields_by_name["category"]["attrs"]["selected_options"] == [
        {"id": str(sample.category_id), "text": "Cameras"}
    ]
    assert set(change_fields_by_name["tags"]["attrs"]["value"]) == set(sample.tags.values_list("pk", flat=True))
    assert {option["text"] for option in change_fields_by_name["tags"]["attrs"]["selected_options"]} == {
        "Featured",
        "Compact",
    }
    assert change_fields_by_name["manual"]["attrs"]["current_file"] == {
        "name": "manuals/alpha.pdf",
        "url": "/media/manuals/alpha.pdf",
    }
    assert fields_by_name["upper_name"]["attrs"]["read_only"] is True

    created = admin_client.post(
        "/admin-api/testapp/product",
        data={
            "data": {
                "name": "Gamma",
                "category": category.pk,
                "tags": list(sample.tags.values_list("pk", flat=True)),
                "price": "9.00",
                "stock_status": "in_stock",
                "description": "Created",
            },
            "inlines": {"testapp.productimage": {"add": [{"title": "Side"}]}},
        },
        content_type="application/json",
    )
    assert created.status_code == 201
    created_id = created.json()["data"]["id"]
    assert set(created.json()["data"]["tags"]) == set(sample.tags.values_list("pk", flat=True))
    assert set(Product.objects.get(pk=created_id).tags.values_list("pk", flat=True)) == set(
        sample.tags.values_list("pk", flat=True)
    )
    assert ProductImage.objects.filter(product_id=created_id, title="Side").exists()
    addition_entry = LogEntry.objects.get(object_id=str(created_id), action_flag=ADDITION)
    addition_message = json.loads(addition_entry.change_message)
    assert {"added": {"name": "product image", "object": "Side"}} in addition_message

    changed = admin_client.patch(
        f"/admin-api/testapp/product/{created_id}",
        data={"data": {"price": "11.00"}},
        content_type="application/json",
    )
    assert changed.status_code == 200
    assert Product.objects.get(pk=created_id).price == 11
    price_change_entry = LogEntry.objects.filter(object_id=str(created_id), action_flag=CHANGE).latest("action_time")
    assert json.loads(price_change_entry.change_message) == [{"changed": {"fields": ["Price"]}}]

    tag = Tag.objects.create(name="Clearance")
    retagged = admin_client.patch(
        f"/admin-api/testapp/product/{created_id}",
        data={"data": {"tags": [tag.pk]}},
        content_type="application/json",
    )
    assert retagged.status_code == 200
    assert retagged.json()["data"]["tags"] == [tag.pk]
    assert list(Product.objects.get(pk=created_id).tags.values_list("pk", flat=True)) == [tag.pk]
    change_entry = LogEntry.objects.filter(object_id=str(created_id), action_flag=CHANGE).latest("action_time")
    assert json.loads(change_entry.change_message) == [{"changed": {"fields": ["Tags"]}}]

    history = admin_client.get("/admin-api/history?app_label=testapp&model=product")
    assert history.status_code == 200
    assert history.json()["pagination"]["count"] >= 2
    latest_history = history.json()["results"][0]
    assert latest_history["change_message"] == [{"changed": {"fields": ["Tags"]}}]
    assert latest_history["change_message_text"] == "Changed Tags."

    deleted = admin_client.delete(f"/admin-api/testapp/product/{created_id}")
    assert deleted.status_code == 204


def test_direct_update_skips_empty_change_log(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    save_calls = []
    original_save_model = product_admin.save_model

    def save_model(request, obj, form, change):
        save_calls.append(obj.pk)
        return original_save_model(request, obj, form, change)

    monkeypatch.setattr(product_admin, "save_model", save_model)
    before = LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).count()
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"name": sample.name}},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert save_calls == [sample.pk]
    assert LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).count() == before
    sample.refresh_from_db()
    assert sample.name == "Alpha"
