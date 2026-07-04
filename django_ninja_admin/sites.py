import json
import re
from collections.abc import Sequence
from functools import wraps
from math import ceil
from typing import Any, cast
from weakref import WeakSet

from asgiref.sync import async_to_sync, sync_to_async
from django import forms
from django.apps import apps
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.shortcuts import get_current_site
from django.core.exceptions import (
    FieldDoesNotExist,
    ImproperlyConfigured,
    ObjectDoesNotExist,
    PermissionDenied,
    ValidationError,
)
from django.core.paginator import InvalidPage, Paginator
from django.db import router, transaction
from django.db.models.base import ModelBase
from django.forms.models import _get_foreign_key, modelformset_factory
from django.http import Http404
from django.http.multipartparser import MultiPartParserError
from django.middleware.csrf import get_token
from django.utils.functional import LazyObject
from django.utils.module_loading import import_string
from django.utils.text import capfirst
from django.utils.translation import gettext as _
from ninja import NinjaAPI, Query, Router, Status
from ninja.constants import NOT_SET
from ninja.errors import AuthenticationError, AuthorizationError, HttpError, Throttled
from ninja.errors import ValidationError as NinjaValidationError
from ninja.security import SessionAuthIsStaff
from ninja.utils import is_async_callable
from pydantic import ValidationError as PydanticValidationError

from django_ninja_admin import actions
from django_ninja_admin.admins.model import ModelAdmin
from django_ninja_admin.exceptions import (
    AdminPermissionError,
    AdminValidationError,
    AlreadyRegistered,
    DisallowedModelAdminLookup,
    DisallowedModelAdminToField,
    MissingSearchFields,
    NotRegistered,
    ProtectedDelete,
)
from django_ninja_admin.routes import AdminRoute
from django_ninja_admin.schemas import (
    AppSummary,
    AutocompleteResponse,
    ChangelistResponse,
    CsrfTokenResponse,
    ErrorResponse,
    FormResponse,
    HistoryResponse,
    JsonObjectResponse,
    Pagination,
    PermissionsResponse,
    SessionLoginPayload,
    SessionResponse,
    SiteContext,
    ViewOnSiteResponse,
)
from django_ninja_admin.utils.deletion import deletion_error_payload
from django_ninja_admin.utils.format_error import format_error
from django_ninja_admin.utils.forms import (
    _jsonish_value,
    fieldset_layout_description,
    form_errors,
    form_field_descriptions,
    form_media_description,
    formset_errors,
    model_data_for_form,
)
from django_ninja_admin.utils.lookup import (
    display_metadata_for_field,
    field_name_for_display,
    label_for_field,
    lookup_field,
)
from django_ninja_admin.utils.quote import quote, unquote
from django_ninja_admin.utils.schema_examples import (
    form_data_example,
    form_field_example_value,
    json_request_examples_extra,
    pydantic_model_example,
    relation_form_field_example_value,
    schema_type_example,
)

all_sites = WeakSet()
DEFAULT_AUTH = object()
DEFAULT_THROTTLE = object()
DEFAULT_SITE_TITLE = "Django Ninja site admin"
DEFAULT_SITE_HEADER = "Django Ninja administration"
DEFAULT_INDEX_TITLE = "Site administration"
CUSTOM_OPERATION_ID_CHARS_RE = re.compile(r"[^0-9a-zA-Z]+")
_UNSET = object()
NinjaQuery = cast(Any, Query)


