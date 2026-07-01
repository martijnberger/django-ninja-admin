import enum
import re
from functools import reduce, wraps
from operator import or_
from typing import Annotated, Any, Literal

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist, PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import models
from django.db.models.constants import LOOKUP_SEP
from django.forms.models import model_to_dict
from django.utils.text import capfirst, smart_split, unescape_string_literal
from django.utils.translation import gettext_lazy as _
from ninja import Schema
from pydantic import BaseModel, Field, RootModel, TypeAdapter, create_model
from pydantic import ValidationError as PydanticValidationError

from django_ninja_admin.admins.base import BaseAdmin
from django_ninja_admin.exceptions import AdminValidationError
from django_ninja_admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django_ninja_admin.routes import AdminRoute
from django_ninja_admin.schemas import AdminInlinePayloadSchema
from django_ninja_admin.utils.deletion import get_deleted_objects

HORIZONTAL, VERTICAL = 1, 2
DEFAULT_ROUTE_AUTH = object()


class ShowFacets(enum.Enum):
    NEVER = "NEVER"
    ALLOW = "ALLOW"
    ALWAYS = "ALWAYS"


class ModelAdmin(BaseAdmin):
    list_display = ("__str__",)
    list_display_links = ()
    list_filter = ()
    list_select_related = False
    list_per_page = 100
    list_max_show_all = 200
    list_editable = ()
    search_fields = ()
    search_help_text = None
    date_hierarchy = None
    save_as = False
    save_as_continue = True
    save_on_top = False
    paginator = Paginator
    show_facets = ShowFacets.ALLOW
    inlines = ()
    actions = ()
    actions_on_top = True
    actions_on_bottom = False
    actions_selection_counter = True

    changelist_options = [
        "actions_on_top",
        "actions_on_bottom",
        "actions_selection_counter",
        "empty_value_display",
        "list_display",
        "list_display_links",
        "list_editable",
        "exclude",
        "show_full_result_count",
        "list_per_page",
        "list_max_show_all",
        "date_hierarchy",
        "search_help_text",
        "sortable_by",
        "search_fields",
    ]

    def __init__(self, model, admin_site):
        self.model = model
        self.opts = model._meta
        self.admin_site = admin_site
        self.paginator = self.paginator or admin_site.paginator

    def __repr__(self):
        return f"<{self.__class__.__qualname__}: model={self.model.__qualname__} site={self.admin_site!r}>"

    def get_inline_instances(self, request, obj=None, *, check_permissions=True):
        inline_instances = []
        for inline_class in self.inlines:
            inline = inline_class(self.model, self.admin_site)
            if request is not None and check_permissions:
                if not (
                    inline.has_view_or_change_permission(request, obj)
                    or inline.has_add_permission(request, obj)
                    or inline.has_delete_permission(request, obj)
                ):
                    continue
                if not inline.has_add_permission(request, obj):
                    inline.max_num = 0
            inline_instances.append(inline)
        return inline_instances

    def admin_view(self, view_func):
        @wraps(view_func)
        def inner(request, *args, **kwargs):
            if not self.has_view_or_change_permission(request):
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
        auth=DEFAULT_ROUTE_AUTH,
        include_in_schema=True,
    ):
        route_auth = self.admin_site.auth if auth is DEFAULT_ROUTE_AUTH else auth
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

    def get_inline_payload_schema(self, request=None, obj=None, *, change=False, partial=False):
        cache = getattr(self, "_inline_payload_schema_cache", {})
        inline_instances = self.get_inline_instances(request, obj)
        cache_key = (
            "inline-payload",
            tuple(f"{inline.model._meta.app_label}.{inline.model._meta.model_name}" for inline in inline_instances),
            change,
            partial,
        )
        if cache_key not in cache:
            fields = {}
            for inline in inline_instances:
                inline_id = f"{inline.model._meta.app_label}.{inline.model._meta.model_name}"
                field_name = inline_id.replace(".", "_")
                fields[field_name] = (
                    inline.get_inline_operations_schema(request, obj, change=change) | None,
                    Field(default=None, alias=inline_id),
                )
            cache[cache_key] = create_model(
                f"{self.model.__name__}AdminInlinePayload",
                __base__=AdminInlinePayloadSchema,
                **fields,
            )
            self._inline_payload_schema_cache = cache
        return cache[cache_key]

    def get_mutation_payload_schema(self, request=None, obj=None, *, change=False, partial=False):
        cache = getattr(self, "_mutation_payload_schema_cache", {})
        cache_key = ("model-mutation", change, partial)
        if cache_key not in cache:
            data_schema = self.get_write_schema(request, obj, change=change, partial=partial)
            inline_payload_schema = self.get_inline_payload_schema(request, obj, change=change, partial=partial)
            operation = "PartialUpdate" if partial else "Update" if change else "Create"
            cache[cache_key] = create_model(
                f"{self.model.__name__}Admin{operation}Payload",
                __base__=Schema,
                data=(data_schema, ...),
                inlines=(inline_payload_schema | None, None),
            )
            self._mutation_payload_schema_cache = cache
        return cache[cache_key]

    def get_model_perms(self, request):
        return {
            "has_add_permission": self.has_add_permission(request),
            "has_change_permission": self.has_change_permission(request),
            "has_delete_permission": self.has_delete_permission(request),
            "has_view_permission": self.has_view_permission(request),
        }

    def get_object(self, request, object_id, from_field=None):
        queryset = self.get_queryset(request)
        field = queryset.model._meta.pk if from_field is None else queryset.model._meta.get_field(from_field)
        try:
            object_id = field.to_python(object_id)
            return queryset.get(**{field.name: object_id})
        except (queryset.model.DoesNotExist, ValidationError, ValueError):
            return None

    def get_list_display(self, request):
        return self.list_display

    def get_list_display_links(self, request, list_display):
        if self.list_display_links or self.list_display_links is None or not list_display:
            return self.list_display_links
        return list(list_display)[:1]

    def get_list_filter(self, request):
        return self.list_filter

    def get_list_select_related(self, request):
        return self.list_select_related

    def get_changelist(self, request, **kwargs):
        from django_ninja_admin.changelist import ChangeList

        return ChangeList

    def get_changelist_instance(self, request, **kwargs):
        return self.get_changelist(request, **kwargs)(request, self)

    def get_search_fields(self, request):
        return self.search_fields

    def get_search_results(self, request, queryset, search_term):
        def construct_search(field_name):
            if field_name.startswith("^"):
                return f"{field_name.removeprefix('^')}__istartswith", None, False
            if field_name.startswith("="):
                return f"{field_name.removeprefix('=')}__iexact", None, False
            if field_name.startswith("@"):
                return f"{field_name.removeprefix('@')}__search", None, False
            opts = queryset.model._meta
            prev_field = None
            may_have_duplicates = False
            for path_part in field_name.split(LOOKUP_SEP):
                if path_part == "pk":
                    path_part = opts.pk.name
                try:
                    field = opts.get_field(path_part)
                except FieldDoesNotExist:
                    if prev_field and prev_field.get_lookup(path_part):
                        return field_name, prev_field if path_part == "exact" else None, may_have_duplicates
                    return f"{field_name}__icontains", None, may_have_duplicates
                prev_field = field
                if hasattr(field, "path_infos"):
                    may_have_duplicates = may_have_duplicates or any(
                        path_info.m2m for path_info in field.path_infos
                    )
                    opts = field.path_infos[-1].to_opts
            return f"{field_name}__icontains", None, may_have_duplicates

        may_have_duplicates = False
        search_fields = self.get_search_fields(request)
        if search_fields and search_term:
            orm_lookups = [construct_search(str(field)) for field in search_fields]
            may_have_duplicates = any(lookup_may_have_duplicates for _, _, lookup_may_have_duplicates in orm_lookups)
            term_queries = []
            for bit in smart_split(search_term):
                if bit.startswith(('"', "'")) and bit[0] == bit[-1]:
                    bit = unescape_string_literal(bit)
                bit_lookups = []
                for orm_lookup, validate_field, _lookup_may_have_duplicates in orm_lookups:
                    if validate_field is not None:
                        formfield = validate_field.formfield()
                        try:
                            value = formfield.to_python(bit) if formfield is not None else validate_field.to_python(bit)
                        except ValidationError:
                            continue
                    else:
                        value = bit
                    bit_lookups.append((orm_lookup, value))
                if bit_lookups:
                    term_queries.append(models.Q.create(bit_lookups, connector=models.Q.OR))
                else:
                    term_queries.append(models.Q(pk__in=[]))
            queryset = queryset.filter(models.Q.create(term_queries))
        return queryset, may_have_duplicates

    @staticmethod
    def _get_action_description(func, name):
        return getattr(func, "short_description", capfirst(name.replace("_", " ")))

    def _get_base_actions(self):
        actions = []
        base_actions = (self.get_action(action) for action in self.actions or [])
        base_actions = [action for action in base_actions if action]
        base_action_names = {name for _, name, _ in base_actions}
        for name, func in self.admin_site.actions:
            if name not in base_action_names:
                actions.append((func, name, self._get_action_description(func, name)))
        actions.extend(base_actions)
        return actions

    def _filter_actions_by_permissions(self, request, actions):
        filtered = []
        for action in actions:
            func = action[0]
            if not hasattr(func, "allowed_permissions"):
                filtered.append(action)
                continue
            checks = (getattr(self, f"has_{permission}_permission") for permission in func.allowed_permissions)
            if any(check(request) for check in checks):
                filtered.append(action)
        return filtered

    def get_actions(self, request):
        if self.actions is None:
            return {}
        actions = self._filter_actions_by_permissions(request, self._get_base_actions())
        return {name: (func, name, desc) for func, name, desc in actions}

    def get_action_choices(self, request, default_choices=()):
        choices = [
            {"action": name, "description": str(desc)}
            for _, name, desc in self.get_actions(request).values()
        ]
        return [*default_choices, *choices]

    def get_action(self, action):
        if callable(action):
            func = action
            action = action.__name__
        elif hasattr(self.__class__, action):
            func = getattr(self.__class__, action)
        else:
            try:
                func = self.admin_site.get_action(action)
            except KeyError:
                return None
        return func, action, self._get_action_description(func, action)

    def get_action_payload_schema(self, request=None):
        cache = getattr(self, "_action_payload_schema_cache", {})
        actions = self._get_base_actions()
        action_signatures = tuple((name, getattr(func, "action_input_schema", None)) for func, name, _desc in actions)
        cache_key = ("action-payload", action_signatures)
        if cache_key not in cache:
            variants = tuple(self._action_payload_variant_schema(func, name) for func, name, _desc in actions)
            cache[cache_key] = self._action_payload_root_schema(variants)
            self._action_payload_schema_cache = cache
        return cache[cache_key]

    def _action_payload_root_schema(self, variants):
        if not variants:
            return create_model(
                f"{self.model.__name__}AdminActionPayload",
                __base__=Schema,
                action=(str, ...),
                selected_ids=(list[Any], Field(default_factory=list)),
                select_across=(bool, False),
                data=(dict[str, Any] | None, None),
            )
        union_type = self._union_type(variants)
        discriminated_union = Annotated[union_type, Field(discriminator="action")]
        return type(
            f"{self.model.__name__}AdminActionPayload",
            (RootModel[discriminated_union],),
            {"__module__": self.__class__.__module__},
        )

    def _action_payload_variant_schema(self, func, name):
        action_type = Literal.__getitem__(name)
        input_schema = getattr(func, "action_input_schema", None)
        fields = {
            "action": (action_type, ...),
            "selected_ids": (list[Any], Field(default_factory=list)),
            "select_across": (bool, False),
        }
        if input_schema is None:
            fields["data"] = (None, None)
        else:
            fields["data"] = (input_schema, ...)
        return create_model(
            f"{self.model.__name__}Admin{self._schema_name_part(name)}ActionPayload",
            __base__=Schema,
            **fields,
        )

    def get_action_response_schema(self, request=None):
        cache = getattr(self, "_action_response_schema_cache", {})
        actions = self._get_base_actions()
        action_response_schemas = self._action_schemas(actions, "action_response_schema")
        cache_key = ("action-response", action_response_schemas)
        if cache_key not in cache:
            if action_response_schemas:
                cache[cache_key] = self._union_type((*action_response_schemas, dict[str, Any]))
            else:
                cache[cache_key] = dict[str, Any]
            self._action_response_schema_cache = cache
        return cache[cache_key]

    def _action_schemas(self, actions, attr_name):
        return tuple(
            schema
            for schema in dict.fromkeys(
                getattr(func, attr_name, None)
                for func, _name, _description in actions
                if getattr(func, attr_name, None) is not None
            )
        )

    def _union_type(self, types):
        return reduce(or_, types)

    def _schema_name_part(self, value):
        parts = re.split(r"[^0-9A-Za-z]+", value)
        return "".join(part[:1].upper() + part[1:] for part in parts if part) or "Action"

    def construct_change_message(self, request, form, inline_results=None, add=False):
        inline_results = inline_results or {}
        if add:
            message = [{"added": {}}]
            message.extend(self._inline_change_messages(inline_results))
            return message
        changed = getattr(form, "changed_data", None) or []
        message = []
        if changed:
            message.append({"changed": {"fields": [self._form_field_label(form, field) for field in changed]}})
        message.extend(self._inline_change_messages(inline_results))
        return message

    def _form_field_label(self, form, field_name):
        field = form.fields.get(field_name)
        if field is not None and field.label:
            return str(field.label)
        try:
            return str(self.model._meta.get_field(field_name).verbose_name)
        except FieldDoesNotExist:
            return field_name.replace("_", " ")

    def _inline_change_messages(self, inline_results):
        messages = []
        for inline_id, results in inline_results.items():
            verbose_name = self._inline_verbose_name(inline_id)
            for item in results.get("add", []):
                messages.append({"added": {"name": verbose_name, "object": self._inline_object_repr(item)}})
            for item in results.get("change", []):
                fields = item.get("_changed_fields") or []
                messages.append(
                    {
                        "changed": {
                            "name": verbose_name,
                            "object": self._inline_object_repr(item),
                            "fields": fields,
                        }
                    }
                )
            for item in results.get("_delete_objects", results.get("delete", [])):
                messages.append({"deleted": {"name": verbose_name, "object": self._inline_object_repr(item)}})
        return messages

    def _inline_verbose_name(self, inline_id):
        try:
            app_label, model_name = inline_id.split(".", 1)
            return str(apps.get_model(app_label, model_name)._meta.verbose_name)
        except (LookupError, ValueError):
            return inline_id

    def _inline_object_repr(self, item):
        if isinstance(item, dict):
            return str(item.get("_object_repr") or item.get("title") or item.get("name") or item.get("id") or item)
        return str(item)

    def save_form(self, request, form, change):
        return form.save(commit=False)

    def save_model(self, request, obj, form, change):
        obj.save()

    def save_related(self, request, form, inline_results, change):
        form.save_m2m()

    def delete_model(self, request, obj):
        obj.delete()

    def delete_queryset(self, request, queryset):
        queryset.delete()

    def log_addition(self, request, obj, message):
        return LogEntry.objects.log_actions(
            user_id=request.user.pk, queryset=[obj], action_flag=ADDITION, change_message=message, single_object=True
        )

    def log_change(self, request, obj, message):
        return LogEntry.objects.log_actions(
            user_id=request.user.pk, queryset=[obj], action_flag=CHANGE, change_message=message, single_object=True
        )

    def log_deletion(self, request, queryset):
        return LogEntry.objects.log_actions(user_id=request.user.pk, queryset=queryset, action_flag=DELETION)

    def response_add(self, request, obj, form, inline_results):
        return {"data": self.serialize_object(obj, request), "inlines": self._public_inline_results(inline_results)}

    def response_change(self, request, obj, form, inline_results):
        return {"data": self.serialize_object(obj, request), "inlines": self._public_inline_results(inline_results)}

    def _public_inline_results(self, inline_results):
        if not inline_results:
            return None
        public_results = {}
        for inline_id, operations in inline_results.items():
            public_results[inline_id] = {}
            for operation, values in operations.items():
                if operation.startswith("_"):
                    continue
                public_values = []
                for value in values:
                    if isinstance(value, dict):
                        public_values.append({key: item for key, item in value.items() if not key.startswith("_")})
                    else:
                        public_values.append(value)
                public_results[inline_id][operation] = public_values
        return public_results

    def response_delete(self, request, obj_display, obj_id):
        return None

    def response_action(self, request, queryset, payload):
        payload = self._action_payload_value(payload)
        action = payload.action
        if action not in self.get_actions(request):
            raise AdminValidationError([{"message": _("Invalid action."), "param": "action"}])
        if not payload.selected_ids and not payload.select_across:
            raise AdminValidationError(
                [{"message": _("Items must be selected in order to perform actions on them."), "param": "selected_ids"}]
            )
        if payload.selected_ids and not payload.select_across:
            queryset = queryset.filter(pk__in=payload.selected_ids)
        func = self.get_actions(request)[action][0]
        action_data = self._action_data(func, payload)
        if self._action_input_schema(func) is None:
            response = func(self, request, queryset)
        else:
            response = func(self, request, queryset, action_data)
        return response if response is not None else {"detail": "Action completed."}

    def _action_input_schema(self, func):
        return getattr(func, "action_input_schema", None)

    def _action_payload_value(self, payload):
        return payload.root if isinstance(payload, RootModel) else payload

    def _action_data(self, func, payload):
        schema = self._action_input_schema(func)
        if schema is None:
            return None
        raw_data = getattr(payload, "data", None)
        if isinstance(raw_data, BaseModel):
            raw_data = raw_data.model_dump()
        if raw_data is None:
            raw_data = {}
        try:
            return TypeAdapter(schema).validate_python(raw_data)
        except PydanticValidationError as exc:
            raise AdminValidationError(self._action_data_errors(exc)) from exc

    def _action_data_errors(self, exc):
        errors = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            errors.append(
                {
                    "message": error.get("msg", str(error)),
                    "param": f"data.{location}" if location else "data",
                }
            )
        return errors

    def get_deleted_objects(self, objs, request):
        return get_deleted_objects(objs, request, self.admin_site)

    def form_initial_for_instance(self, obj, form_class):
        return model_to_dict(obj, fields=list(form_class.base_fields.keys()))
