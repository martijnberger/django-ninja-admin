from django_ninja_admin import ModelAdmin, TabularInline, action, display, site
from tests.testapp.models import Category, Product, ProductImage


class ProductImageInline(TabularInline):
    model = ProductImage
    extra = 1
    min_num = 0
    max_num = 3


class ProductAdmin(ModelAdmin):
    list_display = ("name", "category", "price", "stock_status", "upper_name")
    list_filter = ("stock_status",)
    list_editable = ("stock_status",)
    search_fields = ("name", "description", "category__name")
    ordering = ("name",)
    inlines = [ProductImageInline]
    actions = ["mark_out_of_stock"]
    readonly_fields = ("upper_name",)

    @display(description="Upper name")
    def upper_name(self, obj):
        return obj.name.upper()

    @action(description="Mark out of stock", permissions=["change"])
    def mark_out_of_stock(self, request, queryset):
        queryset.update(stock_status="out_of_stock")


class CategoryAdmin(ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


site.register(Category, CategoryAdmin)
site.register(Product, ProductAdmin)
