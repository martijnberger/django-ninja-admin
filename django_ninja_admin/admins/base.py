from django import forms
from django.contrib.auth import get_permission_codename
from django.core.exceptions import FieldDoesNotExist
from django.forms import modelform_factory
from django.urls import reverse
from django.utils.safestring import mark_safe

from django_ninja_admin.exceptions import NotRegistered
from django_ninja_admin.utils.flatten_fieldsets import flatten_fieldsets
from django_ninja_admin.utils.forms import form_field_descriptions


class BaseAdmin:
    autocomplete_fields = ()
    raw_id_fields = ()
    fields = None
    exclude = None
    fieldsets = None
    form_class = None
    output_schema = None
    schema_field_overrides = {}
    filter_vertical = ()
    filter_horizontal = ()
    radio_fields = {}
    prepopulated_fields = {}
    readonly_fields = ()
    ordering = None
    sortable_by = None
    view_on_site = True
    empty_value_display = "-"

    def check(self, **kwargs):
        return []

    def get_autocomplete_fields(self, request):
        return self.autocomplete_fields

    def get_empty_value_display(self):
        return mark_safe(getattr(self, "empty_value_display", self.admin_site.empty_value_display))

    def get_exclude(self, request, obj=None):
        return self.exclude

    def get_fields(self, request, obj=None):
        if self.fields:
            return self.fields
        exclude = set(self.get_exclude(request, obj) or [])
        fields = [
            field.name
            for field in self.model._meta.fields
            if field.editable and field.name not in exclude
        ]
        fields += [
            field.name
            for field in self.model._meta.many_to_many
            if field.editable and field.name not in exclude
        ]
        return fields

    def get_fieldsets(self, request, obj=None):
        if self.fieldsets:
            return self.fieldsets
        return [(None, {"fields": self.get_fields(request, obj)})]

    def get_form_class(self, request, obj=None, change=False):
        if self.form_class is not None:
            return self.form_class
        fields = flatten_fieldsets(self.get_fieldsets(request, obj))
        exclude = list(self.get_exclude(request, obj) or [])
        readonly_fields = list(self.get_readonly_fields(request, obj) or [])
        form_fields = [field for field in fields if field not in readonly_fields]
        return modelform_factory(
            self.model,
            form=forms.ModelForm,
            fields=form_fields or None,
            exclude=exclude or None,
        )

    def get_schema_field_overrides(self, request=None):
        return self.schema_field_overrides

    def _output_schema_for_fields(self, fields_key, custom_fields):
        from ninja.orm import create_schema

        cache = getattr(self, "_output_schema_cache", {})
        cache_key = (
            fields_key,
            tuple((name, repr(field_type), repr(default)) for name, field_type, default in custom_fields),
        )
        if cache_key not in cache:
            fields = list(fields_key)
            cache[cache_key] = create_schema(
                self.model,
                name=f"{self.model.__name__}AdminOut",
                fields=fields,
                custom_fields=custom_fields,
            )
            self._output_schema_cache = cache
        return cache[cache_key]

    def get_output_schema(self, request=None):
        if self.output_schema is not None:
            return self.output_schema
        overrides = self.get_schema_field_overrides(request) or {}
        fields = [self.model._meta.pk.name]
        fields.extend(
            field.name
            for field in self.model._meta.fields
            if field.name != self.model._meta.pk.name and field.name != "password"
        )
        custom_fields = []
        for field in self.model._meta.fields:
            if field.remote_field and field.name != "password":
                custom_fields.append((f"{field.name}_label", str, None))
        for field in self.model._meta.many_to_many:
            custom_fields.append((field.name, list[object], []))
        custom_fields.extend(
            (name, field_type, default)
            for name, value in overrides.items()
            for field_type, default in [self._normalize_schema_override(value)]
        )
        return self._output_schema_for_fields(tuple(fields), tuple(custom_fields))

    def _normalize_schema_override(self, value):
        if isinstance(value, tuple):
            if len(value) == 2:
                return value
            if len(value) == 1:
                return value[0], None
        return value, None

    def get_form_fields_description(self, request, obj=None):
        return form_field_descriptions(
            self.get_form_class(request, obj, change=obj is not None),
            readonly_fields=self.get_readonly_fields(request, obj),
            instance=obj,
        )

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

    def get_form_description(self, request, obj=None, **kwargs):
        permissions = {
            "has_add_permission": self.has_add_permission(request),
            "has_change_permission": self.has_change_permission(request, obj),
            "has_delete_permission": self.has_delete_permission(request, obj),
            "has_view_permission": self.has_view_permission(request, obj),
        }
        form_description = {
            "model": f"{self.model._meta.app_label}.{self.model._meta.model_name}",
            "readonly_fields": list(self.get_readonly_fields(request, obj)),
            "fields": self.get_form_fields_description(request, obj),
            "fieldsets": list(self.get_fieldsets(request, obj)),
            "prepopulated": dict(self.get_prepopulated_fields(request, obj)),
            "permissions": permissions,
            "save_as": getattr(self, "save_as", False),
            "save_as_continue": getattr(self, "save_as_continue", True),
            "save_on_top": getattr(self, "save_on_top", False),
            "filter_horizontal": list(self.filter_horizontal),
            "filter_vertical": list(self.filter_vertical),
            "raw_id_fields": list(self.raw_id_fields),
            "radio_fields": dict(self.radio_fields),
            "view_on_site": bool(self.view_on_site),
            "autocomplete_fields": list(self.autocomplete_fields),
            **kwargs,
        }
        return {"form": form_description}

    def get_prepopulated_fields(self, request, obj=None):
        return self.prepopulated_fields

    def get_ordering(self, request):
        return self.ordering or ()

    def get_queryset(self, request):
        qs = self.model._default_manager.get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields

    def get_sortable_by(self, request):
        return self.sortable_by if self.sortable_by is not None else self.get_list_display(request)

    def get_view_on_site_url(self, obj=None):
        if obj is None or not self.view_on_site:
            return None
        if callable(self.view_on_site):
            return self.view_on_site(obj)
        if hasattr(obj, "get_absolute_url"):
            from django.contrib.contenttypes.models import ContentType

            return reverse(
                f"{self.admin_site.name}:view_on_site",
                kwargs={
                    "content_type_id": ContentType.objects.get_for_model(obj, for_concrete_model=False).pk,
                    "object_id": obj.pk,
                },
                current_app=self.admin_site.name,
            )
        return None

    def lookup_allowed(self, lookup, value, request):
        if lookup in self.get_list_filter(request):
            return True
        try:
            self.model._meta.get_field(lookup.split("__", 1)[0])
            return "__" not in lookup
        except FieldDoesNotExist:
            return False

    def to_field_allowed(self, request, to_field):
        try:
            field = self.model._meta.get_field(to_field)
        except FieldDoesNotExist:
            return False
        if field.primary_key:
            return True
        for model, _admin in self.admin_site._registry.items():
            if model is self.model:
                continue
            for related_field in model._meta.fields:
                if related_field.remote_field and related_field.remote_field.model is self.model:
                    return True
            for related_field in model._meta.many_to_many:
                if related_field.remote_field and related_field.remote_field.model is self.model:
                    return True
        return False

    def get_field_queryset(self, db, db_field, request):
        try:
            related_admin = self.admin_site.get_model_admin(db_field.remote_field.model)
        except NotRegistered:
            return None
        ordering = related_admin.get_ordering(request)
        if ordering:
            return db_field.remote_field.model._default_manager.order_by(*ordering)
        return None

    def has_add_permission(self, request):
        opts = self.opts
        codename = get_permission_codename("add", opts)
        return request.user.has_perm(f"{opts.app_label}.{codename}")

    def has_change_permission(self, request, obj=None):
        opts = self.opts
        codename = get_permission_codename("change", opts)
        return request.user.has_perm(f"{opts.app_label}.{codename}")

    def has_delete_permission(self, request, obj=None):
        opts = self.opts
        codename = get_permission_codename("delete", opts)
        return request.user.has_perm(f"{opts.app_label}.{codename}")

    def has_view_permission(self, request, obj=None):
        opts = self.opts
        view_codename = get_permission_codename("view", opts)
        change_codename = get_permission_codename("change", opts)
        return request.user.has_perm(f"{opts.app_label}.{view_codename}") or request.user.has_perm(
            f"{opts.app_label}.{change_codename}"
        )

    def has_view_or_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj) or self.has_change_permission(request, obj)

    def has_module_permission(self, request):
        return request.user.has_module_perms(self.opts.app_label)
