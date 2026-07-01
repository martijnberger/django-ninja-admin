from django import forms
from django.urls import path

from django_ninja_admin import ModelAdmin, NinjaAdminSite
from tests.testapp.models import Category, Product, Tag


class ProductAdminForm(forms.ModelForm):
    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={"data-admin": "custom"}),
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


custom_form_site = NinjaAdminSite(name="custom_form_admin", include_auth=False)
custom_form_site.register(Category, ModelAdmin)
custom_form_site.register(Tag, ModelAdmin)
custom_form_site.register(Product, CustomFormProductAdmin)

urlpatterns = [
    path("custom-form-admin/", custom_form_site.urls),
]
