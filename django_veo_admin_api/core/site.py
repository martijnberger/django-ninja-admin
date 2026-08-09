"""Transport-neutral Django admin registry and operation facade."""

from typing import Any, cast, override
from weakref import WeakSet

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import Paginator
from django.db.models.base import ModelBase
from django.utils.translation import gettext as _

from django_veo_admin_api import actions
from django_veo_admin_api.admins.model import ModelAdmin
from django_veo_admin_api.core.exceptions import AlreadyRegistered, NotRegistered
from django_veo_admin_api.core.operations import AdminRequestContext
from django_veo_admin_api.core.operations.actions import ActionOperations
from django_veo_admin_api.core.operations.autocomplete import AutocompleteOperations
from django_veo_admin_api.core.operations.bulk import BulkMutationOperations
from django_veo_admin_api.core.operations.changelist import ChangelistOperations
from django_veo_admin_api.core.operations.deletion import DeletionOperations
from django_veo_admin_api.core.operations.discovery import DiscoveryOperations
from django_veo_admin_api.core.operations.forms import FormOperations
from django_veo_admin_api.core.operations.history import HistoryOperations
from django_veo_admin_api.core.operations.mutations import MutationOperations
from django_veo_admin_api.core.operations.objects import ObjectOperations

DEFAULT_SITE_TITLE = "Django Veo Admin API"
DEFAULT_SITE_HEADER = "Django Veo administration"
DEFAULT_INDEX_TITLE = "Site administration"

all_sites: WeakSet[Any] = WeakSet()


class CoreAdminSite:
    """Django-admin registry shared by every transport integration."""

    admin_class = ModelAdmin
    paginator = Paginator
    site_title = DEFAULT_SITE_TITLE
    site_header = DEFAULT_SITE_HEADER
    index_title = DEFAULT_INDEX_TITLE
    site_url = "/"
    enable_nav_sidebar = True
    empty_value_display = "-"
    include_auth = True
    changelist_max_per_page = 200
    history_max_per_page = 100
    autocomplete_per_page = 20
    autocomplete_max_per_page = 100
    model_field_type_resolvers: tuple[Any, ...] = ()

    def __init__(self, *, name="veo_admin_api", include_auth=True):
        self.name = name
        self.include_auth = include_auth
        self._registry = {}
        self._actions = {"delete_selected": actions.delete_selected}
        self._global_actions = self._actions.copy()
        all_sites.add(self)
        if include_auth:
            from django_veo_admin_api.admins.auth import AuthGroupAdmin, AuthUserAdmin

            self.register(get_user_model(), AuthUserAdmin)
            self.register(Group, AuthGroupAdmin)

    @override
    def __repr__(self):
        return f"{self.__class__.__name__}(name={self.name!r})"

    @property
    def actions(self):
        return self._actions.items()

    def clear_cache(self):
        """Allow transport subclasses to invalidate generated artifacts."""

    def get_model_field_type_resolvers(self):
        return self.model_field_type_resolvers

    def register(self, model_or_iterable, admin_class=None, **options):
        admin_class = cast(type[ModelAdmin], admin_class or self.admin_class)
        if isinstance(model_or_iterable, ModelBase):
            model_or_iterable = [model_or_iterable]
        for model in model_or_iterable:
            if model._meta.abstract:
                raise ImproperlyConfigured(f"The model {model.__name__} is abstract, so it cannot be registered.")
            if model in self._registry:
                raise AlreadyRegistered(f"The model {model.__name__} is already registered.")
            if model._meta.swapped:
                continue
            if options:
                options["__module__"] = __name__
                admin_base = cast(Any, admin_class)
                admin_class = cast(type[ModelAdmin], type(f"{model.__name__}Admin", (admin_base,), options))
            self._registry[model] = admin_class(model, self)
        self.clear_cache()

    def unregister(self, model_or_iterable):
        if isinstance(model_or_iterable, ModelBase):
            model_or_iterable = [model_or_iterable]
        for model in model_or_iterable:
            if model not in self._registry:
                raise NotRegistered(f"The model {model.__name__} is not registered.")
            del self._registry[model]
        self.clear_cache()

    def is_registered(self, model):
        return model in self._registry

    def get_model_admin(self, model):
        try:
            return self._registry[model]
        except KeyError as exc:
            raise NotRegistered(f"The model {model.__name__} is not registered.") from exc

    def get_registered_model_admins(self):
        return self._registry.items()

    def add_action(self, action, name=None):
        name = name or action.__name__
        self._actions[name] = action
        self._global_actions[name] = action
        self.clear_cache()

    def disable_action(self, name):
        del self._actions[name]
        self.clear_cache()

    def get_action(self, name):
        return self._global_actions[name]

    def has_permission(self, request):
        return request.user.is_active and request.user.is_staff

    def check(self, app_configs=None):
        if app_configs is None:
            app_configs = apps.get_app_configs()
        app_configs = set(app_configs)
        errors = []
        for model_admin in self._registry.values():
            if model_admin.model._meta.app_config in app_configs:
                errors.extend(model_admin.check())
        return errors

    def get_app_list(self, request, app_label=None):
        data = self.discovery_operations.list_apps(AdminRequestContext(request), app_label).data
        if isinstance(data, list):
            return [app.model_dump(mode="json") for app in data]
        return data.model_dump(mode="json")

    def each_context(self, request):
        return self.discovery_operations.site_context(AdminRequestContext(request)).data.model_dump(mode="json")

    @property
    def discovery_operations(self):
        return DiscoveryOperations(self)

    @property
    def form_operations(self):
        return FormOperations(self)

    @property
    def object_operations(self):
        return ObjectOperations()

    @property
    def changelist_operations(self):
        return ChangelistOperations()

    @property
    def autocomplete_operations(self):
        return AutocompleteOperations(self)

    @property
    def history_operations(self):
        return HistoryOperations(self)

    @property
    def mutation_operations(self):
        return MutationOperations()

    @property
    def bulk_mutation_operations(self):
        return BulkMutationOperations()

    @property
    def action_operations(self):
        return ActionOperations()

    @property
    def deletion_operations(self):
        return DeletionOperations()

    def get_site_title(self):
        return self._site_label("site_title", DEFAULT_SITE_TITLE)

    def get_site_header(self):
        return self._site_label("site_header", DEFAULT_SITE_HEADER)

    def get_site_url(self, request):
        script_name = request.META.get("SCRIPT_NAME", "")
        return script_name if self.site_url == "/" and script_name else self.site_url

    def _site_label(self, attr, default):
        value = getattr(self, attr)
        if value == default:
            return _(default)
        return str(value)
