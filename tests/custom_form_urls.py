from django import forms
from django.db import models
from django.urls import path
from ninja import Status

from django_ninja_admin import VERTICAL, ModelAdmin, NinjaAdminSite
from tests.testapp.models import Category, Product, Tag


class ProductNameWidget(forms.TextInput):
    class Media:
        css = {
            "all": ("admin/product-name.css",),
            "print": ("/print/product-name.css",),
        }
        js = ("admin/product-name.js", "https://cdn.example.test/product-name.js")


class ProductAdminForm(forms.ModelForm):
    name = forms.CharField(
        max_length=100,
        widget=ProductNameWidget(attrs={"data-admin": "custom"}),
        error_messages={"required": "Product name is required."},
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    class Meta:
        model = Product
        fields = ("name", "category", "tags", "price", "stock_status", "description")

    def clean_name(self):
        name = self.cleaned_data["name"]
        if name == "Forbidden":
            raise forms.ValidationError("Forbidden product name.")
        return name


class CustomFormProductAdmin(ModelAdmin):
    form_class = ProductAdminForm
    filter_horizontal = ("tags",)
    ordering = ("name",)

    def save_form(self, request, form, change):
        obj = super().save_form(request, form, change)
        action = "change" if change else "add"
        obj.description = f"{obj.description} [{action}:save_form]"
        return obj

    def save_model(self, request, obj, form, change):
        action = "change" if change else "add"
        obj.description = f"{obj.description} [{action}:save_model]"
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, inline_results, change):
        super().save_related(request, form, inline_results, change)
        tag, _created = Tag.objects.get_or_create(name="Hooked")
        form.instance.tags.add(tag)

    def response_add(self, request, obj, form, inline_results):
        response = super().response_add(request, obj, form, inline_results)
        response["data"]["response_hook"] = "add"
        return response

    def response_change(self, request, obj, form, inline_results):
        response = super().response_change(request, obj, form, inline_results)
        response["data"]["response_hook"] = "change"
        return response

    def delete_model(self, request, obj):
        Tag.objects.get_or_create(name=f"delete_model:{obj.pk}:{obj.name}")
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        names = list(queryset.order_by("name").values_list("name", flat=True))
        Tag.objects.get_or_create(name=f"delete_queryset:{','.join(names)}")
        super().delete_queryset(request, queryset)

    def response_delete(self, request, obj_display, obj_id):
        return Status(200, {"deleted_id": obj_id, "deleted_display": obj_display, "response_hook": "delete"})


custom_form_site = NinjaAdminSite(name="custom_form_admin", include_auth=False)
custom_form_site.register(Category, ModelAdmin)
custom_form_site.register(Tag, ModelAdmin)
custom_form_site.register(Product, CustomFormProductAdmin)


class FormfieldHookProductAdmin(ModelAdmin):
    formfield_overrides = {
        models.TextField: {
            "widget": forms.Textarea(attrs={"rows": 4, "data-hook": "override"}),
            "help_text": "Describe the product carefully.",
        }
    }
    radio_fields = {"stock_status": VERTICAL}

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "name":
            kwargs["help_text"] = "Name from formfield_for_dbfield."
            kwargs["min_length"] = 3
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        return formfield

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "category":
            kwargs["queryset"] = Category.objects.filter(name__startswith="Allowed")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "stock_status":
            kwargs["choices"] = [("in_stock", "Available")]
        return super().formfield_for_choice_field(db_field, request, **kwargs)


custom_formfield_site = NinjaAdminSite(name="custom_formfield_admin", include_auth=False)
custom_formfield_site.register(Category, ModelAdmin)
custom_formfield_site.register(Tag, ModelAdmin)
custom_formfield_site.register(Product, FormfieldHookProductAdmin)


class SplitDateTimeProductForm(forms.ModelForm):
    description = forms.SplitDateTimeField(
        required=False,
        input_date_formats=["%Y-%m-%d"],
        input_time_formats=["%H:%M", "%H:%M:%S"],
    )

    class Meta:
        model = Product
        fields = ("name", "category", "price", "stock_status", "description")

    def clean_description(self):
        value = self.cleaned_data["description"]
        return "" if value is None else value.isoformat()


class SplitDateTimeProductAdmin(ModelAdmin):
    form_class = SplitDateTimeProductForm


split_datetime_site = NinjaAdminSite(name="split_datetime_admin", include_auth=False)
split_datetime_site.register(Category, ModelAdmin)
split_datetime_site.register(Product, SplitDateTimeProductAdmin)


class CodeCountWidget(forms.MultiWidget):
    def __init__(self, attrs=None):
        super().__init__([forms.TextInput(), forms.NumberInput()], attrs)

    def decompress(self, value):
        if not value:
            return ["", ""]
        code, _separator, count = str(value).partition(":")
        return [code, count]


class CodeCountField(forms.MultiValueField):
    widget = CodeCountWidget

    def __init__(self, *args, **kwargs):
        fields = (
            forms.RegexField(regex=r"^[A-Z]{3}$"),
            forms.IntegerField(min_value=1, max_value=9),
        )
        super().__init__(*args, fields=fields, require_all_fields=True, **kwargs)

    def compress(self, data_list):
        if not data_list:
            return ""
        return f"{data_list[0]}:{data_list[1]}"


class MultiValueProductForm(forms.ModelForm):
    description = CodeCountField(required=False)

    class Meta:
        model = Product
        fields = ("name", "category", "price", "stock_status", "description")


class MultiValueProductAdmin(ModelAdmin):
    form_class = MultiValueProductForm


multi_value_site = NinjaAdminSite(name="multi_value_admin", include_auth=False)
multi_value_site.register(Category, ModelAdmin)
multi_value_site.register(Product, MultiValueProductAdmin)


urlpatterns = [
    path("custom-form-admin/", custom_form_site.urls),
    path("custom-formfield-admin/", custom_formfield_site.urls),
    path("split-datetime-admin/", split_datetime_site.urls),
    path("multi-value-admin/", multi_value_site.urls),
]
