from typing import Any

from django import forms
from django.contrib.auth import get_permission_codename
from django.forms.models import BaseInlineFormSet, _get_foreign_key, inlineformset_factory, modelform_factory
from django.utils.text import format_lazy
from pydantic import Field, create_model

from django_ninja_admin.admins.base import BaseAdmin
from django_ninja_admin.exceptions import AdminValidationError
from django_ninja_admin.schemas import AdminInlineOperationsSchema, AdminInlineRowSchema
from django_ninja_admin.utils.flatten_fieldsets import flatten_fieldsets


class InlineModelAdmin(BaseAdmin):
    model = None
    fk_name = None
    extra = 3
    min_num = None
    max_num = None
    formset = BaseInlineFormSet
    verbose_name = None
    verbose_name_plural = None
    can_delete = True
    show_change_link = False
    admin_style = "tabular"

    def __init__(self, parent_model, admin_site):
        self.admin_site = admin_site
        self.parent_model = parent_model
        self.opts = self.model._meta
        self.has_registered_model = admin_site.is_registered(self.model)
        if self.verbose_name_plural is None:
            if self.verbose_name is None:
                self.verbose_name_plural = self.opts.verbose_name_plural
            else:
                self.verbose_name_plural = format_lazy("{}s", self.verbose_name)
        if self.verbose_name is None:
            self.verbose_name = self.opts.verbose_name

    def get_extra(self, request, obj=None, **kwargs):
        return self.extra

    def get_min_num(self, request, obj=None, **kwargs):
        return self.min_num

    def get_max_num(self, request, obj=None, **kwargs):
        return self.max_num

    def get_formset_count_options(self, request, obj=None):
        extra = self._clean_formset_count_option("extra", self.get_extra(request, obj), allow_none=False)
        min_num = self._clean_formset_count_option("min_num", self.get_min_num(request, obj), allow_none=True)
        max_num = self._clean_formset_count_option("max_num", self.get_max_num(request, obj), allow_none=True)
        if min_num is not None and max_num is not None and min_num > max_num:
            self._raise_count_option_error("min_num", "Inline 'min_num' must not exceed 'max_num'.")
        return {"extra": extra, "min_num": min_num, "max_num": max_num}

    def _clean_formset_count_option(self, option, value, *, allow_none):
        if value is None and allow_none:
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            self._raise_count_option_error(option, f"Inline '{option}' must be an integer.")
        if value < 0:
            self._raise_count_option_error(option, f"Inline '{option}' must not be negative.")
        return value

    def _raise_count_option_error(self, option, message):
        inline_id = f"{self.model._meta.app_label}.{self.model._meta.model_name}"
        raise AdminValidationError([{"message": message, "param": f"inlines.{inline_id}.{option}"}])

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not self.has_view_or_change_permission(request):
            return queryset.none()
        return queryset

    def get_form_class(self, request, obj=None, change=False):
        if self.form_class is not None:
            return self.form_class
        fk = _get_foreign_key(self.parent_model, self.model, fk_name=self.fk_name)
        excluded_fields = set(self.get_exclude(request, obj) or ())
        excluded_fields.update(self.get_readonly_fields(request, obj) or ())
        excluded_fields.add(fk.name)
        fields = [
            field
            for field in flatten_fieldsets(self.get_fieldsets(request, obj))
            if field not in excluded_fields
        ]
        return modelform_factory(
            self.model,
            form=forms.ModelForm,
            fields=fields or None,
            formfield_callback=lambda db_field, **kwargs: self.formfield_for_dbfield(db_field, request, **kwargs),
        )

    def get_formset(self, request, obj=None, change=False, *, count_options=None):
        count_options = count_options or self.get_formset_count_options(request, obj)
        return inlineformset_factory(
            self.parent_model,
            self.model,
            form=self.get_form_class(request, obj, change=change),
            formset=self.formset,
            fk_name=self.fk_name,
            extra=count_options["extra"],
            min_num=count_options["min_num"],
            max_num=count_options["max_num"],
            can_delete=self.can_delete,
            validate_min=count_options["min_num"] is not None,
            validate_max=count_options["max_num"] is not None,
        )

    def get_inline_row_schema(self, request=None, obj=None, *, change=False, partial=False, require_pk=False):
        cache = getattr(self, "_inline_row_schema_cache", {})
        formset_class = self.get_formset(request, obj, change=change)
        form_fields = formset_class.form.base_fields
        overrides = self.get_form_schema_field_overrides(request, obj, change=change) or {}
        cache_key = (
            "inline-row",
            tuple(form_fields),
            self._schema_override_cache_key(overrides),
            change,
            partial,
            require_pk,
        )
        if cache_key not in cache:
            fields = {}
            if require_pk:
                fields["pk"] = (Any, ...)
            for field_name, form_field in form_fields.items():
                field_type = self.get_form_schema_field_type(field_name, form_field, overrides=overrides)
                required = bool(form_field.required and not getattr(form_field, "disabled", False) and not partial)
                fields[field_name] = (field_type, ...) if required else (field_type | None, None)
            operation = "Change" if require_pk else "Add"
            cache[cache_key] = create_model(
                f"{self.model.__name__}Inline{operation}Row",
                __base__=AdminInlineRowSchema,
                **fields,
            )
            self._inline_row_schema_cache = cache
        return cache[cache_key]

    def get_inline_operations_schema(self, request=None, obj=None, *, change=False):
        cache = getattr(self, "_inline_operations_schema_cache", {})
        add_schema = self.get_inline_row_schema(request, obj, change=change, partial=False, require_pk=False)
        change_schema = self.get_inline_row_schema(request, obj, change=True, partial=True, require_pk=True)
        cache_key = ("inline-operations", change, add_schema, change_schema)
        if cache_key not in cache:
            cache[cache_key] = create_model(
                f"{self.model.__name__}InlineOperations",
                __base__=AdminInlineOperationsSchema,
                add=(list[add_schema], Field(default_factory=list)),
                change=(list[change_schema], Field(default_factory=list)),
                delete=(list[Any], Field(default_factory=list)),
            )
            self._inline_operations_schema_cache = cache
        return cache[cache_key]

    def _has_any_perms_for_target_model(self, request, perms):
        opts = self.opts
        for field in opts.fields:
            if field.remote_field and field.remote_field.model != self.parent_model:
                opts = field.remote_field.model._meta
                break
        return any(
            request.user.has_perm(f"{opts.app_label}.{get_permission_codename(perm, opts)}")
            for perm in perms
        )

    def has_add_permission(self, request, obj=None):
        if self.opts.auto_created:
            return self._has_any_perms_for_target_model(request, ["change"])
        return super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        if self.opts.auto_created:
            return self._has_any_perms_for_target_model(request, ["change"])
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self.opts.auto_created:
            return self._has_any_perms_for_target_model(request, ["change"])
        return super().has_delete_permission(request, obj)

    def has_view_permission(self, request, obj=None):
        if self.opts.auto_created:
            return self._has_any_perms_for_target_model(request, ["view", "change"])
        return super().has_view_permission(request, obj)


class TabularInline(InlineModelAdmin):
    admin_style = "tabular"


class StackedInline(InlineModelAdmin):
    admin_style = "stacked"
