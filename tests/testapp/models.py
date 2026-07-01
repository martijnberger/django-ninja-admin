from django.db import models
from django.urls import reverse
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=100)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="products")
    price = models.DecimalField(max_digits=8, decimal_places=2)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    stock_status = models.CharField(
        max_length=20,
        choices=[
            ("in_stock", "In Stock"),
            ("out_of_stock", "Out of Stock"),
        ],
        default="in_stock",
    )
    description = models.TextField(blank=True)
    manual = models.FileField(upload_to="manuals", blank=True)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("product-detail", kwargs={"pk": self.pk})


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    title = models.CharField(max_length=100)

    def __str__(self):
        return self.title


class ProductReview(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="reviews")
    note = models.CharField(max_length=100)

    def __str__(self):
        return self.note
