from django import forms
from django.core.validators import FileExtensionValidator
from django.db import models
from django.forms.models import BaseModelFormSet
from django.urls import path
from ninja import Schema, Status

from django_ninja_admin import VERTICAL, ModelAdmin, NinjaAdminSite, TabularInline
from tests.testapp.models import Article, ArticleLabel, Category, Label, Product, ProductImage, Tag


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


class ProductDeleteHookResponse(Schema):
    deleted_id: str
    deleted_display: str
    response_hook: str


class ProductAddHookResponse(Schema):
    hook: str
    id: int
    name: str


class ProductChangeHookResponse(Schema):
    hook: str
    id: int
    description: str


class ProductDeleteStatusHookResponse(Schema):
    hook: str
    id: str
    display: str


class CustomFormProductAdmin(ModelAdmin):
    form_class = ProductAdminForm
    filter_horizontal = ("tags",)
    ordering = ("name",)
    response_delete_schema = ProductDeleteHookResponse

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

    def delete_model(self, request, obj):
        Tag.objects.get_or_create(name=f"delete_model:{obj.pk}:{obj.name}")
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        names = list(queryset.order_by("name").values_list("name", flat=True))
        Tag.objects.get_or_create(name=f"delete_queryset:{','.join(names)}")
        super().delete_queryset(request, queryset)

    def response_delete(self, request, obj_display, obj_id):
        return {"deleted_id": obj_id, "deleted_display": obj_display, "response_hook": "delete"}


custom_form_site = NinjaAdminSite(name="custom_form_admin", include_auth=False)
custom_form_site.register(Category, ModelAdmin)
custom_form_site.register(Tag, ModelAdmin)
custom_form_site.register(Product, CustomFormProductAdmin)


class StatusHookProductAdmin(ModelAdmin):
    response_add_schema = ProductAddHookResponse
    response_change_schema = ProductChangeHookResponse
    response_delete_schema = ProductDeleteStatusHookResponse

    def response_add(self, request, obj, form, inline_results):
        return Status(202, {"hook": "add", "id": obj.pk, "name": obj.name})

    def response_change(self, request, obj, form, inline_results):
        return Status(202, {"hook": "change", "id": obj.pk, "description": obj.description})

    def response_delete(self, request, obj_display, obj_id):
        return Status(202, {"hook": "delete", "id": obj_id, "display": obj_display})


status_hook_site = NinjaAdminSite(name="status_hook_admin", include_auth=False)
status_hook_site.register(Category, ModelAdmin)
status_hook_site.register(Product, StatusHookProductAdmin)


class InvalidResponseHookProductAdmin(ModelAdmin):
    def response_add(self, request, obj, form, inline_results):
        response = super().response_add(request, obj, form, inline_results)
        response["data"]["unexpected_response_field"] = "invalid"
        return response

    def response_change(self, request, obj, form, inline_results):
        response = super().response_change(request, obj, form, inline_results)
        response["data"]["unexpected_response_field"] = "invalid"
        return response


invalid_response_hook_site = NinjaAdminSite(name="invalid_response_hook_admin", include_auth=False)
invalid_response_hook_site.register(Category, ModelAdmin)
invalid_response_hook_site.register(Product, InvalidResponseHookProductAdmin)


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


class TemporalProductForm(forms.ModelForm):
    description = forms.DateTimeField(
        required=False,
        input_formats=["%d/%m/%Y %H.%M"],
    )

    class Meta:
        model = Product
        fields = ("name", "category", "price", "stock_status", "description")

    def clean_description(self):
        value = self.cleaned_data["description"]
        return "" if value is None else value.isoformat()


class TemporalProductAdmin(ModelAdmin):
    form_class = TemporalProductForm


temporal_site = NinjaAdminSite(name="temporal_admin", include_auth=False)
temporal_site.register(Category, ModelAdmin)
temporal_site.register(Product, TemporalProductAdmin)


class ScalarProductForm(forms.ModelForm):
    homepage = forms.URLField(required=False)
    host = forms.GenericIPAddressField(required=False)
    tracking_id = forms.UUIDField(required=False)

    class Meta:
        model = Product
        fields = ("name", "category", "price", "stock_status", "homepage", "host", "tracking_id")


class ScalarProductAdmin(ModelAdmin):
    form_class = ScalarProductForm

    def save_form(self, request, form, change):
        obj = super().save_form(request, form, change)
        homepage = form.cleaned_data.get("homepage")
        host = form.cleaned_data.get("host")
        tracking_id = form.cleaned_data.get("tracking_id")
        if homepage or host or tracking_id:
            obj.description = f"{homepage}|{host}|{tracking_id}"
        return obj


