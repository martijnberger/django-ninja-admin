from django_ninja_admin import VERTICAL, ModelAdmin, SimpleListFilter, TabularInline, action, display, site
from tests.testapp.models import Category, Product, ProductImage, Tag


class PriceBandFilter(SimpleListFilter):
    title = "price band"
    parameter_name = "price_band"

    def lookups(self, request, model_admin):
        return [("cheap", "Cheap"), ("premium", "Premium")]

    def queryset(self, request, queryset):
        if self.value() == "cheap":
            return queryset.filter(price__lt=10)
        if self.value() == "premium":
            return queryset.filter(price__gte=10)
        return queryset


class ProductImageInline(TabularInline):
    model = ProductImage
    extra = 1
    min_num = 0
    max_num = 3


class ProductAdmin(ModelAdmin):
    list_display = ("name", "category", "price", "stock_status", "upper_name", "has_description", "tagline")
    list_filter = ("stock_status", "category", PriceBandFilter)
    list_editable = ("stock_status",)
    search_fields = ("name", "description", "category__name")
    autocomplete_fields = ("category",)
    filter_horizontal = ("tags",)
    ordering = ("name",)
    inlines = [ProductImageInline]
    actions = ["mark_out_of_stock", "report_names"]
    readonly_fields = ("upper_name",)
    date_hierarchy = "created_at"
    radio_fields = {"stock_status": VERTICAL}
    prepopulated_fields = {"description": ("name",)}

    @display(description="Upper name", ordering="name")
    def upper_name(self, obj):
        return obj.name.upper()

    @display(boolean=True, description="Has description")
    def has_description(self, obj):
        return bool(obj.description)

    @display(description="Tagline", empty_value="No description")
    def tagline(self, obj):
        return obj.description or None

    @action(description="Mark out of stock", permissions=["change"])
    def mark_out_of_stock(self, request, queryset):
        queryset.update(stock_status="out_of_stock")

    @action(description="Report names", permissions=["view"])
    def report_names(self, request, queryset):
        return {"names": list(queryset.order_by("name").values_list("name", flat=True))}


class CategoryAdmin(ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


class TagAdmin(ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


site.register(Category, CategoryAdmin)
site.register(Tag, TagAdmin)
site.register(Product, ProductAdmin)
