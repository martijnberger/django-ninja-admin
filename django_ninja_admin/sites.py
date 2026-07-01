import json
from typing import Any
from weakref import WeakSet

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.shortcuts import get_current_site
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.paginator import InvalidPage, Paginator
from django.db import router, transaction
from django.db.models.base import ModelBase
from django.forms.models import _get_foreign_key
from django.http import Http404
from django.utils.functional import LazyObject
from django.utils.module_loading import import_string
from django.utils.text import capfirst
from ninja import NinjaAPI, Query, Router, Status
from ninja.errors import AuthenticationError, AuthorizationError, HttpError
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
from django_ninja_admin.schemas import (
    ActionPayload,
    AppSummary,
    AutocompleteResponse,
    BulkPayload,
    ChangelistResponse,
    ErrorResponse,
    FormResponse,
    HistoryResponse,
    MutationPayload,
    MutationResponse,
    SiteContext,
    ViewOnSiteResponse,
)
from django_ninja_admin.utils.format_error import format_error
from django_ninja_admin.utils.forms import form_errors, model_data_for_form
from django_ninja_admin.utils.lookup import label_for_field, lookup_field
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

    def disable_action(self, name):
        del self._actions[name]

    def get_action(self, name):
        return self._global_actions[name]

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
        for model, model_admin in self._registry.items():
            self._register_model_routes(router, model, model_admin)
        api.add_router("", router)
        return api

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

        @api.exception_handler(MissingSearchFields)
        def missing_search_fields(request, exc):
            return error_response(request, "Missing search_fields.", 409, param="search_fields")

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
            o: str = "-action_time",
            page: int = 1,
        ):
            from django_ninja_admin.models import LogEntry

            if o not in {"action_time", "-action_time"}:
                raise AdminValidationError([{"message": "Invalid ordering provided.", "param": "o"}])
            qs = LogEntry.objects.all().order_by(o).select_related("content_type")
            if app_label and model:
                model_class = apps.get_model(app_label, model)
                qs = qs.filter(content_type=ContentType.objects.get_for_model(model_class))
            if object_id is not None:
                qs = qs.filter(object_id=object_id)
            paginator = site.paginator(qs, 20)
            page_obj = paginator.page(page)
            results = []
            for item in page_obj.object_list:
                if item.content_type and item.content_type.model_class():
                    try:
                        model_admin = site.get_model_admin(item.content_type.model_class())
                        if not model_admin.has_view_or_change_permission(request):
                            raise PermissionDenied
                    except NotRegistered:
                        pass
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
            source_model = apps.get_model(app_label, model_name)
            try:
                source_field = source_model._meta.get_field(field_name)
                remote_model = source_field.remote_field.model
                model_admin = site.get_model_admin(remote_model)
            except Exception:
                raise Http404
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
            page_obj = paginator.page(page)
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
                if not content_type.model_class():
                    raise Http404
                obj = content_type.get_object_for_this_type(pk=object_id)
            except (ObjectDoesNotExist, ValueError, ValidationError):
                raise Http404
            if not hasattr(obj, "get_absolute_url"):
                return Status(409, {"errors": [{"message": "Object has no get_absolute_url().", "param": "object_id"}]})
            absurl = obj.get_absolute_url()
            if absurl.startswith(("http://", "https://", "//")):
                return {"url": absurl}
            try:
                object_domain = get_current_site(request).domain
            except ObjectDoesNotExist:
                object_domain = None
            if object_domain is not None:
                return {"url": f"{request.scheme}://{object_domain}{absurl}"}
            return {"url": absurl}

    def _register_model_routes(self, router, model, model_admin):
        site = self
        app_label = model._meta.app_label
        model_name = model._meta.model_name
        prefix = f"/{app_label}/{model_name}"
        tags = [f"{app_label}.{model_name}"]

        @router.get(prefix, response=ChangelistResponse, tags=tags, operation_id=f"{app_label}_{model_name}_list")
        def changelist(request):
            return site._changelist_response(request, model_admin)

        @router.get(
            f"{prefix}/form",
            response=FormResponse,
            tags=tags,
            operation_id=f"{app_label}_{model_name}_add_form",
        )
        def add_form(request):
            if not model_admin.has_add_permission(request):
                raise PermissionDenied
            return site._form_response(request, model_admin, None)

        @router.post(
            prefix,
            response={201: MutationResponse, 400: ErrorResponse, 403: ErrorResponse},
            tags=tags,
            operation_id=f"{app_label}_{model_name}_create",
        )
        def create(request, payload: MutationPayload):
            if not model_admin.has_add_permission(request):
                raise PermissionDenied
            with transaction.atomic(using=router_db_for_write(model_admin.model)):
                form_class = model_admin.get_form_class(request, None, change=False)
                form = form_class(data=payload.data)
                if not form.is_valid():
                    raise AdminValidationError({"form": form_errors(form)})
                obj = model_admin.save_form(request, form, change=False)
                model_admin.save_model(request, obj, form, change=False)
                inline_results = site._process_inlines(
                    request,
                    model_admin,
                    obj,
                    payload.inlines or {},
                    change=False,
                )
                model_admin.save_related(request, form, inline_results, change=False)
                change_message = model_admin.construct_change_message(request, form, inline_results, add=True)
                model_admin.log_addition(request, obj, change_message)
                return Status(201, model_admin.response_add(request, obj, form, inline_results))

        @router.post(
            f"{prefix}/actions",
            response={200: dict[str, Any], 400: ErrorResponse, 403: ErrorResponse},
            tags=tags,
            operation_id=f"{app_label}_{model_name}_action",
        )
        def actions_view(request, payload: ActionPayload):
            cl_queryset = site._filtered_queryset(request, model_admin)
            return model_admin.response_action(request, cl_queryset, payload)

        @router.put(
            f"{prefix}/bulk",
            response={200: dict[str, Any], 400: ErrorResponse, 403: ErrorResponse},
            tags=tags,
            operation_id=f"{app_label}_{model_name}_bulk_update",
        )
        def bulk_update(request, payload: BulkPayload):
            if not model_admin.has_change_permission(request):
                raise PermissionDenied
            return site._bulk_update(request, model_admin, payload)

        @router.get(
            f"{prefix}/{{object_id}}",
            response=model_admin.get_output_schema(None),
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
            response=FormResponse,
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
            response={200: MutationResponse, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
            tags=tags,
            operation_id=f"{app_label}_{model_name}_partial_update",
        )
        def update(request, object_id: str, payload: MutationPayload):
            return site._update_object(request, model_admin, object_id, payload, partial=True)

        @router.put(
            f"{prefix}/{{object_id}}",
            response={200: MutationResponse, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
            tags=tags,
            operation_id=f"{app_label}_{model_name}_update",
        )
        def replace(request, object_id: str, payload: MutationPayload):
            return site._update_object(request, model_admin, object_id, payload, partial=False)

        @router.delete(
            f"{prefix}/{{object_id}}",
            response={204: None, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 409: ErrorResponse},
            tags=tags,
            operation_id=f"{app_label}_{model_name}_delete",
        )
        def delete(request, object_id: str, to_field: str | None = Query(None, alias="_to_field")):
            obj = site._get_object_or_404(request, model_admin, object_id, to_field)
            if not model_admin.has_delete_permission(request, obj):
                raise PermissionDenied
            deleted_objects, model_count, perms_needed, protected = model_admin.get_deleted_objects([obj], request)
            if protected:
                return Status(409, {"errors": [{"message": "Cannot delete protected objects.", "param": "object_id"}]})
            if perms_needed:
                raise PermissionDenied
            with transaction.atomic(using=router_db_for_write(model_admin.model)):
                model_admin.log_deletion(request, [obj])
                model_admin.delete_model(request, obj)
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
        qs = model_admin.get_queryset(request)
        if model_admin.get_list_select_related(request):
            qs = qs.select_related(*model_admin.get_list_select_related(request))
        params = request.GET
        reserved = {"q", "p", "pp", "all", "o", "page"}
        for key, value in params.items():
            if key in reserved or value in ("", None):
                continue
            if not model_admin.lookup_allowed(key, value, request):
                raise DisallowedModelAdminLookup(f"Filtering by {key!r} is not allowed.")
            qs = qs.filter(**{key: value})
        search_term = params.get("q")
        if search_term:
            qs, use_distinct = model_admin.get_search_results(request, qs, search_term)
            if use_distinct:
                qs = qs.distinct()
        ordering = params.get("o")
        if ordering:
            fields = [field.strip() for field in ordering.split(",") if field.strip()]
            sortable = set(model_admin.get_sortable_by(request))
            safe_ordering = []
            for field in fields:
                bare = field.removeprefix("-")
                if bare in sortable:
                    safe_ordering.append(field)
            if safe_ordering:
                qs = qs.order_by(*safe_ordering)
        return qs

    def _changelist_response(self, request, model_admin):
        if not model_admin.has_view_or_change_permission(request):
            raise PermissionDenied
        qs = self._filtered_queryset(request, model_admin)
        full_count = model_admin.get_queryset(request).count()
        result_count = qs.count()
        per_page = int(request.GET.get("pp") or model_admin.list_per_page)
        page_number = int(request.GET.get("p") or request.GET.get("page") or 1)
        paginator = model_admin.paginator(qs, per_page)
        page = paginator.page(page_number)
        list_display = tuple(model_admin.get_list_display(request))
        columns = [
            {"field": field, "headerName": label_for_field(field, model_admin.model, model_admin)}
            for field in list_display
        ]
        rows = []
        empty_value = model_admin.get_empty_value_display()
        for obj in page.object_list:
            cells = {}
            for field in list_display:
                value = lookup_field(field, obj, model_admin)
                cells[field] = empty_value if value is None else value
            rows.append({"id": obj.pk, "cells": cells})
        filters = self._filter_descriptions(request, model_admin)
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
            for obj in page.object_list:
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
                "full_count": full_count,
                "result_count": result_count,
                "page_count": paginator.num_pages,
                "page": page_number,
                "per_page": per_page,
                "action_choices": model_admin.get_action_choices(request),
                "filters": filters,
                "list_display_fields": model_field_names,
                "ordering_field_columns": {field: field for field in model_field_names},
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

    def _update_object(self, request, model_admin, object_id, payload, *, partial):
        obj = self._get_object_or_404(request, model_admin, object_id)
        if not model_admin.has_change_permission(request, obj):
            raise PermissionDenied
        with transaction.atomic(using=router_db_for_write(model_admin.model)):
            form_class = model_admin.get_form_class(request, obj, change=True)
            form_data = payload.data
            if partial:
                current = model_data_for_form(obj, list(form_class.base_fields.keys()))
                current.update(form_data)
                form_data = current
            form = form_class(data=form_data, instance=obj)
            if not form.is_valid():
                raise AdminValidationError({"form": form_errors(form)})
            updated_object = model_admin.save_form(request, form, change=True)
            model_admin.save_model(request, updated_object, form, change=True)
            inline_results = self._process_inlines(
                request,
                model_admin,
                updated_object,
                payload.inlines or {},
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
            for inline in model_admin.get_inline_instances(request, obj)
        }
        for inline_id, operations in inline_payload.items():
            if inline_id not in inline_by_id:
                raise AdminValidationError({inline_id: [{"message": "Unknown inline.", "param": "non_field_errors"}]})
            inline = inline_by_id[inline_id]
            fk = _get_foreign_key(inline.parent_model, inline.model, fk_name=inline.fk_name)
            related_name = fk.remote_field.accessor_name
            related_manager = getattr(obj, related_name, None)
            results[inline_id] = {"add": [], "change": [], "delete": []}
            for data in operations.get("add", []):
                if not inline.has_add_permission(request, obj):
                    raise PermissionDenied
                data = {**data, fk.name: obj.pk}
                form_class = inline.get_form_class(request, None, change=False)
                form = form_class(data=data)
                if not form.is_valid():
                    raise AdminValidationError({inline_id: {"add": form_errors(form)}})
                instance = form.save()
                results[inline_id]["add"].append(inline.serialize_object(instance, request))
            for data in operations.get("change", []):
                if not inline.has_change_permission(request, obj):
                    raise PermissionDenied
                pk = data.get("pk") or data.get(inline.model._meta.pk.name)
                if pk is None:
                    raise AdminValidationError({inline_id: {"change": [{"message": "Missing pk.", "param": "pk"}]}})
                instance_qs = related_manager.all() if related_manager is not None else inline.model.objects.none()
                try:
                    instance = instance_qs.get(pk=pk)
                except inline.model.DoesNotExist:
                    raise AdminValidationError(
                        {inline_id: {"change": [{"message": "Unknown inline object.", "param": "pk"}]}}
                    )
                form_class = inline.get_form_class(request, instance, change=True)
                current = model_data_for_form(instance, list(form_class.base_fields.keys()))
                current.update(data)
                current[fk.name] = obj.pk
                form = form_class(data=current, instance=instance)
                if not form.is_valid():
                    raise AdminValidationError({inline_id: {"change": form_errors(form)}})
                form.save()
                results[inline_id]["change"].append(inline.serialize_object(instance, request))
            for pk in operations.get("delete", []):
                if not inline.has_delete_permission(request, obj):
                    raise PermissionDenied
                instance_qs = related_manager.all() if related_manager is not None else inline.model.objects.none()
                try:
                    instance = instance_qs.get(pk=pk)
                except inline.model.DoesNotExist:
                    raise AdminValidationError(
                        {inline_id: {"delete": [{"message": "Unknown inline object.", "param": "pk"}]}}
                    )
                instance.delete()
                results[inline_id]["delete"].append(pk)
        return results

    def _bulk_update(self, request, model_admin, payload):
        if not payload.data:
            raise AdminValidationError([{"message": "Change data cannot be empty.", "param": "data"}])
        results = {}
        for idx, data in enumerate(payload.data):
            pk = data.get("pk") or data.get(model_admin.model._meta.pk.name)
            if pk is None:
                raise AdminValidationError({idx: [{"message": "This field is required.", "param": "pk"}]})
            obj = model_admin.get_object(request, pk)
            if obj is None:
                raise AdminValidationError({idx: [{"message": "Object not found.", "param": "pk"}]})
            form_class = model_admin.get_form_class(request, obj, change=True)
            allowed = set(model_admin.list_editable) | {"pk", model_admin.model._meta.pk.name}
            current = model_data_for_form(obj, list(form_class.base_fields.keys()))
            current.update({key: value for key, value in data.items() if key in allowed})
            form = form_class(data=current, instance=obj)
            if not form.is_valid():
                raise AdminValidationError({idx: form_errors(form)})
            with transaction.atomic(using=router_db_for_write(model_admin.model)):
                updated = model_admin.save_form(request, form, change=True)
                model_admin.save_model(request, updated, form, change=True)
                model_admin.save_related(request, form, {}, change=True)
                model_admin.log_change(request, updated, model_admin.construct_change_message(request, form))
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