scalar_site = NinjaAdminSite(name="scalar_admin", include_auth=False)
scalar_site.register(Category, ModelAdmin)
scalar_site.register(Product, ScalarProductAdmin)


class DisabledProductForm(forms.ModelForm):
    name = forms.CharField(disabled=True, initial="Server named product", max_length=100)

    class Meta:
        model = Product
        fields = ("name", "category", "price", "stock_status")


class DisabledProductAdmin(ModelAdmin):
    form_class = DisabledProductForm


disabled_site = NinjaAdminSite(name="disabled_admin", include_auth=False)
disabled_site.register(Category, ModelAdmin)
disabled_site.register(Product, DisabledProductAdmin)


class RequiredManualProductForm(forms.ModelForm):
    manual = forms.FileField(required=True, validators=[FileExtensionValidator(["pdf", "txt"])])

    class Meta:
        model = Product
        fields = ("name", "category", "price", "stock_status", "manual")


class RequiredManualProductAdmin(ModelAdmin):
    form_class = RequiredManualProductForm


required_file_site = NinjaAdminSite(name="required_file_admin", include_auth=False)
required_file_site.register(Category, ModelAdmin)
required_file_site.register(Product, RequiredManualProductAdmin)


class BlockingBulkProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ("name", "category", "price", "stock_status")

    def clean(self):
        raise forms.ValidationError("The change form should not validate list-editable rows.")


class BulkStatusForm(forms.ModelForm):
    stock_status = forms.ChoiceField(
        choices=(("out_of_stock", "Bulk unavailable"),),
        help_text="Bulk-only status field.",
    )

    class Meta:
        model = Product
        fields = ("stock_status",)


class BulkStatusFormSet(BaseModelFormSet):
    @classmethod
    def get_default_prefix(cls):
        return "bulk_status"

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        for form in self.forms:
            if form.cleaned_data.get("stock_status") == "out_of_stock" and form.instance.name == "Beta":
                raise forms.ValidationError("Beta cannot be bulk disabled.")


class BulkFormProductAdmin(ModelAdmin):
    form_class = BlockingBulkProductForm
    changelist_formset = BulkStatusFormSet
    list_display = ("name", "stock_status")
    list_display_links = ("name",)
    list_editable = ("stock_status",)

    def get_changelist_form_class(self, request):
        return BulkStatusForm


bulk_form_site = NinjaAdminSite(name="bulk_form_admin", include_auth=False)
bulk_form_site.register(Category, ModelAdmin)
bulk_form_site.register(Product, BulkFormProductAdmin)


class InlineCodeProductImageForm(forms.ModelForm):
    title = CodeCountField()

    class Meta:
        model = ProductImage
        fields = ("title",)


class InlineCodeProductImageInline(TabularInline):
    model = ProductImage
    form_class = InlineCodeProductImageForm
    extra = 0


class InlineMultiValueProductAdmin(ModelAdmin):
    inlines = [InlineCodeProductImageInline]


inline_multivalue_site = NinjaAdminSite(name="inline_multivalue_admin", include_auth=False)
inline_multivalue_site.register(Category, ModelAdmin)
inline_multivalue_site.register(ProductImage, ModelAdmin)
inline_multivalue_site.register(Product, InlineMultiValueProductAdmin)


class ArticleLabelInline(TabularInline):
    model = ArticleLabel
    extra = 0


class ThroughInlineArticleAdmin(ModelAdmin):
    inlines = [ArticleLabelInline]


through_inline_site = NinjaAdminSite(name="through_inline_admin", include_auth=False)
through_inline_site.register(Label, ModelAdmin)
through_inline_site.register(ArticleLabel, ModelAdmin)
through_inline_site.register(Article, ThroughInlineArticleAdmin)


urlpatterns = [
    path("custom-form-admin/", custom_form_site.urls),
    path("status-hook-admin/", status_hook_site.urls),
    path("invalid-response-hook-admin/", invalid_response_hook_site.urls),
    path("custom-formfield-admin/", custom_formfield_site.urls),
    path("split-datetime-admin/", split_datetime_site.urls),
    path("multi-value-admin/", multi_value_site.urls),
    path("temporal-admin/", temporal_site.urls),
    path("scalar-admin/", scalar_site.urls),
    path("disabled-admin/", disabled_site.urls),
    path("required-file-admin/", required_file_site.urls),
    path("bulk-form-admin/", bulk_form_site.urls),
    path("inline-multivalue-admin/", inline_multivalue_site.urls),
    path("through-inline-admin/", through_inline_site.urls),
]