class NinjaAdminSite:
    admin_class = ModelAdmin
    paginator = Paginator
    site_title = DEFAULT_SITE_TITLE
    site_header = DEFAULT_SITE_HEADER
    index_title = DEFAULT_INDEX_TITLE
    site_url = "/"
    enable_nav_sidebar = True
    empty_value_display = "-"
    include_auth = True
    history_max_per_page = 100
    autocomplete_per_page = 20
    history_throttle: Any = NOT_SET
    autocomplete_throttle: Any = NOT_SET

    def __init__(
        self,
        *,
        name="ninja_admin",
        auth=DEFAULT_AUTH,
        include_auth=True,
        history_throttle=DEFAULT_THROTTLE,
        autocomplete_throttle=DEFAULT_THROTTLE,
    ):
        self.name = name
        self.include_auth = include_auth
        self.auth: Any = SessionAuthIsStaff() if auth is DEFAULT_AUTH else auth
        self.history_throttle = (
            self.__class__.history_throttle if history_throttle is DEFAULT_THROTTLE else history_throttle
        )
        self.autocomplete_throttle = (
            self.__class__.autocomplete_throttle if autocomplete_throttle is DEFAULT_THROTTLE else autocomplete_throttle
        )
        self._registry = {}
        self._actions = {"delete_selected": actions.delete_selected}
        self._global_actions = self._actions.copy()
        self._api = None
        all_sites.add(self)
        if include_auth:
            from django_ninja_admin.admins.auth import AuthGroupAdmin, AuthUserAdmin

            self.register(get_user_model(), AuthUserAdmin)
            self.register(Group, AuthGroupAdmin)

    def __repr__(self):
        return f"{self.__class__.__name__}(name={self.name!r})"

    @property
    def actions(self):
        return self._actions.items()

    def clear_cache(self):
        self._api = None

    def register(self, model_or_iterable, admin_class=None, **options):
        admin_class = admin_class or self.admin_class
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
                admin_class = type(f"{model.__name__}Admin", (admin_class,), options)
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

    def admin_view(self, view_func):
        if is_async_callable(view_func):

            @wraps(view_func)
            async def async_inner(request, *args, **kwargs):
                has_permission = await sync_to_async(self.has_permission)(request)
                if not has_permission:
                    raise PermissionDenied
                return await view_func(request, *args, **kwargs)

            return async_inner

        @wraps(view_func)
        def inner(request, *args, **kwargs):
            if not self.has_permission(request):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return inner

    def route(
        self,
        path,
        view_func=None,
        *,
        methods=("GET",),
        response=JsonObjectResponse,
        operation_id=None,
        summary=None,
        description=None,
        tags=None,
        auth=DEFAULT_AUTH,
        throttle=NOT_SET,
        include_in_schema=True,
    ):
        def build_route(func):
            route_auth = self.auth if auth is DEFAULT_AUTH else auth
            return AdminRoute(
                path=path,
                view_func=func,
                methods=tuple(method.upper() for method in methods),
                response=response,
                operation_id=operation_id,
                summary=summary,
                description=description,
                tags=tags,
                auth=route_auth,
                throttle=throttle,
                include_in_schema=include_in_schema,
            )

        if view_func is None:
            return build_route
        return build_route(view_func)

    def get_urls(self):
        return []

    def check(self, app_configs=None):
        if app_configs is None:
            app_configs = apps.get_app_configs()
        app_configs = set(app_configs)
        errors = []
        for model_admin in self._registry.values():
            if model_admin.model._meta.app_config in app_configs:
                errors.extend(model_admin.check())
        return errors

    def _build_app_dict(self, request, label=None):
        app_dict: dict[str, dict[str, Any]] = {}
        models = {
            model: model_admin
            for model, model_admin in self._registry.items()
            if label is None or model._meta.app_label == label
        }
        for model, model_admin in models.items():
            app_label = model._meta.app_label
            has_module_perms = model_admin.has_module_permission(request)
            if not has_module_perms:
                continue
            perms = model_admin.get_model_perms(request)
            if True not in perms.values():
                continue
            model_dict = {
                "name": str(capfirst(model._meta.verbose_name_plural)),
                "object_name": model._meta.object_name,
                "app_label": app_label,
                "model_name": model._meta.model_name,
                "perms": perms,
            }
            if app_label in app_dict:
                app_dict[app_label]["models"].append(model_dict)
            else:
                app_dict[app_label] = {
                    "name": str(apps.get_app_config(app_label).verbose_name),
                    "app_label": app_label,
                    "has_module_perms": has_module_perms,
                    "models": [model_dict],
                }
        if label:
            return app_dict.get(label)
        return app_dict

    def get_app_list(self, request, app_label=None):
        app_dict = self._build_app_dict(request, app_label)
        if app_label is not None:
            if app_dict is None:
                raise Http404
            app_dict["models"].sort(key=lambda x: x["name"])
            return app_dict
        app_list = sorted(app_dict.values(), key=lambda x: x["name"].lower())
        for app in app_list:
            app["models"].sort(key=lambda x: x["name"])
        return app_list

    def each_context(self, request):
        script_name = request.META.get("SCRIPT_NAME", "")
        site_url = script_name if self.site_url == "/" and script_name else self.site_url
        return {
            "site_title": self._site_label("site_title", DEFAULT_SITE_TITLE),
            "site_header": self._site_label("site_header", DEFAULT_SITE_HEADER),
            "site_url": site_url,
            "has_permission": self.has_permission(request),
            "available_apps": self.get_app_list(request),
            "is_nav_sidebar_enabled": self.enable_nav_sidebar,
        }

    def _site_label(self, attr, default):
        value = getattr(self, attr)
        if value == default:
            return _(default)
        return str(value)

    def paginate_queryset(self, request, paginator, page_kwarg="page"):
        page_value = request.GET.get(page_kwarg) or 1
        try:
            page_number = paginator.num_pages if page_value == "last" else int(page_value)
            page = paginator.page(page_number)
            return page, page.object_list, page.has_other_pages()
        except (ValueError, InvalidPage) as exc:
            raise HttpError(404, f"Invalid page ({page_value}): {exc}") from exc

    def pagination_payload(self, paginator, page_obj):
        has_next = page_obj.has_next()
        return Pagination(
            count=paginator.count,
            num_pages=paginator.num_pages,
            page=page_obj.number,
            per_page=paginator.per_page,
            has_next=has_next,
            has_previous=page_obj.has_previous(),
            more=has_next,
        ).model_dump(mode="json")

    def visibility_filtered_pagination_payload(self, page_obj, visible_items):
        visible_count = len(visible_items)
        return Pagination(
            count=visible_count,
            num_pages=1 if visible_count else 0,
            page=page_obj.number,
            per_page=page_obj.paginator.per_page,
            has_next=False,
            has_previous=page_obj.has_previous(),
            more=False,
        ).model_dump(mode="json")

    @property
    def urls(self):
        return self.api.urls

    @property
    def api(self):
        if self._api is None:
            self._api = self._build_api()
        return self._api

    def _build_api(self):
        api = NinjaAPI(
            title=self._site_label("site_header", DEFAULT_SITE_HEADER),
            version="2.0.0",
            urls_namespace=self.name,
            auth=self.auth,
            openapi_url="/openapi.json",
            docs_url="/docs",
            docs_decorator=None if self.auth is None else self._docs_auth_decorator,
        )
        self._register_exception_handlers(api)
        router = Router(tags=["admin"])
        self._register_site_routes(router)
        self._register_custom_routes(router, self.get_urls(), default_tags=["admin"])
        for model, model_admin in self._registry.items():
            self._register_model_routes(router, model, model_admin)
        api.add_router("", router)
        return api

    def _auth_callbacks(self):
        if self.auth is None:
            return ()
        if isinstance(self.auth, Sequence):
            return tuple(self.auth)
        return (self.auth,)

    def _run_docs_authentication(self, request):
        for callback in self._auth_callbacks():
            try:
                if is_async_callable(callback) or getattr(callback, "is_async", False):
                    result = async_to_sync(callback)(request)
                else:
                    result = callback(request)
            except Exception as exc:
                return self.api.on_exception(request, exc)

            if result:
                request.auth = result
                return None
        return self.api.on_exception(request, AuthenticationError())

    def _docs_auth_decorator(self, view_func):
        @wraps(view_func)
        def inner(request, *args, **kwargs):
            error = self._run_docs_authentication(request)
            if error is not None:
                return error
            return view_func(request, *args, **kwargs)

        return inner

    def _register_custom_routes(self, router, routes, *, prefix="", default_tags=None):
        for route in routes:
            if not isinstance(route, AdminRoute):
                raise ImproperlyConfigured("Custom admin get_urls() entries must be AdminRoute instances.")
            path = self._join_route_path(prefix, route.path)
            view_func = self._custom_route_view_func(route.view_func)
            tags = route.tags or default_tags
            response = self._custom_route_response(route.response, auth=route.auth)
            response.update(self._throttle_error_responses(route.throttle))
            multi_method = len(route.methods) > 1
            for method in route.methods:
                router.add_api_operation(
                    path,
                    [method],
                    view_func,
                    auth=route.auth,
                    throttle=route.throttle,
                    response=response,
                    operation_id=self._custom_route_operation_id(
                        path,
                        method,
                        route.operation_id,
                        multi_method=multi_method,
                    ),
                    summary=route.summary,
                    description=route.description,
                    tags=tags,
                    include_in_schema=route.include_in_schema,
                )

    def _custom_route_operation_id(self, path, method, operation_id=None, *, multi_method=False):
        if operation_id is not None:
            return f"{operation_id}_{method.lower()}" if multi_method else operation_id
        normalized_path = path.strip("/").replace("{", "").replace("}", "") or "root"
        normalized_path = CUSTOM_OPERATION_ID_CHARS_RE.sub("_", normalized_path).strip("_").lower()
        return f"custom_{method.lower()}_{normalized_path}"

    def _custom_route_response(self, response, *, auth):
        response_map = response.copy() if isinstance(response, dict) else {200: response}
        if auth is not None:
            response_map.setdefault(401, ErrorResponse)
        for status_code in (400, 403, 404, 422):
            response_map.setdefault(status_code, ErrorResponse)
        return response_map

    def _site_route_response(self, success_response, *, errors=()):
        response_map = {200: success_response}
        response_map.update(self._auth_error_responses(include_forbidden=True))
        for status_code in errors:
            response_map[status_code] = ErrorResponse
        return response_map

    def _custom_hook_responses(self, schema, statuses):
        if schema is None:
            return {}
        if isinstance(schema, dict):
            return schema
        return dict.fromkeys(statuses, schema)

    def _auth_error_responses(self, *, include_forbidden=False):
        if self.auth is None:
            return {}
        response_map = {401: ErrorResponse}
        if include_forbidden:
            response_map[403] = ErrorResponse
        return response_map

    def _throttle_error_responses(self, throttle):
        return {429: ErrorResponse} if throttle is not NOT_SET else {}

    def _custom_route_view_func(self, view_func):
        if not (hasattr(view_func, "__self__") and hasattr(view_func, "__func__")):
            return view_func

        if is_async_callable(view_func):

            @wraps(view_func)
            async def async_inner(request, *args, **kwargs):
                return await view_func(request, *args, **kwargs)

            return async_inner

        @wraps(view_func)
        def inner(request, *args, **kwargs):
            return view_func(request, *args, **kwargs)

        return inner

    def _join_route_path(self, prefix, path):
        prefix = prefix.rstrip("/")
        path = path if path.startswith("/") else f"/{path}"
        return f"{prefix}{path}" if prefix else path

    def _register_exception_handlers(self, api):
        def error_response(request, message, status, param="non_field_errors"):
            return api.create_response(
                request,
                {"errors": [{"message": message, "param": param}]},
                status=status,
            )

        @api.exception_handler(AdminValidationError)
        def admin_validation_error(request, exc):
            return api.create_response(request, {"errors": exc.errors}, status=exc.status_code)

        @api.exception_handler(AdminPermissionError)
        def admin_permission_error(request, exc):
            return api.create_response(request, {"errors": exc.errors}, status=exc.status_code)

        @api.exception_handler(ProtectedDelete)
        def protected_delete(request, exc):
            return error_response(request, str(exc), 409)

        def permission_denied(request, exc):
            return error_response(request, _("Permission denied."), 403)

        api.add_exception_handler(PermissionDenied, permission_denied)
        api.add_exception_handler(AuthorizationError, permission_denied)

        def not_authenticated(request, exc):
            return error_response(request, _("Authentication required."), 401)

        api.add_exception_handler(AuthenticationError, not_authenticated)

        def throttled(request, exc):
            response = error_response(request, _("Too many requests."), 429)
            wait = getattr(exc, "wait", None)
            if wait is not None:
                response["Retry-After"] = str(ceil(wait))
            return response

        api.add_exception_handler(Throttled, throttled)

        def not_found(request, exc):
            return error_response(request, _("Not found."), 404)

        api.add_exception_handler(Http404, not_found)
        api.add_exception_handler(NotRegistered, not_found)

        def bad_request(request, exc):
            return api.create_response(request, {"errors": format_error(exc)}, status=400)

        api.add_exception_handler(DisallowedModelAdminLookup, bad_request)
        api.add_exception_handler(DisallowedModelAdminToField, bad_request)
        api.add_exception_handler(ValidationError, bad_request)
        api.add_exception_handler(PydanticValidationError, bad_request)

        def request_validation_error(request, exc):
            errors = []
            raw_errors = getattr(exc, "errors", None)
            raw_errors = raw_errors() if callable(raw_errors) else raw_errors
            raw_errors = raw_errors if isinstance(raw_errors, list) else [raw_errors or str(exc)]
            for error in raw_errors:
                if isinstance(error, dict):
                    location = self._request_validation_param(error)
                    errors.append(
                        {
                            "message": error.get("msg", str(error)),
                            "param": location or "body",
                        }
                    )
                else:
                    errors.append({"message": str(error), "param": "body"})
            return api.create_response(request, {"errors": errors}, status=422)

        api.add_exception_handler(NinjaValidationError, request_validation_error)

        @api.exception_handler(MissingSearchFields)
        def missing_search_fields(request, exc):
            return error_response(request, _("Missing search_fields."), 409, param="search_fields")

    def _request_validation_param(self, error):
        if error.get("type") == "union_tag_invalid":
            discriminator = (error.get("ctx") or {}).get("discriminator")
            if discriminator:
                return str(discriminator).strip("'\"")
        location_parts = [str(part) for part in error.get("loc", []) if part not in {"body", "payload"}]
        if len(location_parts) > 1 and location_parts[1] in {"action", "selected_ids", "select_across", "data"}:
            location_parts = location_parts[1:]
        return ".".join(location_parts)

    def _model_admin_method_overridden(self, model_admin, method_name):
        method = getattr(model_admin, method_name)
        base_method = getattr(ModelAdmin, method_name)
        return getattr(method, "__func__", method) is not base_method

    def _uses_object_visibility_permissions(self, model_admin):
        return self._model_admin_method_overridden(
            model_admin,
            "has_view_permission",
        ) or self._model_admin_method_overridden(
            model_admin,
            "has_change_permission",
        )

    def _history_requires_object_visibility_filter(self, content_type_ids):
        for content_type in ContentType.objects.filter(pk__in=content_type_ids):
            model_class = content_type.model_class()
            if model_class is None:
                continue
            try:
                model_admin = self.get_model_admin(model_class)
            except NotRegistered:
                continue
            if self._uses_object_visibility_permissions(model_admin):
                return True
        return False

    def _session_state(self, request):
        user = request.user
        return {
            "is_authenticated": user.is_authenticated,
            "is_active": getattr(user, "is_active", False),
            "is_staff": getattr(user, "is_staff", False),
            "is_superuser": getattr(user, "is_superuser", False),
            "has_permission": self.has_permission(request),
            "csrf_token": get_token(request),
        }

    def _history_content_type_ids(self, request, *, app_label=None, model_name=None):
        if model_name and not app_label:
            raise AdminValidationError(
                [{"message": _("app_label is required when model is provided."), "param": "app_label"}]
            )
        if app_label and model_name:
            try:
                model = apps.get_model(app_label, model_name)
                model_admin = self.get_model_admin(model)
            except (LookupError, NotRegistered) as exc:
                raise Http404 from exc
            if not model_admin.has_view_or_change_permission(request):
                raise PermissionDenied
            return [ContentType.objects.get_for_model(model, for_concrete_model=False).pk]
        registered_models = [
            model
            for model, model_admin in self._registry.items()
            if (app_label is None or model._meta.app_label == app_label)
            and model_admin.has_view_or_change_permission(request)
        ]
        if app_label is not None and not any(model._meta.app_label == app_label for model in self._registry):
            raise Http404
        return [
            content_type.pk
            for content_type in ContentType.objects.get_for_models(
                *registered_models,
                for_concrete_models=False,
            ).values()
        ]

    def _history_object_links(self, request, item, model_class, opts, obj=_UNSET):
        if model_class is None or opts is None or not item.object_id:
            return {"detail_url": None, "change_form_url": None}
        try:
            model_admin = self.get_model_admin(model_class)
        except NotRegistered:
            return {"detail_url": None, "change_form_url": None}
        if not self._uses_object_visibility_permissions(model_admin):
            if not model_admin.has_view_or_change_permission(request):
                return {"detail_url": None, "change_form_url": None}
            return self._history_object_link_urls(request, item, opts)
        if obj is _UNSET:
            try:
                obj = model_admin.get_object(request, item.object_id)
            except (LookupError, ValidationError, ValueError):
                return {"detail_url": None, "change_form_url": None}
        if obj is None:
            return {"detail_url": None, "change_form_url": None}
        if not model_admin.has_view_permission(request, obj) and not model_admin.has_change_permission(request, obj):
            return {"detail_url": None, "change_form_url": None}
        return self._history_object_link_urls(request, item, opts)

    def _history_object_link_urls(self, request, item, opts):
        admin_base_path = request.path.rstrip("/")
        if admin_base_path.endswith("/history"):
            admin_base_path = admin_base_path[: -len("/history")]
        object_url = f"{admin_base_path}/{opts.app_label}/{opts.model_name}/{quote(item.object_id)}"
        return {"detail_url": object_url, "change_form_url": f"{object_url}/form"}

    def _history_item_is_visible(self, request, item):
        visible, _obj = self._history_item_visibility(request, item)
        return visible

    def _history_item_visibility(self, request, item):
        content_type = item.content_type
        model_class = content_type.model_class() if content_type is not None else None
        if model_class is None or not item.object_id:
            return True, None
        try:
            model_admin = self.get_model_admin(model_class)
            obj = model_admin.get_object(request, item.object_id)
        except (LookupError, NotRegistered, ValidationError, ValueError):
            return True, None
        if obj is None:
            return True, None
        visible = model_admin.has_view_permission(request, obj) or model_admin.has_change_permission(request, obj)
        return visible, obj

    def _register_site_routes(self, router):
        site = self
        auth_errors = site._auth_error_responses()

        @router.get(
            "/csrf",
            auth=None,
            response={200: CsrfTokenResponse},
            operation_id="admin_csrf",
        )
        def csrf(request):
            return {"csrf_token": get_token(request)}

        @router.post(
            "/login",
            auth=None,
            response={
                200: SessionResponse,
                400: ErrorResponse,
                403: ErrorResponse,
                422: ErrorResponse,
            },
            operation_id="admin_login",
        )
        def login(request, payload: SessionLoginPayload):
            user = authenticate(request, username=payload.username, password=payload.password)
            if user is None:
                raise AdminValidationError([{"message": _("Invalid username or password."), "param": "username"}])
            request.user = user
            if not site.has_permission(request):
                raise PermissionDenied
            auth_login(request, user)
            request.user = user
            return site._session_state(request)

        @router.post(
            "/logout",
            auth=site.auth,
            response={
                200: SessionResponse,
                **auth_errors,
                403: ErrorResponse,
                422: ErrorResponse,
            },
            operation_id="admin_logout",
        )
        def logout(request):
            auth_logout(request)
            request.user = AnonymousUser()
            return site._session_state(request)

        @router.get(
            "/apps",
            response=site._site_route_response(list[AppSummary]),
            operation_id="admin_list_apps",
        )
        def list_apps(request):
            return site.get_app_list(request)

        @router.get(
            "/apps/{app_label}",
            response=site._site_route_response(AppSummary, errors=(404,)),
            operation_id="admin_get_app",
        )
        def get_app(request, app_label: str):
            return site.get_app_list(request, app_label)

        @router.get(
            "/context",
            response=site._site_route_response(SiteContext),
            operation_id="admin_context",
        )
        def context(request):
            return site.each_context(request)

        @router.get(
            "/permissions",
            response=site._site_route_response(PermissionsResponse),
            operation_id="admin_permissions",
        )
        def permissions(request):
            user = request.user
            model_permissions = [model for app in site.get_app_list(request) for model in app["models"]]
            return {
                "is_authenticated": user.is_authenticated,
                "is_active": user.is_active,
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
                "has_permission": site.has_permission(request),
                "models": model_permissions,
            }

        @router.get(
            "/history",
            response={
                200: HistoryResponse,
                **auth_errors,
                400: ErrorResponse,
                403: ErrorResponse,
                404: ErrorResponse,
                **site._throttle_error_responses(site.history_throttle),
                422: ErrorResponse,
            },
            throttle=site.history_throttle,
            operation_id="admin_history",
        )
        def history(
            request,
            app_label: str | None = None,
            model: str | None = None,
            object_id: str | None = None,
            action_flag: int | None = None,
            o: str = "-action_time",
            page: int = 1,
            per_page: int = 20,
        ):
            from django_ninja_admin.models import ACTION_FLAG_CHOICES, LogEntry

            if o not in {"action_time", "-action_time"}:
                raise AdminValidationError([{"message": _("Invalid ordering provided."), "param": "o"}])
            if action_flag is not None and action_flag not in dict(ACTION_FLAG_CHOICES):
                raise AdminValidationError([{"message": _("Invalid action flag provided."), "param": "action_flag"}])
            if per_page < 1:
                raise AdminValidationError([{"message": _("Invalid page size."), "param": "per_page"}])
            if per_page > site.history_max_per_page:
                raise AdminValidationError(
                    [
                        {
                            "message": _("Page size cannot exceed %(max_page_size)s.")
                            % {"max_page_size": site.history_max_per_page},
                            "param": "per_page",
                        }
                    ]
                )
            content_type_ids = site._history_content_type_ids(
                request,
                app_label=app_label,
                model_name=model,
            )
            qs = (
                LogEntry.objects.filter(
                    content_type_id__in=content_type_ids,
                )
                .order_by(o)
                .select_related("content_type")
            )
            if object_id is not None:
                qs = qs.filter(object_id=object_id)
            if action_flag is not None:
                qs = qs.filter(action_flag=action_flag)
            use_visibility_filter = site._history_requires_object_visibility_filter(content_type_ids)
            paginator = site.paginator(qs, per_page)
            try:
                page_obj = paginator.page(page)
            except InvalidPage as exc:
                raise Http404 from exc
            page_items = list(page_obj.object_list)
            visible_objects = {}
            if use_visibility_filter:
                visible_items = []
                for item in page_items:
                    visible, obj = site._history_item_visibility(request, item)
                    if visible:
                        visible_items.append(item)
                        visible_objects[item.pk] = obj
                page_items = visible_items
            results = []
            for item in page_items:
                try:
                    message = json.loads(item.change_message or "[]")
                except json.JSONDecodeError:
                    message = item.change_message
                content_type = item.content_type
                model_class = content_type.model_class() if content_type is not None else None
                opts = model_class._meta if model_class is not None else None
                object_links = site._history_object_links(
                    request,
                    item,
                    model_class,
                    opts,
                    obj=visible_objects.get(item.pk, _UNSET),
                )
                results.append(
                    {
                        "id": _jsonish_value(item.pk),
                        "action_time": item.action_time,
                        "user_id": _jsonish_value(item.user_id),
                        "content_type_id": _jsonish_value(item.content_type_id),
                        "model": f"{opts.app_label}.{opts.model_name}" if opts is not None else None,
                        "app_label": opts.app_label if opts is not None else None,
                        "model_name": opts.model_name if opts is not None else None,
                        "model_verbose_name": str(opts.verbose_name) if opts is not None else None,
                        "model_verbose_name_plural": str(opts.verbose_name_plural) if opts is not None else None,
                        "object_id": item.object_id,
                        "object_repr": item.object_repr,
                        **object_links,
                        "action_flag": item.action_flag,
                        "change_message": _jsonish_value(message),
                        "change_message_text": item.get_change_message(),
                    }
                )
            pagination = (
                site.visibility_filtered_pagination_payload(page_obj, page_items)
                if use_visibility_filter
                else site.pagination_payload(paginator, page_obj)
            )
            return {
                "pagination": pagination,
                "results": results,
            }

        @router.get(
            "/autocomplete",
            response={
                200: AutocompleteResponse,
                **auth_errors,
                403: ErrorResponse,
                404: ErrorResponse,
                409: ErrorResponse,
                **site._throttle_error_responses(site.autocomplete_throttle),
                422: ErrorResponse,
            },
            throttle=site.autocomplete_throttle,
            operation_id="admin_autocomplete",
        )
        def autocomplete(
            request,
            app_label: str,
            model_name: str,
            field_name: str,
            term: str = "",
            page: int = 1,
        ):
            try:
                source_model = apps.get_model(app_label, model_name)
                source_admin = site.get_model_admin(source_model)
                source_field = source_model._meta.get_field(field_name)
                remote_model = source_field.remote_field.model
                model_admin = site.get_model_admin(remote_model)
            except (AttributeError, LookupError, NotRegistered) as exc:
                raise Http404 from exc
            if field_name not in source_admin.get_autocomplete_fields(request):
                raise Http404
            if not source_admin.has_view_or_change_permission(request):
                raise PermissionDenied
            if not model_admin.get_search_fields(request):
                raise MissingSearchFields
            if hasattr(source_field.remote_field, "get_related_field"):
                to_field_name = source_field.remote_field.get_related_field().attname
            else:
                to_field_name = remote_model._meta.pk.attname
            to_field_name = remote_model._meta.get_field(to_field_name).attname
            if not model_admin.to_field_allowed(request, to_field_name):
                raise PermissionDenied
            if not model_admin.has_view_permission(request):
                raise PermissionDenied
            qs = model_admin.get_queryset(request).complex_filter(source_field.get_limit_choices_to())
            qs, use_distinct = model_admin.get_search_results(request, qs, term)
            if use_distinct:
                qs = qs.distinct()
            if not qs.ordered:
                qs = qs.order_by(remote_model._meta.pk.name)
            per_page = site.autocomplete_per_page
            use_visibility_filter = site._model_admin_method_overridden(model_admin, "has_view_permission")
            paginator = model_admin.get_paginator(request, qs, per_page)
            try:
                page_obj = paginator.page(page)
            except InvalidPage as exc:
                raise Http404 from exc
            page_items = list(page_obj.object_list)
            if use_visibility_filter:
                page_items = [obj for obj in page_items if model_admin.has_view_permission(request, obj)]
            pagination = (
                site.visibility_filtered_pagination_payload(page_obj, page_items)
                if use_visibility_filter
                else site.pagination_payload(paginator, page_obj)
            )
            return {
                "results": [{"id": str(getattr(obj, to_field_name)), "text": str(obj)} for obj in page_items],
                "pagination": pagination,
            }

        @router.get(
            "/view-on-site/{content_type_id}/{object_id}",
            response={
                200: ViewOnSiteResponse,
                **auth_errors,
                403: ErrorResponse,
                404: ErrorResponse,
                409: ErrorResponse,
                422: ErrorResponse,
            },
            operation_id="admin_view_on_site",
        )
        def view_on_site(request, content_type_id: int, object_id: str):
            try:
                content_type = ContentType.objects.get(pk=content_type_id)
                model = content_type.model_class()
                if model is None:
                    raise Http404
                model_admin = site.get_model_admin(model)
                obj = model_admin.get_object(request, unquote(object_id))
                if obj is None:
                    raise Http404
            except (ObjectDoesNotExist, ValueError, ValidationError, NotRegistered) as exc:
                raise Http404 from exc
            if not model_admin.has_view_or_change_permission(request, obj):
                raise PermissionDenied
            if callable(model_admin.view_on_site):
                absurl = model_admin.view_on_site(obj)
            elif model_admin.view_on_site and hasattr(obj, "get_absolute_url"):
                absurl = obj.get_absolute_url()
            else:
                absurl = None
            if not absurl:
                return Status(
                    409,
                    {"errors": [{"message": _("Object has no get_absolute_url()."), "param": "object_id"}]},
                )
            if absurl.startswith(("http://", "https://", "//")):
                return {"url": absurl}
            try:
                object_domain = get_current_site(request).domain
            except ObjectDoesNotExist:
                object_domain = request.get_host()
            return {"url": f"{request.scheme}://{object_domain}{absurl}"}

    def _register_model_routes(self, router, model, model_admin):
        site = self
        app_label = model._meta.app_label
        model_name = model._meta.model_name
        prefix = f"/{app_label}/{model_name}"
        tags = [f"{app_label}.{model_name}"]
        auth_errors = site._auth_error_responses()
        create_payload_schema = model_admin.get_mutation_payload_schema(None, change=False, partial=False)
        update_payload_schema = model_admin.get_mutation_payload_schema(None, change=True, partial=True)
        replace_payload_schema = model_admin.get_mutation_payload_schema(None, change=True, partial=False)
        mutation_response_schema = model_admin.get_mutation_response_schema(None)
        bulk_payload_schema = model_admin.get_bulk_payload_schema(None)
        bulk_response_schema = model_admin.get_bulk_response_schema(None)
        action_payload_schema = model_admin.get_action_payload_schema(None)
        action_response_schema = model_admin.get_action_response_schema(None)
        changelist_throttle = model_admin.get_changelist_throttle(None)
        add_hook_responses = site._custom_hook_responses(model_admin.get_response_add_schema(None), (200, 202))
        change_hook_responses = site._custom_hook_responses(model_admin.get_response_change_schema(None), (200, 202))
        delete_hook_responses = site._custom_hook_responses(model_admin.get_response_delete_schema(None), (200, 202))
        action_response = {
            200: action_response_schema,
            202: action_response_schema,
            204: None,
            **auth_errors,
            400: ErrorResponse,
            403: ErrorResponse,
            409: ErrorResponse,
            422: ErrorResponse,
        }
        create_file_fields = site._file_form_field_names(model_admin, change=False)
        create_required_file_fields = site._required_file_form_field_names(model_admin, change=False)
        change_file_fields = site._file_form_field_names(model_admin, change=True)
        create_response = {
            201: mutation_response_schema,
            **add_hook_responses,
            204: None,
            **auth_errors,
            400: ErrorResponse,
            403: ErrorResponse,
            422: ErrorResponse,
        }
        change_response = {
            200: mutation_response_schema,
            **change_hook_responses,
            204: None,
            **auth_errors,
            400: ErrorResponse,
            403: ErrorResponse,
            404: ErrorResponse,
            422: ErrorResponse,
        }

        @router.get(
            prefix,
            response={
                200: ChangelistResponse,
                **auth_errors,
                400: ErrorResponse,
                403: ErrorResponse,
                404: ErrorResponse,
                **site._throttle_error_responses(changelist_throttle),
                422: ErrorResponse,
            },
            throttle=changelist_throttle,
            tags=tags,
            operation_id=f"{app_label}_{model_name}_list",
            description=(
                "List registered model objects. Supports search (`q`), ordering (`o` with 1-based column "
                "indexes), pagination (`p`/`page`, `pp`, `all`), facets (`_facets`), alternate row identity "
                "(`_to_field`), and Django-style field lookup filters such as `field__in`, `field__isnull`, "
                "and date hierarchy parameters like `created_at__year`."
            ),
        )
        def changelist(
            request,
            q: str | None = NinjaQuery(None, description="Search term matched against the admin search fields."),
            o: str | None = NinjaQuery(
                None,
                description="Ordering token list using 1-based changelist column indexes, e.g. `1,-2`.",
            ),
            p: str | None = NinjaQuery(None, description="1-based page number, or `last`."),
            page: str | None = NinjaQuery(None, description="Legacy alias for `p`; generated links use `p`."),
            pp: int | None = NinjaQuery(None, description="Page size override."),
            all_: bool | None = NinjaQuery(
                None,
                alias="all",
                description="Show all rows when allowed by the admin.",
            ),
            facets: bool | None = NinjaQuery(None, alias="_facets", description="Enable optional facet counts."),
            to_field: str | None = NinjaQuery(
                None,
                alias="_to_field",
                description="Use an allowed alternate object id field.",
            ),
        ):
            return site._changelist_response(request, model_admin)

        @router.get(
            f"{prefix}/form",
            response={200: FormResponse, **auth_errors, 403: ErrorResponse},
            tags=tags,
            operation_id=f"{app_label}_{model_name}_add_form",
        )
        def add_form(request):
            if not model_admin.has_add_permission(request):
                raise PermissionDenied
            return site._form_response(request, model_admin, None)

        @router.post(
            prefix,
            response=create_response,
            tags=tags,
            operation_id=f"{app_label}_{model_name}_create",
            openapi_extra=json_request_examples_extra(
                create=site._mutation_payload_example(model_admin, change=False, partial=False)
            ),
        )
        def create(request, payload: create_payload_schema):
            return site._create_object(request, model_admin, payload)

        if create_file_fields:

            @router.post(
                f"{prefix}/multipart",
                response=create_response,
                tags=tags,
                operation_id=f"{app_label}_{model_name}_create_multipart",
                openapi_extra=site._multipart_openapi_extra(
                    create_payload_schema,
                    create_file_fields,
                    required_data=True,
                    required_file_fields=create_required_file_fields,
                ),
            )
            def create_multipart(request):
                payload = site._multipart_mutation_payload(request, create_payload_schema, create_file_fields)
                form_class = model_admin.get_form_class(request, None, change=False)
                return site._create_object(
                    request,
                    model_admin,
                    payload,
                    files=site._multipart_form_files(request, form_class),
                )

        @router.post(
            f"{prefix}/actions",
            response=action_response,
            tags=tags,
            operation_id=f"{app_label}_{model_name}_action",
            openapi_extra=json_request_examples_extra(
                action=site._action_payload_example(model_admin),
            ),
        )
        def actions_view(request, payload: action_payload_schema):
            if not model_admin.has_view_or_change_permission(request):
                raise PermissionDenied
            cl_queryset = site._filtered_queryset(request, model_admin)
            return model_admin.response_action(request, cl_queryset, payload)

        @router.put(
            f"{prefix}/bulk",
            response={
                200: bulk_response_schema,
                **auth_errors,
                400: ErrorResponse,
                403: ErrorResponse,
                422: ErrorResponse,
            },
            tags=tags,
            operation_id=f"{app_label}_{model_name}_bulk_update",
            openapi_extra=json_request_examples_extra(
                bulk_update=site._bulk_payload_example(model_admin),
            ),
        )
        def bulk_update(request, payload: bulk_payload_schema):
            if not model_admin.has_change_permission(request):
                raise PermissionDenied
            changelist = model_admin.get_changelist_instance(request)
            return site._bulk_update(
                request,
                model_admin,
                payload,
                queryset=changelist.queryset,
                object_id_field=changelist.object_id_field,
            )

        self._register_custom_routes(
            router,
            model_admin.get_urls(),
            prefix=prefix,
            default_tags=tags,
        )

        @router.get(
            f"{prefix}/{{object_id}}",
            response={
                200: model_admin.get_output_schema(None),
                **auth_errors,
                400: ErrorResponse,
                403: ErrorResponse,
                404: ErrorResponse,
            },
            tags=tags,
            operation_id=f"{app_label}_{model_name}_detail",
        )
        def detail(request, object_id: str, to_field: str | None = NinjaQuery(None, alias="_to_field")):
            obj = site._get_object_or_404(request, model_admin, object_id, to_field)
            if not model_admin.has_view_or_change_permission(request, obj):
                raise PermissionDenied
            return model_admin.serialize_object(obj, request)

        @router.get(
            f"{prefix}/{{object_id}}/form",
            response={
                200: FormResponse,
                **auth_errors,
                400: ErrorResponse,
                403: ErrorResponse,
                404: ErrorResponse,
            },
            tags=tags,
            operation_id=f"{app_label}_{model_name}_change_form",
        )
        def change_form(request, object_id: str, to_field: str | None = NinjaQuery(None, alias="_to_field")):
            obj = site._get_object_or_404(request, model_admin, object_id, to_field)
            if not model_admin.has_view_or_change_permission(request, obj):
                raise PermissionDenied
            return site._form_response(request, model_admin, obj)

        @router.patch(
            f"{prefix}/{{object_id}}",
            response=change_response,
            tags=tags,
            operation_id=f"{app_label}_{model_name}_partial_update",
            openapi_extra=json_request_examples_extra(
                partial_update=site._mutation_payload_example(model_admin, change=True, partial=True)
            ),
        )
        def update(
            request,
            object_id: str,
            payload: update_payload_schema,
            to_field: str | None = NinjaQuery(None, alias="_to_field"),
        ):
            return site._update_object(request, model_admin, object_id, payload, partial=True, to_field=to_field)

        @router.put(
            f"{prefix}/{{object_id}}",
            response=change_response,
            tags=tags,
            operation_id=f"{app_label}_{model_name}_update",
            openapi_extra=json_request_examples_extra(
                update=site._mutation_payload_example(model_admin, change=True, partial=False)
            ),
        )
        def replace(
            request,
            object_id: str,
            payload: replace_payload_schema,
            to_field: str | None = NinjaQuery(None, alias="_to_field"),
        ):
            return site._update_object(request, model_admin, object_id, payload, partial=False, to_field=to_field)

        if change_file_fields:

            @router.patch(
                f"{prefix}/{{object_id}}/multipart",
                response=change_response,
                tags=tags,
                operation_id=f"{app_label}_{model_name}_partial_update_multipart",
                openapi_extra=site._multipart_openapi_extra(
                    update_payload_schema,
                    change_file_fields,
                    required_data=False,
                ),
            )
            def update_multipart(
                request,
                object_id: str,
                to_field: str | None = NinjaQuery(None, alias="_to_field"),
            ):
                obj = site._get_object_or_404(request, model_admin, object_id, to_field)
                form_class = model_admin.get_form_class(request, obj, change=True)
                payload = site._multipart_mutation_payload(request, update_payload_schema, change_file_fields)
                return site._update_object(
                    request,
                    model_admin,
                    object_id,
                    payload,
                    partial=True,
                    files=site._multipart_form_files(request, form_class),
                    obj=obj,
                )

            @router.put(
                f"{prefix}/{{object_id}}/multipart",
                response=change_response,
                tags=tags,
                operation_id=f"{app_label}_{model_name}_update_multipart",
                openapi_extra=site._multipart_openapi_extra(
                    replace_payload_schema,
                    change_file_fields,
                    required_data=True,
                ),
            )
            def replace_multipart(
                request,
                object_id: str,
                to_field: str | None = NinjaQuery(None, alias="_to_field"),
            ):
                obj = site._get_object_or_404(request, model_admin, object_id, to_field)
                form_class = model_admin.get_form_class(request, obj, change=True)
                payload = site._multipart_mutation_payload(request, replace_payload_schema, change_file_fields)
                return site._update_object(
                    request,
                    model_admin,
                    object_id,
                    payload,
                    partial=False,
                    files=site._multipart_form_files(request, form_class),
                    obj=obj,
                )

        @router.delete(
            f"{prefix}/{{object_id}}",
            response={
                **delete_hook_responses,
                204: None,
                **auth_errors,
                400: ErrorResponse,
                403: ErrorResponse,
                404: ErrorResponse,
                409: ErrorResponse,
            },
            tags=tags,
            operation_id=f"{app_label}_{model_name}_delete",
        )
        def delete(request, object_id: str, to_field: str | None = NinjaQuery(None, alias="_to_field")):
            obj = site._get_object_or_404(request, model_admin, object_id, to_field)
            if not model_admin.has_delete_permission(request, obj):
                raise PermissionDenied
            deleted_objects, model_count, perms_needed, protected = model_admin.get_deleted_objects([obj], request)
            if protected:
                return Status(
                    409,
                    deletion_error_payload(
                        _("Cannot delete protected objects."),
                        deleted_objects=deleted_objects,
                        protected=protected,
                        model_count=model_count,
                    ),
                )
            if perms_needed:
                return Status(
                    403,
                    deletion_error_payload(
                        _("Permission denied."),
                        deleted_objects=deleted_objects,
                        perms_needed=perms_needed,
                        model_count=model_count,
                    ),
                )
            obj_display = str(obj)
            obj_id = str(obj.pk)
            with transaction.atomic(using=router_db_for_write(model_admin.model)):
                model_admin.log_deletion(request, [obj])
                model_admin.delete_model(request, obj)
            response = model_admin.response_delete(request, obj_display, obj_id)
            if response is not None:
                if isinstance(response, Status):
                    return response
                return Status(200, response)
            return Status(204, None)

    def _get_object_or_404(self, request, model_admin, object_id, to_field=None):
        if to_field and not model_admin.to_field_allowed(request, to_field):
            raise AdminValidationError(
                [
                    {
                        "message": _("The field '%(field)s' cannot be referenced.") % {"field": to_field},
                        "param": "_to_field",
                    }
                ]
            )
        obj = model_admin.get_object(request, unquote(object_id), to_field)
        if obj is None:
            raise Http404
        return obj

    def _filtered_queryset(self, request, model_admin):
        return model_admin.get_changelist_instance(request).queryset

    def _changelist_response(self, request, model_admin):
        changelist = model_admin.get_changelist_instance(request)
        list_display = changelist.list_display
        ordering_field_columns = {field: int(column) for field, column in changelist.ordering_field_columns.items()}
        columns = [
            {
                "field": field_name_for_display(field),
                "header_name": label_for_field(field, model_admin.model, model_admin),
                "display_link": self._display_field_in(field, changelist.list_display_links or ()),
                **display_metadata_for_field(field, model_admin.model, model_admin),
                "sortable": field in changelist.ordering_field_columns,
                "ordering_field": changelist.get_ordering_field(field),
                "ordering_index": ordering_field_columns.get(field),
                **changelist.column_sort_query_strings(field),
            }
            for field in list_display
        ]
        columns_by_field = {column["field"]: column for column in columns}
        rows = []
        empty_value = model_admin.get_empty_value_display()
        result_start_index = changelist.page.start_index()
        for index, obj in enumerate(changelist.result_list):
            cells = {}
            cell_metadata = {}
            for field in list_display:
                field_key = field_name_for_display(field)
                raw_value = lookup_field(field, obj, model_admin)
                value = _jsonish_value(raw_value)
                display_metadata = display_metadata_for_field(field, model_admin.model, model_admin)
                field_empty_value = display_metadata["empty_value_display"] or empty_value
                is_empty = raw_value in (None, "")
                display_value = field_empty_value if is_empty else value
                cells[field_key] = display_value
                column = columns_by_field[field_key]
                cell_metadata[field_key] = {
                    "field": field_key,
                    "header_name": column["header_name"],
                    "value": value,
                    "display_value": display_value,
                    "empty": is_empty,
                    "boolean": column["boolean"],
                    "display_link": column["display_link"],
                    "sortable": column["sortable"],
                    "ordering_field": column["ordering_field"],
                    "editable": field_key in model_admin.list_editable,
                    "empty_value_display": field_empty_value,
                }
            object_id = _jsonish_value(changelist.object_id_for(obj))
            rows.append(
                {
                    "id": object_id,
                    "index": index,
                    "result_index": result_start_index + index,
                    "cells": cells,
                    "cell_metadata": cell_metadata,
                    **self._changelist_row_metadata(request, model_admin, obj, object_id, changelist.to_field),
                }
            )
        action_form = [
            {
                "name": "action",
                "type": "ChoiceField",
                "attrs": {
                    "required": True,
                    "choices": [
                        (item["action"], str(item["description"])) for item in model_admin.get_action_choices(request)
                    ],
                },
            },
            {"name": "selected_ids", "type": "MultipleChoiceField", "attrs": {"required": False}},
            {"name": "select_across", "type": "BooleanField", "attrs": {"required": False}},
        ]
        list_editing_formset = []
        list_editing_rows = []
        list_editing_formset_prefix = None
        list_editing_management_form = []
        list_editing_total_form_count = None
        list_editing_initial_form_count = None
        if model_admin.list_editable:
            form_class = model_admin.get_changelist_form_class(request)
            formset_class = modelformset_factory(model_admin.model, form=form_class, extra=0)
            page_pks = [obj.pk for obj in changelist.result_list]
            formset_queryset = model_admin.model._default_manager.filter(pk__in=page_pks)
            formset = formset_class(queryset=formset_queryset)
            list_editing_formset_prefix = formset.prefix
            list_editing_management_form = form_field_descriptions(
                formset.management_form.__class__,
                request=request,
                form=formset.management_form,
            )
            list_editing_total_form_count = formset.total_form_count()
            list_editing_initial_form_count = formset.initial_form_count()
            for index, obj in enumerate(changelist.result_list):
                object_id = _jsonish_value(changelist.object_id_for(obj))
                form = form_class(instance=obj, prefix=f"{formset.prefix}-{index}")
                field_descriptions = model_admin.get_changelist_form_fields_description(request, obj, form=form)
                editable_fields = [field for field in field_descriptions if field["name"] in model_admin.list_editable]
                list_editing_formset.append(editable_fields)
                list_editing_rows.append(
                    {
                        "index": index,
                        "pk": object_id,
                        "pk_name": changelist.object_id_field,
                        "form_prefix": form.prefix,
                        "empty_permitted": form.empty_permitted,
                        "fields": editable_fields,
                    }
                )
        model_field_names = [field for field in list_display if self._model_has_field(model_admin.model, field)]
        display_ordering_field_columns = {
            field_name_for_display(field): column for field, column in ordering_field_columns.items()
        }
        payload = {
            "columns": columns,
            "rows": rows,
            "config": {
                "full_count": changelist.full_result_count,
                "result_count": changelist.result_count,
                "page_result_count": len(changelist.result_list),
                "result_start_index": changelist.page.start_index(),
                "result_end_index": changelist.page.end_index(),
                "page_count": changelist.paginator.num_pages,
                "page": changelist.page_num,
                "per_page": changelist.per_page,
                "pagination": {
                    "count": changelist.result_count,
                    "num_pages": changelist.paginator.num_pages,
                    "page": changelist.page_num,
                    "per_page": changelist.per_page,
                    "has_next": changelist.page.has_next(),
                    "has_previous": changelist.page.has_previous(),
                    "more": changelist.page.has_next(),
                },
                "has_next": changelist.page.has_next(),
                "has_previous": changelist.page.has_previous(),
                "multi_page": changelist.multi_page,
                "pagination_required": changelist.pagination_required,
                "page_range": changelist.get_page_range(),
                "page_choices": changelist.get_page_choices(),
                **changelist.pagination_query_strings(),
                **changelist.show_all_query_strings(),
                "show_all": changelist.show_all,
                "can_show_all": changelist.can_show_all_results,
                "show_facets": changelist.show_facets,
                **changelist.facet_query_strings(),
                "has_filters": changelist.has_filters,
                "has_active_filters": changelist.has_active_filters(),
                "clear_all_filters_query_string": changelist.clear_all_filters_query_string(),
                "actions_on_top": bool(model_admin.actions_on_top),
                "actions_on_bottom": bool(model_admin.actions_on_bottom),
                "actions_selection_counter": bool(model_admin.actions_selection_counter),
                "show_full_result_count": changelist.show_full_result_count,
                "show_admin_actions": changelist.show_admin_actions,
                "action_choices": model_admin.get_action_choices(request),
                "filters": changelist.filter_descriptions(),
                "date_hierarchy": changelist.date_hierarchy_description(),
                "list_display_fields": model_field_names,
                "list_display_links": [
                    field_name_for_display(field) for field in (changelist.list_display_links or ())
                ],
                "to_field": changelist.to_field,
                "object_id_field": changelist.object_id_field,
                "ordering_field_columns": display_ordering_field_columns,
                "ordering": changelist.ordering,
                **changelist.search_query_strings(),
                "search_fields": list(changelist.search_fields),
                "search_help_text": model_admin.search_help_text,
            },
            "action_form": action_form,
            "list_editing_formset_prefix": list_editing_formset_prefix,
            "list_editing_management_form": list_editing_management_form,
            "list_editing_total_form_count": list_editing_total_form_count,
            "list_editing_initial_form_count": list_editing_initial_form_count,
            "list_editing_formset": list_editing_formset,
            "list_editing_rows": list_editing_rows,
        }
        return ChangelistResponse.model_validate(payload).model_dump(mode="json")

    def _changelist_row_metadata(self, request, model_admin, obj, object_id, to_field=None):
        quoted_object_id = quote(object_id)
        detail_url = f"{request.path.rstrip('/')}/{quoted_object_id}"
        to_field_query_string = f"?_to_field={quote(to_field)}" if to_field else ""
        has_view_permission = model_admin.has_view_permission(request, obj)
        has_change_permission = model_admin.has_change_permission(request, obj)
        has_delete_permission = model_admin.has_delete_permission(request, obj)
        can_open_object = has_view_permission or has_change_permission
        return {
            "detail_url": f"{detail_url}{to_field_query_string}" if can_open_object else None,
            "change_form_url": f"{detail_url}/form{to_field_query_string}" if can_open_object else None,
            "delete_url": f"{detail_url}{to_field_query_string}" if has_delete_permission else None,
            "view_on_site_url": model_admin.get_view_on_site_url(obj) if can_open_object else None,
            "permissions": {
                "has_add_permission": model_admin.has_add_permission(request),
                "has_change_permission": has_change_permission,
                "has_delete_permission": has_delete_permission,
                "has_view_permission": has_view_permission,
            },
        }

    @staticmethod
    def _display_field_in(field, candidates):
        field_key = field_name_for_display(field)
        return any(field == candidate or field_key == field_name_for_display(candidate) for candidate in candidates)

    def _model_has_field(self, model, field):
        try:
            model._meta.get_field(field)
            return True
        except FieldDoesNotExist:
            return False

    def _filter_descriptions(self, request, model_admin):
        filters = []
        for field_name in model_admin.get_list_filter(request):
            if not isinstance(field_name, str):
                continue
            try:
                field = model_admin.model._meta.get_field(field_name)
            except FieldDoesNotExist:
                continue
            current = request.GET.get(field_name)
            values = (
                model_admin.get_queryset(request).order_by(field_name).values_list(field_name, flat=True).distinct()
            )
            choices = []
            for value in values:
                display = dict(field.choices).get(value, value) if field.choices else value
                choices.append(
                    {
                        "selected": str(value) == str(current),
                        "query_string": f"{field_name}={value}",
                        "display": str(display),
                    }
                )
            filters.append({"title": str(field.verbose_name), "choices": choices})
        return filters

    def _form_response(self, request, model_admin, obj):
        data = model_admin.get_form_description(request, obj)
        inlines = []
        for inline in model_admin.get_inline_instances(request, obj):
            count_options = inline.get_formset_count_options(request, obj)
            formset_class = inline.get_formset(request, obj, change=obj is not None, count_options=count_options)
            queryset = inline.model.objects.none()
            if obj is not None:
                fk = _get_foreign_key(inline.parent_model, inline.model, fk_name=inline.fk_name)
                related_name = fk.remote_field.accessor_name
                try:
                    queryset = getattr(obj, related_name).all()
                except AttributeError:
                    queryset = inline.model.objects.none()
            formset = formset_class(instance=obj, queryset=queryset)
            initial_form_count = formset.initial_form_count()
            fieldsets = inline.get_fieldsets(request, obj)
            inline_desc = {
                "model": f"{inline.model._meta.app_label}.{inline.model._meta.model_name}",
                "readonly_fields": list(inline.get_readonly_fields(request, obj)),
                "fieldset_layout": fieldset_layout_description(fieldsets),
                "prepopulated": dict(inline.get_prepopulated_fields(request, obj)),
                "media": form_media_description(formset_class.form()),
                "permissions": {
                    "has_add_permission": inline.has_add_permission(request, obj),
                    "has_change_permission": inline.has_change_permission(request, obj),
                    "has_delete_permission": inline.has_delete_permission(request, obj),
                    "has_view_permission": inline.has_view_permission(request, obj),
                },
                "formset_prefix": formset.prefix,
                "management_form": form_field_descriptions(
                    formset.management_form.__class__,
                    request=request,
                    form=formset.management_form,
                ),
                "total_form_count": formset.total_form_count(),
                "initial_form_count": initial_form_count,
                "empty_form_prefix": formset.empty_form.prefix,
                "empty_form": inline.get_form_fields_description(request, None, form=formset.empty_form),
                "formset_row_metadata": [],
                "extra": count_options["extra"],
                "min_num": count_options["min_num"],
                "max_num": count_options["max_num"],
                "verbose_name": str(inline.verbose_name),
                "verbose_name_plural": str(inline.verbose_name_plural),
                "can_delete": inline.can_delete,
                "show_change_link": inline.show_change_link,
                "admin_style": inline.admin_style,
                "formset": [],
            }
            for index, form in enumerate(formset.forms):
                form_obj = form.instance if getattr(form.instance, "pk", None) else None
                inline_desc["formset"].append(inline.get_form_fields_description(request, form_obj, form=form))
                row_metadata = {
                    "index": index,
                    "prefix": form.prefix,
                    "is_initial": index < initial_form_count,
                    "empty_permitted": form.empty_permitted,
                }
                if form_obj is not None:
                    row_metadata["object_id"] = str(form_obj.pk)
                inline_desc["formset_row_metadata"].append(row_metadata)
            inlines.append(inline_desc)
        data["inlines"] = inlines
        return FormResponse.model_validate(data).model_dump(mode="json")

    def _payload_data(self, payload, *, exclude_unset=True):
        data = cast(Any, getattr(payload, "data", {}))
        if hasattr(data, "model_dump"):
            return data.model_dump(mode="python", exclude_unset=exclude_unset)
        return data

    def _payload_inlines(self, payload):
        inlines = cast(Any, getattr(payload, "inlines", None))
        if hasattr(inlines, "model_dump"):
            return inlines.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_unset=True)
        return inlines

    def _normalize_form_data(self, form_class, data):
        normalized = dict(data)
        for field_name, field in form_class.base_fields.items():
            if field_name in normalized:
                normalized[field_name] = self._normalize_form_value(field, normalized[field_name])
            if isinstance(field, forms.FileField) and field_name in normalized and normalized[field_name] is None:
                normalized.pop(field_name)
                normalized[f"{field_name}-clear"] = "on"
            if isinstance(field, forms.MultiValueField) and field_name in normalized:
                self._expand_multivalue_form_data(normalized, field_name, field)
        return normalized

    def _normalize_form_value(self, field, value):
        if value is None:
            return value
        if isinstance(field, (forms.URLField, forms.GenericIPAddressField, forms.UUIDField)) and not isinstance(
            value,
            str,
        ):
            return str(value)
        return value

    def _expand_multivalue_form_data(self, data, field_name, field):
        value = data[field_name]
        values = None
        if value is None:
            values = [""] * len(field.fields)
        elif isinstance(value, (list, tuple)):
            values = value
        elif hasattr(field.widget, "decompress"):
            try:
                values = field.widget.decompress(value)
            except (AttributeError, TypeError, ValueError):
                values = None
        if values is None:
            return
        data.pop(field_name, None)
        for index, item in enumerate(values):
            data[f"{field_name}_{index}"] = item

    def _create_object(self, request, model_admin, payload, *, files=None):
        if not model_admin.has_add_permission(request):
            raise PermissionDenied
        with transaction.atomic(using=router_db_for_write(model_admin.model)):
            form_class = model_admin.get_form_class(request, None, change=False)
            form_data = self._normalize_form_data(form_class, self._payload_data(payload))
            form = form_class(data=form_data, files=files or None)
            if not form.is_valid():
                raise AdminValidationError({"form": form_errors(form)})
            obj = model_admin.save_form(request, form, change=False)
            model_admin.save_model(request, obj, form, change=False)
            inline_results = self._process_inlines(
                request,
                model_admin,
                obj,
                self._payload_inlines(payload) or {},
                change=False,
            )
            model_admin.save_related(request, form, inline_results, change=False)
            change_message = model_admin.construct_change_message(request, form, inline_results, add=True)
            model_admin.log_addition(request, obj, change_message)
            response = model_admin.response_add(request, obj, form, inline_results)
            if isinstance(response, Status):
                return response
            return Status(201, response)

    def _file_form_field_names(self, model_admin, request=None, obj=None, *, change):
        form_class = model_admin.get_form_class(request, obj, change=change)
        return [name for name, field in form_class.base_fields.items() if isinstance(field, forms.FileField)]

    def _mutation_payload_example(self, model_admin, *, change, partial):
        form_class = model_admin.get_form_class(None, None, change=change)
        overrides = model_admin.get_form_schema_field_overrides(None, None, change=change) or {}
        payload = {
            "data": self._form_data_example(
                form_class.base_fields,
                partial=partial,
                overrides=overrides,
                schema_owner=model_admin,
            )
        }
        inline_examples = self._inline_payload_example(model_admin, change=change)
        if inline_examples:
            payload["inlines"] = inline_examples
        return payload

    def _bulk_payload_example(self, model_admin):
        form_class = model_admin.get_changelist_form_class(None)
        overrides = model_admin.get_form_schema_field_overrides(None, change=True) or {}
        row = {"pk": 1}
        row.update(
            self._form_data_example(
                form_class.base_fields,
                partial=True,
                overrides=overrides,
                schema_owner=model_admin,
            )
        )
        return {"data": [row]}

    def _action_payload_example(self, model_admin):
        model_actions = model_admin._get_base_actions()
        if not model_actions:
            return {"action": "action_name", "selected_ids": [1], "select_across": False}
        func, name, _description = next(
            (
                model_action
                for model_action in model_actions
                if getattr(model_action[0], "action_input_schema", None) is not None
            ),
            model_actions[0],
        )
        payload = {"action": name, "selected_ids": [1], "select_across": False}
        input_schema = getattr(func, "action_input_schema", None)
        if input_schema is not None:
            payload["data"] = pydantic_model_example(input_schema)
        return payload

    def _inline_payload_example(self, model_admin, *, change):
        examples = {}
        for inline in model_admin.get_inline_instances(None, check_permissions=False):
            inline_id = f"{inline.model._meta.app_label}.{inline.model._meta.model_name}"
            formset_class = inline.get_formset(None, None, change=change)
            overrides = inline.get_form_schema_field_overrides(None, None, change=change) or {}
            row = self._form_data_example(
                formset_class.form.base_fields,
                partial=False,
                overrides=overrides,
                schema_owner=inline,
            )
            if not row:
                continue
            if change:
                examples[inline_id] = {"change": [{"pk": 1, **row}], "delete": [2]}
            else:
                examples[inline_id] = {"add": [row]}
        return examples

    def _form_data_example(self, form_fields, *, partial, overrides=None, schema_owner=None):
        override_example = None
        if schema_owner is not None:

            def override_example(value):
                field_type, default = schema_owner._normalize_schema_override(value)
                return schema_type_example(field_type, default)

        return form_data_example(
            form_fields,
            partial=partial,
            overrides=overrides,
            exclude_file_fields=True,
            field_example=lambda _name, field, override: form_field_example_value(
                field,
                override=override if schema_owner is not None else None,
                override_example=override_example,
                relation_example=relation_form_field_example_value,
                choices_json_safe=True,
                coerce_typed_choice=False,
            ),
        )

    def _multipart_openapi_extra(self, payload_schema, file_fields, *, required_data, required_file_fields=()):
        properties = {
            "data": {
                "type": "string",
                "contentMediaType": "application/json",
                "description": f"JSON object matching {payload_schema.__name__}.data.",
            },
            "inlines": {
                "type": "string",
                "contentMediaType": "application/json",
                "description": f"Optional JSON object matching {payload_schema.__name__}.inlines.",
            },
        }
        for field_name in file_fields:
            properties[field_name] = {"type": "string", "format": "binary"}
        schema = {"type": "object", "properties": properties}
        required = []
        if required_data:
            required.append("data")
        required.extend(field_name for field_name in file_fields if field_name in required_file_fields)
        if required:
            schema["required"] = required
        return {"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": schema}}}}

    def _required_file_form_field_names(self, model_admin, request=None, obj=None, *, change):
        form_class = model_admin.get_form_class(request, obj, change=change)
        return [
            name
            for name, field in form_class.base_fields.items()
            if isinstance(field, forms.FileField) and field.required and not getattr(field, "disabled", False)
        ]

    def _multipart_mutation_payload(self, request, payload_schema, file_fields=()):
        data = self._json_form_part(request, "data", default={})
        inlines = self._json_form_part(request, "inlines", default=None)
        if not isinstance(data, dict):
            raise NinjaValidationError(
                [
                    {
                        "loc": ("body", "payload", "data"),
                        "msg": "Input should be a valid object",
                        "type": "dict_type",
                    }
                ]
            )
        data = self._multipart_payload_data_with_file_parts(request, data, file_fields)
        payload_data = {"data": data}
        if inlines is not None:
            if not isinstance(inlines, dict):
                raise NinjaValidationError(
                    [
                        {
                            "loc": ("body", "payload", "inlines"),
                            "msg": "Input should be a valid object",
                            "type": "dict_type",
                        }
                    ]
                )
            payload_data["inlines"] = inlines
        try:
            return payload_schema.model_validate(payload_data)
        except PydanticValidationError as exc:
            self._raise_request_validation(exc)

    def _multipart_payload_data_with_file_parts(self, request, data, file_fields):
        if not file_fields:
            return data
        _form_data, files = self._multipart_request_parts(request)
        if not files:
            return data
        data = dict(data)
        for field_name in file_fields:
            if field_name not in data and field_name in files:
                data[field_name] = files[field_name].name
        return data

    def _json_form_part(self, request, name, *, default):
        form_data, _files = self._multipart_request_parts(request)
        if name not in form_data:
            return default
        raw_value = form_data.get(name)
        if raw_value in ("", None):
            return default
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise NinjaValidationError(
                [
                    {
                        "loc": ("body", "payload", name),
                        "msg": "Input should be valid JSON",
                        "type": "json_invalid",
                    }
                ]
            ) from exc

    def _raise_request_validation(self, exc):
        errors = []
        for error in exc.errors(include_url=False):
            error = dict(error)
            error.pop("input", None)
            error["loc"] = ("body", "payload", *error.get("loc", ()))
            errors.append(error)
        raise NinjaValidationError(errors)

    def _multipart_request_parts(self, request):
        cache_name = "_django_ninja_admin_multipart_parts"
        if hasattr(request, cache_name):
            return getattr(request, cache_name)
        if request.method == "POST":
            parts = (request.POST, request.FILES)
        else:
            try:
                parts = request.parse_file_upload(request.META, request)
            except MultiPartParserError as exc:
                raise NinjaValidationError(
                    [
                        {
                            "loc": ("body", "payload"),
                            "msg": "Input should be valid multipart form data",
                            "type": "multipart_invalid",
                        }
                    ]
                ) from exc
        setattr(request, cache_name, parts)
        return parts

    def _multipart_form_files(self, request, form_class):
        _form_data, files = self._multipart_request_parts(request)
        return {
            name: files[name]
            for name, field in form_class.base_fields.items()
            if isinstance(field, forms.FileField) and name in files
        }

    def _update_object(self, request, model_admin, object_id, payload, *, partial, files=None, obj=None, to_field=None):
        obj = obj or self._get_object_or_404(request, model_admin, object_id, to_field)
        if not model_admin.has_change_permission(request, obj):
            raise PermissionDenied
        with transaction.atomic(using=router_db_for_write(model_admin.model)):
            form_class = model_admin.get_form_class(request, obj, change=True)
            form_data = self._payload_data(payload, exclude_unset=partial)
            if partial:
                current = model_data_for_form(obj, list(form_class.base_fields.keys()))
                current.update(form_data)
                form_data = current
            form_data = self._normalize_form_data(form_class, form_data)
            form = form_class(data=form_data, files=files or None, instance=obj)
            if not form.is_valid():
                raise AdminValidationError({"form": form_errors(form)})
            updated_object = model_admin.save_form(request, form, change=True)
            model_admin.save_model(request, updated_object, form, change=True)
            inline_results = self._process_inlines(
                request,
                model_admin,
                updated_object,
                self._payload_inlines(payload) or {},
                change=True,
            )
            model_admin.save_related(request, form, inline_results, change=True)
            change_message = model_admin.construct_change_message(request, form, inline_results)
            if change_message:
                model_admin.log_change(request, updated_object, change_message)
            response = model_admin.response_change(request, updated_object, form, inline_results)
            if isinstance(response, Status):
                return response
            return Status(200, response)

    def _process_inlines(self, request, model_admin, obj, inline_payload, *, change):
        if not inline_payload:
            return {}
        results = {}
        inline_by_id = {
            f"{inline.model._meta.app_label}.{inline.model._meta.model_name}": inline
            for inline in model_admin.get_inline_instances(request, obj, check_permissions=False)
        }
        for inline_id, operations in inline_payload.items():
            if inline_id not in inline_by_id:
                raise AdminValidationError(
                    {inline_id: [{"message": _("Unknown inline."), "param": "non_field_errors"}]}
                )
            inline = inline_by_id[inline_id]
            fk = _get_foreign_key(inline.parent_model, inline.model, fk_name=inline.fk_name)
            related_name = fk.remote_field.accessor_name
            related_manager = getattr(obj, related_name, None)
            results[inline_id] = self._process_inline_formset(
                request,
                inline,
                obj,
                operations,
                related_manager,
                change=change,
            )
        return results

    def _process_inline_formset(self, request, inline, obj, operations, related_manager, *, change):
        allowed_operations = {"add", "change", "delete"}
        unknown_operations = set(operations) - allowed_operations
        if unknown_operations:
            raise AdminValidationError(
                {
                    f"{inline.model._meta.app_label}.{inline.model._meta.model_name}": [
                        {
                            "message": _("Unknown inline operation: %(operations)s.")
                            % {"operations": ", ".join(sorted(unknown_operations))},
                            "param": "non_field_errors",
                        }
                    ]
                }
            )

        add_rows = list(operations.get("add", []))
        change_rows = list(operations.get("change", []))
        delete_values = [str(pk) for pk in operations.get("delete", [])]
        delete_pks = set(delete_values)
        if add_rows and not inline.has_add_permission(request, obj):
            raise PermissionDenied
        if change_rows and not inline.has_change_permission(request, obj):
            raise PermissionDenied
        if delete_pks and not inline.has_delete_permission(request, obj):
            raise PermissionDenied
        if delete_pks and not inline.can_delete:
            raise AdminValidationError(
                {
                    f"{inline.model._meta.app_label}.{inline.model._meta.model_name}": {
                        "delete": [{"message": _("Inline deletion is not allowed."), "param": "delete"}]
                    }
                }
            )

        formset_class = inline.get_formset(request, obj, change=change)
        form_fields = formset_class.form.base_fields
        editable_fields = set(form_fields)
        pk_name = inline.model._meta.pk.name
        inline_id = f"{inline.model._meta.app_label}.{inline.model._meta.model_name}"
        inline_errors = {}
        duplicate_delete_pks = {pk for pk in delete_values if delete_values.count(pk) > 1}
        for index, pk in enumerate(delete_values):
            if pk in duplicate_delete_pks:
                self._add_inline_row_error(
                    inline_errors,
                    "delete",
                    index,
                    message=_("Duplicate inline delete pk."),
                    param="pk",
                )
        self._collect_inline_row_field_errors(inline_errors, add_rows, editable_fields, operation="add")
        self._collect_inline_row_field_errors(
            inline_errors,
            change_rows,
            editable_fields | {"pk", "id", pk_name},
            operation="change",
        )

        queryset = related_manager.all() if related_manager is not None else inline.model.objects.none()
        existing_instances = list(queryset)
        existing_by_pk = {str(instance.pk): instance for instance in existing_instances}
        changes_by_pk = {}
        seen_change_pks = set()
        for index, row in enumerate(change_rows):
            pk = row.get("pk") or row.get(inline.model._meta.pk.name)
            has_row_error = False
            if pk is None:
                self._add_inline_row_error(
                    inline_errors,
                    "change",
                    index,
                    message=_("Missing pk."),
                    param="pk",
                )
                continue
            pk = str(pk)
            if pk in seen_change_pks:
                self._add_inline_row_error(
                    inline_errors,
                    "change",
                    index,
                    message=_("Duplicate inline change pk."),
                    param="pk",
                )
                has_row_error = True
            seen_change_pks.add(pk)
            if pk not in existing_by_pk:
                self._add_inline_row_error(
                    inline_errors,
                    "change",
                    index,
                    message=_("Unknown inline object."),
                    param="pk",
                )
                has_row_error = True
            if pk in delete_pks and pk in existing_by_pk:
                self._add_inline_row_error(
                    inline_errors,
                    "change",
                    index,
                    message=_("Inline object cannot be changed and deleted in the same request."),
                    param="pk",
                )
                has_row_error = True
            if not has_row_error:
                changes_by_pk[pk] = row
        for index, pk in enumerate(delete_values):
            if pk not in existing_by_pk:
                self._add_inline_row_error(
                    inline_errors,
                    "delete",
                    index,
                    message=_("Unknown inline object."),
                    param="pk",
                )
        if inline_errors:
            raise AdminValidationError({inline_id: inline_errors})

        formset_data = self._inline_formset_data(
            request,
            inline,
            obj,
            formset_class,
            existing_instances,
            changes_by_pk,
            add_rows,
            delete_pks,
        )
        formset = formset_class(data=formset_data, instance=obj, queryset=queryset)
        if not formset.is_valid():
            raise AdminValidationError({inline_id: {"formset": formset_errors(formset)}})
        deleted_objects = [
            {"id": existing_by_pk[pk].pk, "_object_repr": str(existing_by_pk[pk])} for pk in delete_values
        ]
        formset.save()
        changed_objects = []
        for instance, fields in formset.changed_objects:
            item = inline.serialize_object(instance, request)
            item["_changed_fields"] = [self._inline_field_label(inline, field_name) for field_name in fields]
            changed_objects.append(item)
        return {
            "add": [inline.serialize_object(instance, request) for instance in formset.new_objects],
            "change": changed_objects,
            "delete": [item["id"] for item in deleted_objects],
            "_delete_objects": deleted_objects,
        }

    def _collect_inline_row_field_errors(self, inline_errors, rows, allowed_fields, *, operation):
        for index, row in enumerate(rows):
            unknown_fields = sorted(set(row) - allowed_fields)
            for field in unknown_fields:
                self._add_inline_row_error(
                    inline_errors,
                    operation,
                    index,
                    message=_("Unknown or readonly inline field."),
                    param=field,
                )

    def _add_inline_row_error(self, inline_errors, operation, index, *, message, param):
        row_errors = inline_errors.setdefault(operation, {}).setdefault(index, [])
        row_errors.append({"message": message, "param": param})

    def _inline_field_label(self, inline, field_name):
        try:
            return str(inline.model._meta.get_field(field_name).verbose_name)
        except FieldDoesNotExist:
            return field_name.replace("_", " ")

    def _inline_formset_data(
        self,
        request,
        inline,
        obj,
        formset_class,
        existing_instances,
        changes_by_pk,
        add_rows,
        delete_pks,
    ):
        prefix = formset_class.get_default_prefix()
        min_num = inline.get_min_num(request, obj) or 0
        max_num = inline.get_max_num(request, obj)
        total_forms = len(existing_instances) + len(add_rows)
        formset_data = {
            f"{prefix}-TOTAL_FORMS": str(total_forms),
            f"{prefix}-INITIAL_FORMS": str(len(existing_instances)),
            f"{prefix}-MIN_NUM_FORMS": str(min_num),
            f"{prefix}-MAX_NUM_FORMS": "" if max_num is None else str(max_num),
        }
        form_fields = formset_class.form.base_fields
        editable_fields = set(form_fields)
        pk_name = inline.model._meta.pk.name
        fk = _get_foreign_key(inline.parent_model, inline.model, fk_name=inline.fk_name)
        for index, instance in enumerate(existing_instances):
            pk = str(instance.pk)
            row = model_data_for_form(instance, list(editable_fields))
            row.update(changes_by_pk.get(pk, {}))
            self._copy_inline_form_row(formset_data, prefix, index, row, form_fields)
            formset_data[f"{prefix}-{index}-{pk_name}"] = pk
            formset_data[f"{prefix}-{index}-{fk.name}"] = str(obj.pk)
            if pk in delete_pks:
                formset_data[f"{prefix}-{index}-DELETE"] = "on"
        for offset, row in enumerate(add_rows, start=len(existing_instances)):
            self._copy_inline_form_row(formset_data, prefix, offset, row, form_fields)
            formset_data[f"{prefix}-{offset}-{fk.name}"] = str(obj.pk)
        return formset_data

    def _copy_inline_form_row(self, formset_data, prefix, index, row, form_fields):
        for name, value in row.items():
            if name in {"pk", "id"} or name not in form_fields:
                continue
            field = form_fields[name]
            value = self._normalize_form_value(field, value)
            if isinstance(field, forms.FileField) and value is None:
                formset_data[f"{prefix}-{index}-{name}-clear"] = "on"
                continue
            if isinstance(field, forms.MultiValueField):
                expanded = {name: value}
                self._expand_multivalue_form_data(expanded, name, field)
                for expanded_name, expanded_value in expanded.items():
                    formset_data[f"{prefix}-{index}-{expanded_name}"] = expanded_value
                continue
            formset_data[f"{prefix}-{index}-{name}"] = value

    def _bulk_update(self, request, model_admin, payload, *, queryset=None, object_id_field=None):
        payload_data = [
            item.model_dump(mode="python", exclude_unset=True) if hasattr(item, "model_dump") else item
            for item in payload.data
        ]
        if not payload_data:
            raise AdminValidationError([{"message": _("Change data cannot be empty."), "param": "data"}])
        queryset = queryset if queryset is not None else model_admin.get_queryset(request)
        validated_rows = []
        row_errors = {}
        has_permission_errors = False
        seen_pks = set()
        allowed = set(model_admin.list_editable) | {"pk", model_admin.model._meta.pk.name}
        for idx, data in enumerate(payload_data):
            pk = data.get("pk") or data.get(model_admin.model._meta.pk.name)
            if pk is None:
                row_errors[idx] = [{"message": _("This field is required."), "param": "pk"}]
                continue
            pk_key = str(pk)
            if pk_key in seen_pks:
                row_errors[idx] = [{"message": _("Duplicate object in bulk update."), "param": "pk"}]
                continue
            seen_pks.add(pk_key)
            unknown_fields = sorted(set(data) - allowed)
            if unknown_fields:
                row_errors[idx] = [
                    {
                        "message": _("Field is not list editable: %(fields)s.") % {"fields": ", ".join(unknown_fields)},
                        "param": unknown_fields[0],
                    }
                ]
                continue
            obj = self._bulk_object_from_queryset(queryset, pk, object_id_field=object_id_field)
            if obj is None:
                row_errors[idx] = [{"message": _("Object not found."), "param": "pk"}]
                continue
            if not model_admin.has_change_permission(request, obj):
                row_errors[idx] = [{"message": _("Permission denied."), "param": "pk"}]
                has_permission_errors = True
                continue
            form_class = model_admin.get_changelist_form_class(request)
            current = model_data_for_form(obj, list(form_class.base_fields.keys()))
            current.update({key: value for key, value in data.items() if key in allowed})
            current = self._normalize_form_data(form_class, current)
            form = form_class(data=current, instance=obj)
            if not form.is_valid():
                row_errors[idx] = form_errors(form)
                continue
            validated_rows.append((idx, obj, form))
        if row_errors:
            if has_permission_errors:
                raise AdminPermissionError(row_errors)
            raise AdminValidationError(row_errors)

        results = {}
        with transaction.atomic(using=router_db_for_write(model_admin.model)):
            for idx, obj, form in validated_rows:
                if form.has_changed():
                    updated = model_admin.save_form(request, form, change=True)
                    model_admin.save_model(request, updated, form, change=True)
                    model_admin.save_related(request, form, {}, change=True)
                    change_message = model_admin.construct_change_message(request, form)
                    if change_message:
                        model_admin.log_change(request, updated, change_message)
                    obj = updated
                results[str(idx)] = model_admin.serialize_object(obj, request)
        return {"data": results}

    def _bulk_object_from_queryset(self, queryset, pk, *, object_id_field=None):
        field = queryset.model._meta.pk if object_id_field is None else queryset.model._meta.get_field(object_id_field)
        try:
            object_id = field.to_python(pk)
            return queryset.get(**{field.name: object_id})
        except (queryset.model.DoesNotExist, ValidationError, ValueError):
            return None


def router_db_for_write(model):
    return router.db_for_write(model)


class DefaultAdminSite(LazyObject):
    def _setup(self):
        AdminSiteClass = import_string(apps.get_app_config("django_ninja_admin").default_site)
        self._wrapped = AdminSiteClass(name="ninja_admin")

    def __repr__(self):
        return repr(self._wrapped)


site = DefaultAdminSite()
