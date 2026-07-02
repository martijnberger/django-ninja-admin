from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DjangoNinjaAdminConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    default_site = "django_ninja_admin.sites.NinjaAdminSite"
    name = "django_ninja_admin"
    verbose_name = _("Django Ninja Admin")
