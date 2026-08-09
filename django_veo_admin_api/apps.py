from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DjangoVeoAdminApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    default_site = "django_veo_admin_api.sites.NinjaAdminSite"
    name = "django_veo_admin_api"
    verbose_name = _("Django Veo Admin API")
