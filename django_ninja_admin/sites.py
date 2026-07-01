import json
from functools import wraps
from typing import Any
from weakref import WeakSet

from django import forms
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
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
from django.forms.models import _get_foreign_key
from django.http import Http404
from django.http.multipartparser import MultiPartParserError
from django.utils.functional import LazyObject
from django.utils.module_loading import import_string
from django.utils.text import capfirst
from ninja import NinjaAPI, Query, Router, Status
from ninja.errors import AuthenticationError, AuthorizationError, HttpError
from ninja.errors import ValidationError as NinjaValidationError
from ninja.security import SessionAuthIsStaff
from pydantic import ValidationError as PydanticValidationError

from django_ninja_admin import actions
from django_ninja_admin.admins.model import ModelAdmin
from django_ninja_admin.exceptions import (
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
    ErrorResponse,
    FormResponse,
    HistoryResponse,
    MutationResponse,
    SiteContext,
    ViewOnSiteResponse,
)
from django_ninja_admin.utils.deletion import deletion_error_payload
from django_ninja_admin.utils.format_error import format_error
from django_ninja_admin.utils.forms import form_errors, formset_errors, model_data_for_form
from django_ninja_admin.utils.lookup import display_metadata_for_field, label_for_field, lookup_field
from django_ninja_admin.utils.quote import unquote

all_sites = WeakSet()
DEFAULT_AUTH = object()


