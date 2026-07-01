import enum

from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.core.paginator import Paginator
from django.db import models
from django.db.models.constants import LOOKUP_SEP
from django.forms.models import model_to_dict
from django.utils.text import capfirst, smart_split, unescape_string_literal
from django.utils.translation import gettext_lazy as _

from django_ninja_admin.admins.base import BaseAdmin
from django_ninja_admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django_ninja_admin.utils.deletion import get_deleted_objects

HORIZONTAL, VERTICAL = 1, 2


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

    def get_inline_instances(self, request, obj=None):
        inline_instances = []
        for inline_class in self.inlines:
            inline = inline_class(self.model, self.admin_site)
            if request is not None:
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

    def get_search_fields(self, request):
        return self.search_fields

    def get_search_results(self, request, queryset, search_term):
        def construct_search(field_name):
            if field_name.startswith("^"):
                return f"{field_name.removeprefix('^')}__istartswith", None
            if field_name.startswith("="):
                return f"{field_name.removeprefix('=')}__iexact", None
            if field_name.startswith("@"):
                return f"{field_name.removeprefix('@')}__search", None
            opts = queryset.model._meta
            prev_field = None
            for path_part in field_name.split(LOOKUP_SEP):
                if path_part == "pk":
                    path_part = opts.pk.name
                try:
                    field = opts.get_field(path_part)
                except FieldDoesNotExist:
                    if prev_field and prev_field.get_lookup(path_part):
                        return field_name, prev_field if path_part == "exact" else None
                    return f"{field_name}__icontains", None
                prev_field = field
                if hasattr(field, "path_infos"):
                    opts = field.path_infos[-1].to_opts
            return f"{field_name}__icontains", None

        may_have_duplicates = False
        search_fields = self.get_search_fields(request)
        if search_fields and search_term:
            orm_lookups = [construct_search(str(field)) for field in search_fields]
            term_queries = []
            for bit in smart_split(search_term):
                if bit.startswith(('"', "'")) and bit[0] == bit[-1]:
                    bit = unescape_string_literal(bit)
                bit_lookups = []
                for orm_lookup, validate_field in orm_lookups:
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

    def construct_change_message(self, request, form, inline_results=None, add=False):
        if add:
            return [{"added": {}}]
        changed = getattr(form, "changed_data", None) or []
        if changed:
            return [{"changed": {"fields": changed}}]
        return []

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
        return {"data": self.serialize_object(obj, request), "inlines": inline_results or None}

    def response_change(self, request, obj, form, inline_results):
        return {"data": self.serialize_object(obj, request), "inlines": inline_results or None}

    def response_delete(self, request, obj_display, obj_id):
        return None

    def response_action(self, request, queryset, payload):
        action = payload.action
        if action not in self.get_actions(request):
            from django_ninja_admin.exceptions import AdminValidationError

            raise AdminValidationError([{"message": _("Invalid action."), "param": "action"}])
        if not payload.selected_ids and not payload.select_across:
            from django_ninja_admin.exceptions import AdminValidationError

            raise AdminValidationError(
                [{"message": _("Items must be selected in order to perform actions on them."), "param": "selected_ids"}]
            )
        if payload.selected_ids and not payload.select_across:
            queryset = queryset.filter(pk__in=payload.selected_ids)
        func = self.get_actions(request)[action][0]
        response = func(self, request, queryset)
        return response if response is not None else {"detail": "Action completed."}

    def get_deleted_objects(self, objs, request):
        return get_deleted_objects(objs, request, self.admin_site)

    def serialize_object(self, obj, request=None):
        schema = self.get_output_schema(request)
        data = schema.model_validate(obj, from_attributes=True).model_dump(mode="json", by_alias=True)
        for field in obj._meta.fields:
            if field.name == "password":
                data.pop(field.name, None)
                data.pop(f"{field.name}_id", None)
                continue
            value = getattr(obj, field.name)
            alias = f"{field.name}_id" if field.remote_field else field.name
            if field.remote_field and value is not None and alias in data:
                data[f"{field.name}_label"] = str(value)
        for field in obj._meta.many_to_many:
            if obj.pk and field.name not in data:
                data[field.name] = list(getattr(obj, field.name).values_list("pk", flat=True))
        return data

    def form_initial_for_instance(self, obj, form_class):
        return model_to_dict(obj, fields=list(form_class.base_fields.keys()))
