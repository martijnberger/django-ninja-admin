import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("slug", models.SlugField(blank=True, max_length=100, null=True, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name="CategorySlugLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="slug_links",
                        to="testapp.category",
                        to_field="slug",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="CategoryLimitedLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                (
                    "category",
                    models.ForeignKey(
                        limit_choices_to={"slug__startswith": "public"},
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="limited_links",
                        to="testapp.category",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Tag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
            ],
        ),
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("price", models.DecimalField(decimal_places=2, max_digits=8)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                (
                    "stock_status",
                    models.CharField(
                        choices=[("in_stock", "In Stock"), ("out_of_stock", "Out of Stock")],
                        default="in_stock",
                        max_length=20,
                    ),
                ),
                (
                    "condition",
                    models.CharField(
                        blank=True,
                        choices=[(None, "Unspecified"), ("new", "New"), ("used", "Used")],
                        default=None,
                        max_length=20,
                        null=True,
                    ),
                ),
                ("description", models.TextField(blank=True)),
                ("manual", models.FileField(blank=True, upload_to="manuals")),
                (
                    "photo",
                    models.ImageField(
                        blank=True,
                        height_field="photo_height",
                        upload_to="photos",
                        width_field="photo_width",
                    ),
                ),
                ("photo_width", models.PositiveIntegerField(blank=True, editable=False, null=True)),
                ("photo_height", models.PositiveIntegerField(blank=True, editable=False, null=True)),
                ("tags", models.ManyToManyField(blank=True, related_name="products", to="testapp.tag")),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="products",
                        to="testapp.category",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ProductImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=100)),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="testapp.product",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ProductReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("note", models.CharField(max_length=100)),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reviews",
                        to="testapp.product",
                    ),
                ),
            ],
        ),
    ]