class NinjaAdminSite:
    admin_class = ModelAdmin
    paginator = Paginator
    site_title = "Django Ninja site admin"
    site_header = "Django Ninja administration"
    index_title = "Site administration"
    site_url = "/"
    enable_nav_sidebar = True
    empty_value_display = "-"
    include_auth = True

    def __init__(self, *, name="ninja_admin", auth=DEFAULT_AUTH, include_auth=True):
        self.name = name
        self.include_auth = include_auth
        self.auth = SessionAuthIsStaff() if auth is DEFAULT_AUTH else auth
        self._registry = {}
        self._actions = {"delete_selected": actions.delete_selected}
        self._global_actions = self._actions.copy()
        self._api = None
        all_sites.add(self)
        if include_auth:
            self.register([get_user_model(), Group])

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
        except KeyError:
            raise NotRegistered(f"The model {model.__name__} is not registered.")

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
        @wraps(view_func)
        def inner(request, *args, **kwargs):
            if not self.has_permission(request):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return inner

    def route(
        self,
        path,
        view_func,
        *,
        methods=("GET",),
        response=dict[str, Any],
        operation_id=None,
        summary=None,
        description=None,
        tags=None,
        auth=DEFAULT_AUTH,
        include_in_schema=True,
    ):
        route_auth = self.auth if auth is DEFAULT_AUTH else auth
        return AdminRoute(
            path=path,
            view_func=view_func,
            methods=tuple(method.upper() for method in methods),
            response=response,
            operation_id=operation_id,
            summary=summary,
            description=description,
            tags=tags,
            auth=route_auth,
            include_in_schema=include_in_schema,
        )

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
        app_dict = {}
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
            "site_title": str(self.site_title),
            "site_header": str(self.site_header),
            "site_url": site_url,
            "has_permission": request.user.is_active and request.user.is_staff,
            "available_apps": self.get_app_list(request),
            "is_nav_sidebar_enabled": self.enable_nav_sidebar,
        }

    def paginate_queryset(self, request, paginator, page_kwarg="page"):
        page_value = request.GET.get(page_kwarg) or 1
        try:
            page_number = paginator.num_pages if page_value == "last" else int(page_value)
            page = paginator.page(page_number)
            return page, page.object_list, page.has_other_pages()
        except (ValueError, InvalidPage) as exc:
            raise HttpError(404, f"Invalid page ({page_value}): {exc}")

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
            title=str(self.site_header),
            version="2.0.0",
            urls_namespace=self.name,
            auth=self.auth,
            openapi_url="/openapi.json",
            docs_url="/docs",
        )
        self._register_exception_handlers(api)
        router = Router(tags=["admin"])
        self._register_site_routes(router)
        self._register_custom_routes(router, self.get_urls(), default_tags=["admin"])
        for model, model_admin in self._registry.items():
            self._register_model_routes(router, model, model_admin)
        api.add_router("", router)
        return api

    def _register_custom_routes(self, router, routes, *, prefix="", default_tags=None):
        for route in routes:
            if not isinstance(route, AdminRoute):
                raise ImproperlyConfigured("Custom admin get_urls() entries must be AdminRoute instances.")
            path = self._join_route_path(prefix, route.path)
            view_func = self._custom_route_view_func(route.view_func)
            router.add_api_operation(
                path,
                list(route.methods),
                view_func,
                auth=route.auth,
                response=route.response,
                operation_id=route.operation_id,
                summary=route.summary,
                description=route.description,
                tags=route.tags or default_tags,
                include_in_schema=route.include_in_schema,
            )

    def _custom_route_view_func(self, view_func):
        if not (hasattr(view_func, "__self__") and hasattr(view_func, "__func__")):
            return view_func

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

        @api.exception_handler(ProtectedDelete)
        def protected_delete(request, exc):
            return error_response(request, str(exc), 409)

        def permission_denied(request, exc):
            return error_response(request, "Permission denied.", 403)

        api.add_exception_handler(PermissionDenied, permission_denied)
        api.add_exception_handler(AuthorizationError, permission_denied)

        def not_authenticated(request, exc):
            return error_response(request, "Authentication required.", 401)

        api.add_exception_handler(AuthenticationError, not_authenticated)

        def not_found(request, exc):
            return error_response(request, "Not found.", 404)

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
            return error_response(request, "Missing search_fields.", 409, param="search_fields")

    def _request_validation_param(self, error):
        if error.get("type") == "union_tag_invalid":
            discriminator = (error.get("ctx") or {}).get("discriminator")
            if discriminator:
                return str(discriminator).strip("'\"")
        location_parts = [str(part) for part in error.get("loc", []) if part not in {"body", "payload"}]
        if len(location_parts) > 1 and location_parts[1] in {"action", "selected_ids", "select_across", "data"}:
            location_parts = location_parts[1:]
        return ".".join(location_parts)

    def _history_content_type_ids(self, request, *, app_label=None, model_name=None):
        if model_name and not app_label:
            raise AdminValidationError(
                [{"message": "app_label is required when model is provided.", "param": "app_label"}]
            )
        if app_label and model_name:
            try:
                model = apps.get_model(app_label, model_name)
                model_admin = self.get_model_admin(model)
            except (LookupError, NotRegistered):
                raise Http404
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

    def _register_site_routes(self, router):
        site = self

        @router.get("/apps", response=list[AppSummary], operation_id="admin_list_apps")
        def list_apps(request):
            return site.get_app_list(request)

        @router.get("/apps/{app_label}", response=AppSummary, operation_id="admin_get_app")
        def get_app(request, app_label: str):
            return site.get_app_list(request, app_label)

        @router.get("/context", response=SiteContext, operation_id="admin_context")
        def context(request):
            return site.each_context(request)

        @router.get("/permissions", response=dict[str, bool], operation_id="admin_permissions")
        def permissions(request):
            user = request.user
            return {
                "is_authenticated": user.is_authenticated,
                "is_active": user.is_active,
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
            }

        @router.get("/history", response=HistoryResponse, operation_id="admin_history")
        def history(
            request,
            app_label: str | None = None,
            model: str | None = None,
            object_id: str | None = None,
            action_flag: int | None = None,
            o: str = "-action_time",
            page: int = 1,
        ):
            from django_ninja_admin.models import ACTION_FLAG_CHOICES, LogEntry

            if o not in {"action_time", "-action_time"}:
                raise AdminValidationError([{"message": "Invalid ordering provided.", "param": "o"}])
            if action_flag is not None and action_flag not in dict(ACTION_FLAG_CHOICES):
                raise AdminValidationError([{"message": "Invalid action flag provided.", "param": "action_flag"}])
            qs = (
                LogEntry.objects.filter(
                    content_type_id__in=site._history_content_type_ids(
                        request,
                        app_label=app_label,
                        model_name=model,
                    )
                )
                .order_by(o)
                .select_related("content_type")
            )
            if object_id is not None:
                qs = qs.filter(object_id=object_id)
            if action_flag is not None:
                qs = qs.filter(action_flag=action_flag)
            paginator = site.paginator(qs, 20)
            try:
                page_obj = paginator.page(page)
            except InvalidPage:
                raise Http404
            results = []
            for item in page_obj.object_list:
                try:
                    message = json.loads(item.change_message or "[]")
                except json.JSONDecodeError:
                    message = item.change_message
                results.append(
                    {
                        "id": item.pk,
                        "action_time": item.action_time.isoformat(),
                        "user_id": item.user_id,
                        "content_type_id": item.content_type_id,
                        "object_id": item.object_id,
                        "object_repr": item.object_repr,
                        "action_flag": item.action_flag,
                        "change_message": message,
                    }
                )
            return {
                "pagination": {
                    "num_pages": paginator.num_pages,
                    "count": paginator.count,
                    "has_next": page_obj.has_next(),
                    "has_previous": page_obj.has_previous(),
                },
                "results": results,
            }

        @router.get("/autocomplete", response=AutocompleteResponse, operation_id="admin_autocomplete")
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
            except (AttributeError, LookupError, NotRegistered):
                raise Http404
            if field_name not in source_admin.get_autocomplete_fields(request):
                raise Http404
            if not source_admin.has_view_or_change_permission(request):
                raise PermissionDenied
            if not model_admin.search_fields:
                raise MissingSearchFields
            to_field_name = getattr(source_field.remote_field, "field_name", remote_model._meta.pk.attname)
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
            paginator = model_admin.paginator(qs, 20)
            try:
                page_obj = paginator.page(page)
            except InvalidPage:
                raise Http404
            return {
                "results": [{"id": str(getattr(obj, to_field_name)), "text": str(obj)} for obj in page_obj.object_list],
                "pagination": {"more": page_obj.has_next()},
            }

        @router.get(
            "/view-on-site/{content_type_id}/{object_id}",
            response=ViewOnSiteResponse,
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
            except (ObjectDoesNotExist, ValueError, ValidationError, NotRegistered):
                raise Http404
            if not model_admin.has_view_or_change_permission(request, obj):
                raise PermissionDenied
            if callable(model_admin.view_on_site):
                absurl = model_admin.view_on_site(obj)
            elif model_admin.view_on_site and hasattr(obj, "get_absolute_url"):
                absurl = obj.get_absolute_url()
            else:
                absurl = None
            if not absurl:
                return Status(409, {"errors": [{"message": "Object has no get_absolute_url().", "param": "object_id"}]})
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
        create_payload_schema = model_admin.get_mutation_payload_schema(None, change=False, partial=False)
        update_payload_schema = model_admin.get_mutation_payload_schema(None, change=True, partial=True)
        replace_payload_schema = model_admin.get_mutation_payload_schema(None, change=True, partial=False)
        bulk_payload_schema = model_admin.get_bulk_payload_schema(None)
        action_payload_schema = model_admin.get_action_payload_schema(None)
        action_response_schema = model_admin.get_action_response_schema(None)
        create_file_fields = site._file_form_field_names(model_admin, change=False)
        change_file_fields = site._file_form_field_names(model_admin, change=True)

        @router.get(
            prefix,
            response={200: ChangelistResponse, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
            tags=tags,
            operation_id=f"{app_label}_{model_name}_list",
        )
        def changelist(request):
            return site._changelist_response(request, model_admin)

        @router.get(
            f"{prefix}/form",
            response={200: FormResponse, 403: ErrorResponse},
            tags=tags,
            operation_id=f"{app_label}_{model_name}_add_form",
        )
        def add_form(request):
            if not model_admin.has_add_permission(request):
                raise PermissionDenied
            return site._form_response(request, model_admin, None)

        @router.post(
            prefix,
            response={201: MutationResponse, 400: ErrorResponse, 403: ErrorResponse, 422: ErrorResponse},
            tags=tags,
            operation_id=f"{app_label}_{model_name}_create",
        )
        def create(request, payload: create_payload_schema):
            return site._create_object(request, model_admin, payload)

        if create_file_fields:

            @router.post(
                f"{prefix}/multipart",
                response={201: MutationResponse, 400: ErrorResponse, 403: ErrorResponse, 422: ErrorResponse},
                tags=tags,
                operation_id=f"{app_label}_{model_name}_create_multipart",
                openapi_extra=site._multipart_openapi_extra(
                    create_payload_schema,
                    create_file_fields,
                    required_data=True,
                ),
            )
            def create_multipart(request):
                payload = site._multipart_mutation_payload(request, create_payload_schema)
                form_class = model_admin.get_form_class(request, None, change=False)
                return site._create_object(
                    request,
                    model_admin,
                    payload,
                    files=site._multipart_form_files(request, form_class),
                )

        @router.post(
            f"{prefix}/actions",
            response={
                200: action_response_schema,
                400: ErrorResponse,
                403: ErrorResponse,
                409: ErrorResponse,
                422: ErrorResponse,
            },
            tags=tags,
            operation_id=f"{app_label}_{model_name}_action",
        )
        def actions_view(request, payload: action_payload_schema):
            if not model_admin.has_view_or_change_permission(request):
                raise PermissionDenied
            cl_queryset = site._filtered_queryset(request, model_admin)
            return model_admin.response_action(request, cl_queryset, payload)

        @router.put(
            f"{prefix}/bulk",
            response={200: dict[str, Any], 400: ErrorResponse, 403: ErrorResponse, 422: ErrorResponse},
            tags=tags,
            operation_id=f"{app_label}_{model_name}_bulk_update",
        )
        def bulk_update(request, payload: bulk_payload_schema):
            if not model_admin.has_change_permission(request):
                raise PermissionDenied
            return site._bulk_update(request, model_admin, payload)

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
                400: ErrorResponse,
                403: ErrorResponse,
                404: ErrorResponse,
            },
            tags=tags,
            operation_id=f"{app_label}_{model_name}_detail",
        )
        def detail(request, object_id: str, to_field: str | None = Query(None, alias="_to_field")):
            obj = site._get_object_or_404(request, model_admin, object_id, to_field)
            if not model_admin.has_view_or_change_permission(request, obj):
                raise PermissionDenied
            return model_admin.serialize_object(obj, request)

        @router.get(
            f"{prefix}/{{object_id}}/form",
            response={200: FormResponse, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
            tags=tags,
            operation_id=f"{app_label}_{model_name}_change_form",
        )
        def change_form(request, object_id: str, to_field: str | None = Query(None, alias="_to_field")):
            obj = site._get_object_or_404(request, model_admin, object_id, to_field)
            if not model_admin.has_view_or_change_permission(request, obj):
                raise PermissionDenied
            return site._form_response(request, model_admin, obj)

        @router.patch(
            f"{prefix}/{{object_id}}",
            response={
                200: MutationResponse,
                400: ErrorResponse,
                403: ErrorResponse,
                404: ErrorResponse,
                422: ErrorResponse,
            },
            tags=tags,
            operation_id=f"{app_label}_{model_name}_partial_update",
        )
        def update(request, object_id: str, payload: update_payload_schema):
            return site._update_object(request, model_admin, object_id, payload, partial=True)

        @router.put(
            f"{prefix}/{{object_id}}",
            response={
                200: MutationResponse,
                400: ErrorResponse,
                403: ErrorResponse,
                404: ErrorResponse,
                422: ErrorResponse,
            },
            tags=tags,
            operation_id=f"{app_label}_{model_name}_update",
        )
        def replace(request, object_id: str, payload: replace_payload_schema):
            return site._update_object(request, model_admin, object_id, payload, partial=False)

        if change_file_fields:

            @router.patch(
                f"{prefix}/{{object_id}}/multipart",
                response={
                    200: MutationResponse,
                    400: ErrorResponse,
                    403: ErrorResponse,
                    404: ErrorResponse,
                    422: ErrorResponse,
                },
                tags=tags,
                operation_id=f"{app_label}_{model_name}_partial_update_multipart",
                openapi_extra=site._multipart_openapi_extra(
                    update_payload_schema,
                    change_file_fields,
                    required_data=False,
                ),
            )
            def update_multipart(request, object_id: str):
                obj = site._get_object_or_404(request, model_admin, object_id)
                form_class = model_admin.get_form_class(request, obj, change=True)
                payload = site._multipart_mutation_payload(request, update_payload_schema)
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
                response={
                    200: MutationResponse,
                    400: ErrorResponse,
                    403: ErrorResponse,
                    404: ErrorResponse,
                    422: ErrorResponse,
                },
                tags=tags,
                operation_id=f"{app_label}_{model_name}_update_multipart",
                openapi_extra=site._multipart_openapi_extra(
                    replace_payload_schema,
                    change_file_fields,
                    required_data=True,
                ),
            )
            def replace_multipart(request, object_id: str):
                obj = site._get_object_or_404(request, model_admin, object_id)
                form_class = model_admin.get_form_class(request, obj, change=True)
                payload = site._multipart_mutation_payload(request, replace_payload_schema)
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
                200: dict[str, Any],
                204: None,
                400: ErrorResponse,
                403: ErrorResponse,
                404: ErrorResponse,
                409: ErrorResponse,
            },
            tags=tags,
            operation_id=f"{app_label}_{model_name}_delete",
        )
        def delete(request, object_id: str, to_field: str | None = Query(None, alias="_to_field")):
            obj = site._get_object_or_404(request, model_admin, object_id, to_field)
            if not model_admin.has_delete_permission(request, obj):
                raise PermissionDenied
            deleted_objects, model_count, perms_needed, protected = model_admin.get_deleted_objects([obj], request)
            if protected:
                return Status(
                    409,
                    deletion_error_payload(
                        "Cannot delete protected objects.",
                        protected=protected,
                        model_count=model_count,
                    ),
                )
            if perms_needed:
                return Status(
                    403,
                    deletion_error_payload(
                        "Permission denied.",
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
                return response
            return Status(204, None)

    def _get_object_or_404(self, request, model_admin, object_id, to_field=None):
        if to_field and not model_admin.to_field_allowed(request, to_field):
            raise AdminValidationError(
                [{"message": f"The field '{to_field}' cannot be referenced.", "param": "_to_field"}]
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
        columns = [
            {
                "field": field,
                "headerName": label_for_field(field, model_admin.model, model_admin),
                "display_link": field in (changelist.list_display_links or ()),
                **display_metadata_for_field(field, model_admin.model, model_admin),
                "sortable": field in changelist.ordering_field_columns,
                "ordering_field": changelist.get_ordering_field(field),
                "ordering_index": changelist.ordering_field_columns.get(field),
                **changelist.column_sort_query_strings(field),
            }
            for field in list_display
        ]
        rows = []
        empty_value = model_admin.get_empty_value_display()
        for obj in changelist.result_list:
            cells = {}
            for field in list_display:
                value = lookup_field(field, obj, model_admin)
                display_metadata = display_metadata_for_field(field, model_admin.model, model_admin)
                field_empty_value = display_metadata["empty_value_display"] or empty_value
                cells[field] = field_empty_value if value in (None, "") else value
            rows.append({"id": obj.pk, "cells": cells})
        action_form = [
            {
                "name": "action",
                "type": "ChoiceField",
                "attrs": {
                    "required": True,
                    "choices": [
                        (item["action"], str(item["description"]))
                        for item in model_admin.get_action_choices(request)
                    ],
                },
            },
            {"name": "selected_ids", "type": "MultipleChoiceField", "attrs": {"required": False}},
            {"name": "select_across", "type": "BooleanField", "attrs": {"required": False}},
        ]
        list_editing_formset = []
        if model_admin.list_editable:
            for obj in changelist.result_list:
                field_descriptions = model_admin.get_form_fields_description(request, obj)
                list_editing_formset.append(
                    [field for field in field_descriptions if field["name"] in model_admin.list_editable]
                )
        model_field_names = [
            field for field in list_display if self._model_has_field(model_admin.model, field)
        ]
        payload = {
            "columns": columns,
            "rows": rows,
            "config": {
                "full_count": changelist.full_result_count,
                "result_count": changelist.result_count,
                "page_count": changelist.paginator.num_pages,
                "page": changelist.page_num,
                "per_page": changelist.per_page,
                "has_next": changelist.page.has_next(),
                "has_previous": changelist.page.has_previous(),
                "show_all": changelist.show_all,
                "can_show_all": changelist.can_show_all_results,
                "show_facets": changelist.show_facets,
                "actions_on_top": bool(model_admin.actions_on_top),
                "actions_on_bottom": bool(model_admin.actions_on_bottom),
                "actions_selection_counter": bool(model_admin.actions_selection_counter),
                "action_choices": model_admin.get_action_choices(request),
                "filters": changelist.filter_descriptions(),
                "date_hierarchy": changelist.date_hierarchy_description(),
                "list_display_fields": model_field_names,
                "list_display_links": list(changelist.list_display_links or ()),
                "ordering_field_columns": changelist.ordering_field_columns,
                "ordering": changelist.ordering,
                "search_fields": list(changelist.search_fields),
                "search_help_text": model_admin.search_help_text,
            },
            "action_form": action_form,
            "list_editing_formset": list_editing_formset,
        }
        return ChangelistResponse.model_validate(payload).model_dump(mode="json")

    def _model_has_field(self, model, field):
        try:
            model._meta.get_field(field)
            return True
        except Exception:
            return False

    def _filter_descriptions(self, request, model_admin):
        filters = []
        for field_name in model_admin.get_list_filter(request):
            if not isinstance(field_name, str):
                continue
            try:
                field = model_admin.model._meta.get_field(field_name)
            except Exception:
                continue
            current = request.GET.get(field_name)
            values = (
                model_admin.get_queryset(request)
                .order_by(field_name)
                .values_list(field_name, flat=True)
                .distinct()
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
            inline_desc = {
                "model": f"{inline.model._meta.app_label}.{inline.model._meta.model_name}",
                "readonly_fields": list(inline.get_readonly_fields(request, obj)),
                "fieldsets": list(inline.get_fieldsets(request, obj)),
                "prepopulated": dict(inline.get_prepopulated_fields(request, obj)),
                "permissions": {
                    "has_add_permission": inline.has_add_permission(request, obj),
                    "has_change_permission": inline.has_change_permission(request, obj),
                    "has_delete_permission": inline.has_delete_permission(request, obj),
                    "has_view_permission": inline.has_view_permission(request, obj),
                },
                "extra": inline.extra,
                "min_num": inline.min_num,
                "max_num": inline.max_num,
                "verbose_name": str(inline.verbose_name),
                "verbose_name_plural": str(inline.verbose_name_plural),
                "can_delete": inline.can_delete,
                "show_change_link": inline.show_change_link,
                "admin_style": inline.admin_style,
                "formset": [],
            }
            if obj is not None:
                fk = _get_foreign_key(inline.parent_model, inline.model, fk_name=inline.fk_name)
                related_name = fk.remote_field.accessor_name
                try:
                    related_instances = getattr(obj, related_name).all()
                except AttributeError:
                    related_instances = []
                for instance in related_instances:
                    inline_desc["formset"].append(inline.get_form_fields_description(request, instance))
            inline_desc["formset"].append(inline.get_form_fields_description(request, None))
            inlines.append(inline_desc)
        data["inlines"] = inlines
        return FormResponse.model_validate(data).model_dump(mode="json")

    def _payload_data(self, payload, *, exclude_unset=True):
        data = getattr(payload, "data", {})
        if hasattr(data, "model_dump"):
            return data.model_dump(mode="json", exclude_unset=exclude_unset)
        return data

    def _payload_inlines(self, payload):
        inlines = getattr(payload, "inlines", None)
        if hasattr(inlines, "model_dump"):
            return inlines.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_unset=True)
        return inlines

    def _normalize_file_clear_data(self, form_class, data):
        normalized = dict(data)
        for field_name, field in form_class.base_fields.items():
            if isinstance(field, forms.FileField) and field_name in normalized and normalized[field_name] is None:
                normalized.pop(field_name)
                normalized[f"{field_name}-clear"] = "on"
        return normalized

    def _create_object(self, request, model_admin, payload, *, files=None):
        if not model_admin.has_add_permission(request):
            raise PermissionDenied
        with transaction.atomic(using=router_db_for_write(model_admin.model)):
            form_class = model_admin.get_form_class(request, None, change=False)
            form_data = self._normalize_file_clear_data(form_class, self._payload_data(payload))
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
            return Status(201, model_admin.response_add(request, obj, form, inline_results))

    def _file_form_field_names(self, model_admin, request=None, obj=None, *, change):
        form_class = model_admin.get_form_class(request, obj, change=change)
        return [name for name, field in form_class.base_fields.items() if isinstance(field, forms.FileField)]

    def _multipart_openapi_extra(self, payload_schema, file_fields, *, required_data):
        properties = {
            "data": {
                "type": "string",
                "description": f"JSON object matching {payload_schema.__name__}.data.",
            },
            "inlines": {
                "type": "string",
                "description": f"Optional JSON object matching {payload_schema.__name__}.inlines.",
            },
        }
        for field_name in file_fields:
            properties[field_name] = {"type": "string", "format": "binary"}
        schema = {"type": "object", "properties": properties}
        if required_data:
            schema["required"] = ["data"]
        return {"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": schema}}}}

    def _multipart_mutation_payload(self, request, payload_schema):
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

    def _json_form_part(self, request, name, *, default):
        form_data, _files = self._multipart_request_parts(request)
        if name not in form_data:
            return default
        raw_value = form_data.get(name)
        if raw_value in ("", None):
            return default
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            raise NinjaValidationError(
                [
                    {
                        "loc": ("body", "payload", name),
                        "msg": "Input should be valid JSON",
                        "type": "json_invalid",
                    }
                ]
            )

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
            except MultiPartParserError:
                raise NinjaValidationError(
                    [
                        {
                            "loc": ("body", "payload"),
                            "msg": "Input should be valid multipart form data",
                            "type": "multipart_invalid",
                        }
                    ]
                )
        setattr(request, cache_name, parts)
        return parts

    def _multipart_form_files(self, request, form_class):
        _form_data, files = self._multipart_request_parts(request)
        return {
            name: files[name]
            for name, field in form_class.base_fields.items()
            if isinstance(field, forms.FileField) and name in files
        }

    def _update_object(self, request, model_admin, object_id, payload, *, partial, files=None, obj=None):
        obj = obj or self._get_object_or_404(request, model_admin, object_id)
        if not model_admin.has_change_permission(request, obj):
            raise PermissionDenied
        with transaction.atomic(using=router_db_for_write(model_admin.model)):
            form_class = model_admin.get_form_class(request, obj, change=True)
            form_data = self._payload_data(payload, exclude_unset=partial)
            if partial:
                current = model_data_for_form(obj, list(form_class.base_fields.keys()))
                current.update(form_data)
                form_data = current
            form_data = self._normalize_file_clear_data(form_class, form_data)
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
            model_admin.log_change(request, updated_object, change_message)
            return model_admin.response_change(request, updated_object, form, inline_results)

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
                raise AdminValidationError({inline_id: [{"message": "Unknown inline.", "param": "non_field_errors"}]})
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
                            "message": f"Unknown inline operation: {', '.join(sorted(unknown_operations))}.",
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
                        "delete": [{"message": "Inline deletion is not allowed.", "param": "delete"}]
                    }
                }
            )

        formset_class = inline.get_formset(request, obj, change=change)
        editable_fields = set(formset_class.form.base_fields)
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
                    message="Duplicate inline delete pk.",
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
                    message="Missing pk.",
                    param="pk",
                )
                continue
            pk = str(pk)
            if pk in seen_change_pks:
                self._add_inline_row_error(
                    inline_errors,
                    "change",
                    index,
                    message="Duplicate inline change pk.",
                    param="pk",
                )
                has_row_error = True
            seen_change_pks.add(pk)
            if pk not in existing_by_pk:
                self._add_inline_row_error(
                    inline_errors,
                    "change",
                    index,
                    message="Unknown inline object.",
                    param="pk",
                )
                has_row_error = True
            if pk in delete_pks and pk in existing_by_pk:
                self._add_inline_row_error(
                    inline_errors,
                    "change",
                    index,
                    message="Inline object cannot be changed and deleted in the same request.",
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
                    message="Unknown inline object.",
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
            {"id": existing_by_pk[pk].pk, "_object_repr": str(existing_by_pk[pk])}
            for pk in delete_values
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
                    message="Unknown or readonly inline field.",
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
        editable_fields = set(formset_class.form.base_fields)
        pk_name = inline.model._meta.pk.name
        fk = _get_foreign_key(inline.parent_model, inline.model, fk_name=inline.fk_name)
        for index, instance in enumerate(existing_instances):
            pk = str(instance.pk)
            row = model_data_for_form(instance, list(editable_fields))
            row.update(changes_by_pk.get(pk, {}))
            self._copy_inline_form_row(formset_data, prefix, index, row, editable_fields)
            formset_data[f"{prefix}-{index}-{pk_name}"] = pk
            formset_data[f"{prefix}-{index}-{fk.name}"] = str(obj.pk)
            if pk in delete_pks:
                formset_data[f"{prefix}-{index}-DELETE"] = "on"
        for offset, row in enumerate(add_rows, start=len(existing_instances)):
            self._copy_inline_form_row(formset_data, prefix, offset, row, editable_fields)
            formset_data[f"{prefix}-{offset}-{fk.name}"] = str(obj.pk)
        return formset_data

    def _copy_inline_form_row(self, formset_data, prefix, index, row, editable_fields):
        for name, value in row.items():
            if name in {"pk", "id"} or name not in editable_fields:
                continue
            formset_data[f"{prefix}-{index}-{name}"] = value

    def _bulk_update(self, request, model_admin, payload):
        payload_data = [
            item.model_dump(mode="json", exclude_unset=True) if hasattr(item, "model_dump") else item
            for item in payload.data
        ]
        if not payload_data:
            raise AdminValidationError([{"message": "Change data cannot be empty.", "param": "data"}])
        validated_rows = []
        row_errors = {}
        seen_pks = set()
        allowed = set(model_admin.list_editable) | {"pk", model_admin.model._meta.pk.name}
        for idx, data in enumerate(payload_data):
            pk = data.get("pk") or data.get(model_admin.model._meta.pk.name)
            if pk is None:
                row_errors[idx] = [{"message": "This field is required.", "param": "pk"}]
                continue
            pk_key = str(pk)
            if pk_key in seen_pks:
                row_errors[idx] = [{"message": "Duplicate object in bulk update.", "param": "pk"}]
                continue
            seen_pks.add(pk_key)
            unknown_fields = sorted(set(data) - allowed)
            if unknown_fields:
                row_errors[idx] = [
                    {
                        "message": f"Field is not list editable: {', '.join(unknown_fields)}.",
                        "param": unknown_fields[0],
                    }
                ]
                continue
            obj = model_admin.get_object(request, pk)
            if obj is None:
                row_errors[idx] = [{"message": "Object not found.", "param": "pk"}]
                continue
            if not model_admin.has_change_permission(request, obj):
                raise PermissionDenied
            form_class = model_admin.get_form_class(request, obj, change=True)
            current = model_data_for_form(obj, list(form_class.base_fields.keys()))
            current.update({key: value for key, value in data.items() if key in allowed})
            current = self._normalize_file_clear_data(form_class, current)
            form = form_class(data=current, instance=obj)
            if not form.is_valid():
                row_errors[idx] = form_errors(form)
                continue
            validated_rows.append((idx, obj, form))
        if row_errors:
            raise AdminValidationError(row_errors)

        results = {}
        with transaction.atomic(using=router_db_for_write(model_admin.model)):
            for idx, obj, form in validated_rows:
                if form.has_changed():
                    updated = model_admin.save_form(request, form, change=True)
                    model_admin.save_model(request, updated, form, change=True)
                    model_admin.save_related(request, form, {}, change=True)
                    model_admin.log_change(request, updated, model_admin.construct_change_message(request, form))
                    obj = updated
                results[idx] = model_admin.serialize_object(obj, request)
        return {"data": results}


def router_db_for_write(model):
    return router.db_for_write(model)


class DefaultAdminSite(LazyObject):
    def _setup(self):
        AdminSiteClass = import_string(apps.get_app_config("django_ninja_admin").default_site)
        self._wrapped = AdminSiteClass(name="ninja_admin")

    def __repr__(self):
        return repr(self._wrapped)


site = DefaultAdminSite()
