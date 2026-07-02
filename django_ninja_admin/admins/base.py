import copy
from base64 import b64encode
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import ceil, floor
from typing import Annotated, Any, Literal, get_args, get_origin
from uuid import UUID

from django import forms
from django.contrib.auth import get_permission_codename
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import FieldDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import (
    MaxLengthValidator,
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
    RegexValidator,
    StepValueValidator,
    validate_email,
)
from django.db import models
from django.forms import modelform_factory
from django.forms.models import ModelChoiceField, ModelMultipleChoiceField
from django.urls import reverse
from django.utils.dateparse import parse_duration
from django.utils.safestring import mark_safe
from ninja import Schema
from pydantic import (
    AfterValidator,
    AnyUrl,
    BeforeValidator,
    ConfigDict,
    Field,
    IPvAnyAddress,
    TypeAdapter,
    create_model,
)

from django_ninja_admin.exceptions import NotRegistered
from django_ninja_admin.schemas import AdminBulkRowSchema, AdminWriteSchema, FileFieldValue, ImageFieldValue
from django_ninja_admin.utils.flatten_fieldsets import flatten_fieldsets
from django_ninja_admin.utils.forms import (
    fieldset_layout_description,
    file_value_metadata,
    form_field_descriptions,
    form_media_description,
    image_value_metadata,
)
from django_ninja_admin.utils.lookup import field_name_for_display

AdminJsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


def _parse_duration_value(value):
    if isinstance(value, str):
        parsed = parse_duration(value)
        if parsed is not None:
            return parsed
    return value


def _validate_email_value(value):
    try:
        validate_email(value)
    except DjangoValidationError as exc:
        raise ValueError("; ".join(str(message) for message in exc.messages)) from exc
    return value


def _strip_string_value(value):
    if isinstance(value, str):
        return value.strip()
    return value


def _parse_null_boolean_value(value):
    if value in ("unknown", ""):
        return None
    return value


def _base64_binary_value(value):
    if value is None:
        return None
    return b64encode(bytes(value)).decode("ascii")


def _form_field_clean_validator(field):
    def validate(value):
        try:
            return field.clean(value)
        except DjangoValidationError as exc:
            raise ValueError("; ".join(str(message) for message in exc.messages)) from exc

    return validate


def _choice_membership_validator(choices):
    allowed = tuple(choices)

    def validate(value):
        if value not in allowed:
            raise ValueError(f"Input should be one of: {', '.join(str(choice) for choice in allowed)}")
        return value

    return validate


class BaseAdmin:
    autocomplete_fields = ()
    raw_id_fields = ()
    fields = None
    exclude = None
    fieldsets = None
    form_class = None
    formfield_overrides = {}
    form_schema_field_overrides = {}
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
        from django_ninja_admin.checks import check_model_admin

        return check_model_admin(self)

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
        fields = [field.name for field in self.model._meta.fields if field.editable and field.name not in exclude]
        fields += [
            field.name for field in self.model._meta.many_to_many if field.editable and field.name not in exclude
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
        readonly_field_names = {field_name_for_display(field) for field in readonly_fields}
        form_fields = [field for field in fields if field_name_for_display(field) not in readonly_field_names]
        return modelform_factory(
            self.model,
            form=forms.ModelForm,
            fields=form_fields or None,
            exclude=exclude or None,
            formfield_callback=lambda db_field, **kwargs: self.formfield_for_dbfield(db_field, request, **kwargs),
        )

    def get_changelist_form_class(self, request):
        form = self.form_class or forms.ModelForm
        return modelform_factory(
            self.model,
            form=form,
            fields=tuple(getattr(self, "list_editable", ()) or ()),
            formfield_callback=lambda db_field, **kwargs: self.formfield_for_dbfield(db_field, request, **kwargs),
        )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.choices:
            return self.formfield_for_choice_field(db_field, request, **kwargs)
        if isinstance(db_field, models.ForeignKey):
            if db_field.__class__ in self.formfield_overrides:
                kwargs = {**copy.deepcopy(self.formfield_overrides[db_field.__class__]), **kwargs}
            return self.formfield_for_foreignkey(db_field, request, **kwargs)
        if isinstance(db_field, models.ManyToManyField):
            if db_field.__class__ in self.formfield_overrides:
                kwargs = {**copy.deepcopy(self.formfield_overrides[db_field.__class__]), **kwargs}
            return self.formfield_for_manytomany(db_field, request, **kwargs)
        for klass in db_field.__class__.mro():
            if klass in self.formfield_overrides:
                kwargs = {**copy.deepcopy(self.formfield_overrides[klass]), **kwargs}
                return db_field.formfield(**kwargs)
        return db_field.formfield(**kwargs)

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name in self.radio_fields:
            kwargs.setdefault("widget", forms.RadioSelect)
            kwargs.setdefault(
                "choices",
                db_field.get_choices(include_blank=db_field.blank, blank_choice=[("", "None")]),
            )
        return db_field.formfield(**kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        db = kwargs.get("using")
        if "queryset" not in kwargs:
            queryset = self.get_field_queryset(db, db_field, request)
            if queryset is not None:
                kwargs["queryset"] = queryset
        return db_field.formfield(**kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if not db_field.remote_field.through._meta.auto_created:
            return None
        db = kwargs.get("using")
        if "queryset" not in kwargs:
            queryset = self.get_field_queryset(db, db_field, request)
            if queryset is not None:
                kwargs["queryset"] = queryset
        return db_field.formfield(**kwargs)

    def get_schema_field_overrides(self, request=None):
        return self.schema_field_overrides

    def get_form_schema_field_overrides(self, request=None, obj=None, *, change=False):
        return self.form_schema_field_overrides

    def get_write_schema(self, request=None, obj=None, *, change=False, partial=False, fields=None, name_suffix=None):
        cache = getattr(self, "_write_schema_cache", {})
        form_class = self.get_form_class(request, obj, change=change)
        form_fields = form_class.base_fields
        selected_fields = tuple(fields or form_fields.keys())
        overrides = self.get_form_schema_field_overrides(request, obj, change=change) or {}
        cache_key = ("write", selected_fields, self._schema_override_cache_key(overrides), change, partial, name_suffix)
        if cache_key not in cache:
            schema_fields = {}
            for field_name in selected_fields:
                form_field = form_fields.get(field_name)
                field_type = self.get_form_schema_field_type(field_name, form_field, overrides=overrides)
                required = bool(
                    form_field and form_field.required and not getattr(form_field, "disabled", False) and not partial
                )
                if required:
                    schema_fields[field_name] = (field_type, ...)
                else:
                    schema_fields[field_name] = (field_type | None, None)
            operation = name_suffix or ("PartialUpdate" if partial else "Update" if change else "Create")
            cache[cache_key] = create_model(
                f"{self.model.__name__}Admin{operation}Data",
                __base__=AdminWriteSchema,
                __config__=ConfigDict(
                    json_schema_extra={
                        "examples": [
                            self._form_data_example(
                                form_fields,
                                selected_fields=selected_fields,
                                partial=partial,
                                overrides=overrides,
                            )
                        ]
                    }
                ),
                **schema_fields,
            )
            self._write_schema_cache = cache
        return cache[cache_key]

    def get_mutation_payload_schema(self, request=None, obj=None, *, change=False, partial=False):
        cache = getattr(self, "_mutation_payload_schema_cache", {})
        data_schema = self.get_write_schema(request, obj, change=change, partial=partial)
        cache_key = ("mutation", change, partial, data_schema)
        if cache_key not in cache:
            operation = "PartialUpdate" if partial else "Update" if change else "Create"
            cache[cache_key] = create_model(
                f"{self.model.__name__}Admin{operation}Payload",
                __base__=Schema,
                __config__=ConfigDict(json_schema_extra={"examples": [{"data": self._schema_example(data_schema)}]}),
                data=(data_schema, ...),
                inlines=(dict[str, Any] | None, None),
            )
            self._mutation_payload_schema_cache = cache
        return cache[cache_key]

    def get_mutation_response_schema(self, request=None):
        cache = getattr(self, "_mutation_response_schema_cache", {})
        output_schema = self.get_output_schema(request)
        cache_key = ("mutation-response", output_schema)
        if cache_key not in cache:
            data_schema = create_model(
                f"{self.model.__name__}AdminMutationData",
                __base__=output_schema,
                __config__=ConfigDict(extra="allow"),
            )
            cache[cache_key] = create_model(
                f"{self.model.__name__}AdminMutationResponse",
                __base__=Schema,
                __config__=ConfigDict(
                    json_schema_extra={
                        "examples": [
                            {
                                "data": self._schema_example(output_schema),
                                "inlines": None,
                            }
                        ]
                    }
                ),
                data=(dict[str, Any] | data_schema, ...),
                inlines=(dict[str, Any] | None, None),
            )
            self._mutation_response_schema_cache = cache
        return cache[cache_key]

    def get_bulk_payload_schema(self, request=None):
        cache = getattr(self, "_mutation_payload_schema_cache", {})
        overrides = self.get_form_schema_field_overrides(request, change=True) or {}
        cache_key = ("bulk", tuple(self.list_editable), self._schema_override_cache_key(overrides))
        if cache_key not in cache:
            form_fields = {}
            if self.list_editable:
                form_class = self.get_changelist_form_class(request)
                form_fields = form_class.base_fields
            row_fields = {"pk": (Any, ...)}
            for field_name in self.list_editable:
                form_field = form_fields.get(field_name)
                field_type = self.get_form_schema_field_type(
                    field_name,
                    form_field,
                    overrides=overrides,
                    choices_as_literal=False,
                )
                row_fields[field_name] = (field_type | None, None)
            row_schema = create_model(
                f"{self.model.__name__}AdminBulkRow",
                __base__=AdminBulkRowSchema,
                __config__=ConfigDict(
                    json_schema_extra={"examples": [self._bulk_row_example(form_fields, overrides=overrides)]}
                ),
                **row_fields,
            )
            cache[cache_key] = create_model(
                f"{self.model.__name__}AdminBulkPayload",
                __base__=Schema,
                __config__=ConfigDict(json_schema_extra={"examples": [{"data": [self._schema_example(row_schema)]}]}),
                data=(list[row_schema], ...),
            )
            self._mutation_payload_schema_cache = cache
        return cache[cache_key]

    def get_bulk_response_schema(self, request=None):
        cache = getattr(self, "_mutation_response_schema_cache", {})
        output_schema = self.get_output_schema(request)
        cache_key = ("bulk-response", output_schema)
        if cache_key not in cache:
            cache[cache_key] = create_model(
                f"{self.model.__name__}AdminBulkResponse",
                __base__=Schema,
                __config__=ConfigDict(
                    json_schema_extra={"examples": [{"data": {"1": self._schema_example(output_schema)}}]}
                ),
                data=(dict[str, output_schema], ...),
            )
            self._mutation_response_schema_cache = cache
        return cache[cache_key]

    def _schema_example(self, schema):
        return (schema.model_json_schema().get("examples") or [{}])[0]

    def _form_data_example(self, form_fields, *, selected_fields=None, partial=False, overrides=None):
        data = {}
        overrides = overrides or {}
        field_names = tuple(selected_fields or form_fields.keys())
        candidates = [
            (name, form_fields.get(name))
            for name in field_names
            if form_fields.get(name) is not None and not getattr(form_fields.get(name), "disabled", False)
        ]
        for name, field in candidates:
            if partial and data:
                break
            if partial or field.required:
                data[name] = self._form_field_example_value(field, override=overrides.get(name))
        if not data and candidates:
            name, field = candidates[0]
            data[name] = self._form_field_example_value(field, override=overrides.get(name))
        return data

    def _bulk_row_example(self, form_fields, *, overrides=None):
        row = {"pk": 1}
        row.update(
            self._form_data_example(
                form_fields,
                selected_fields=tuple(self.list_editable),
                partial=True,
                overrides=overrides,
            )
        )
        return row

    def _form_field_example_value(self, field, *, override=None):
        if override is not None:
            field_type, default = self._normalize_schema_override(override)
            return self._schema_type_example(field_type, default)
        if isinstance(field, ModelMultipleChoiceField):
            return [self._relation_form_field_example_value(field)]
        if isinstance(field, ModelChoiceField):
            return self._relation_form_field_example_value(field)
        if isinstance(field, forms.TypedMultipleChoiceField | forms.MultipleChoiceField):
            return [self._choice_example_value(field.choices)]
        if isinstance(field, forms.TypedChoiceField):
            return self._coerce_choice_example(field, self._choice_example_value(field.choices))
        if isinstance(field, forms.ChoiceField):
            return self._choice_example_value(field.choices)
        if isinstance(field, forms.NullBooleanField):
            return None
        if isinstance(field, forms.BooleanField):
            return True
        if isinstance(field, forms.DecimalField):
            return "9.99"
        if isinstance(field, forms.IntegerField):
            return 1
        if isinstance(field, forms.FloatField):
            return 1.5
        if isinstance(field, forms.SplitDateTimeField):
            return ["2026-07-02", "12:00:00"]
        if isinstance(field, forms.DateTimeField):
            return "2026-07-02T12:00:00+00:00"
        if isinstance(field, forms.DateField):
            return "2026-07-02"
        if isinstance(field, forms.TimeField):
            return "12:00:00"
        if isinstance(field, forms.DurationField):
            return "01:00:00"
        if isinstance(field, forms.UUIDField):
            return "00000000-0000-4000-8000-000000000000"
        if isinstance(field, forms.EmailField):
            return "user@example.com"
        if isinstance(field, forms.URLField):
            return "https://example.com/"
        if isinstance(field, forms.GenericIPAddressField):
            return "192.0.2.1"
        if isinstance(field, forms.JSONField):
            return {"example": True}
        return "example"

    def _choice_example_value(self, choices):
        for value in self.iter_choice_values(choices):
            if value not in ("", None):
                return value
        return "example"

    def _coerce_choice_example(self, field, value):
        coerce = getattr(field, "coerce", None)
        if coerce is None:
            return value
        try:
            return coerce(value)
        except (TypeError, ValueError):
            return value

    def get_form_schema_field_type(
        self,
        field_name,
        form_field,
        *,
        overrides=None,
        choices_as_literal=True,
    ):
        if overrides is None:
            overrides = self.get_form_schema_field_overrides() or {}
        if field_name in overrides:
            return self._normalize_schema_override(overrides[field_name])[0]
        if form_field is None:
            return Any
        return self.get_pydantic_type_for_form_field(form_field, choices_as_literal=choices_as_literal)

    def get_pydantic_type_for_form_field(self, field, *, choices_as_literal=True):
        field_type = self._get_pydantic_type_for_form_field(field, choices_as_literal=choices_as_literal)
        constraints = self.get_pydantic_constraints_for_form_field(field, field_type)
        metadata = []
        if constraints:
            metadata.append(Field(**constraints))
        if getattr(field, "strip", False):
            metadata.append(BeforeValidator(_strip_string_value))
        if self.should_clean_with_pydantic(field):
            metadata.append(AfterValidator(_form_field_clean_validator(field)))
        if metadata:
            return Annotated[field_type, *metadata]
        return field_type

    def _get_pydantic_type_for_form_field(self, field, *, choices_as_literal=True):
        if isinstance(field, ModelMultipleChoiceField):
            return list[self.get_pydantic_type_for_model_output_field(self.get_model_choice_target_field(field))]
        if isinstance(field, ModelChoiceField):
            return self.get_pydantic_type_for_model_output_field(self.get_model_choice_target_field(field))
        if isinstance(field, forms.NullBooleanField):
            return Annotated[bool | None, BeforeValidator(_parse_null_boolean_value)]
        if isinstance(field, forms.BooleanField):
            return bool
        if isinstance(field, forms.DecimalField):
            return Decimal
        if isinstance(field, forms.FloatField):
            return float
        if isinstance(field, forms.IntegerField):
            return int
        if isinstance(field, forms.ComboField):
            return self.get_pydantic_type_for_combo_field(field)
        if isinstance(field, forms.SplitDateTimeField):
            return tuple[date, time]
        if isinstance(field, forms.MultiValueField):
            return self.get_pydantic_type_for_multivalue_field(field, choices_as_literal=choices_as_literal)
        if isinstance(field, forms.DateTimeField):
            return Annotated[datetime, BeforeValidator(_form_field_clean_validator(field))]
        if isinstance(field, forms.DateField):
            return Annotated[date, BeforeValidator(_form_field_clean_validator(field))]
        if isinstance(field, forms.TimeField):
            return Annotated[time, BeforeValidator(_form_field_clean_validator(field))]
        if isinstance(field, forms.DurationField):
            return Annotated[timedelta, BeforeValidator(_parse_duration_value)]
        if isinstance(field, forms.UUIDField):
            return UUID
        if isinstance(field, forms.EmailField):
            return Annotated[
                str,
                AfterValidator(_validate_email_value),
                Field(json_schema_extra={"format": "email"}),
            ]
        if isinstance(field, forms.URLField):
            return AnyUrl
        if isinstance(field, forms.GenericIPAddressField):
            return IPvAnyAddress
        if isinstance(field, forms.JSONField):
            return AdminJsonValue
        if isinstance(field, forms.TypedMultipleChoiceField):
            return list[self.get_pydantic_type_for_typed_choice_field(field, choices_as_literal=choices_as_literal)]
        if isinstance(field, forms.MultipleChoiceField):
            return list[self.get_pydantic_type_for_choices(field.choices, as_literal=choices_as_literal)]
        if isinstance(field, forms.FileField):
            return str
        if isinstance(field, forms.TypedChoiceField):
            return self.get_pydantic_type_for_typed_choice_field(field, choices_as_literal=choices_as_literal)
        if getattr(field, "choices", None) and not isinstance(field.choices, str | bytes):
            return self.get_pydantic_type_for_choices(field.choices, as_literal=choices_as_literal)
        return str

    def get_pydantic_constraints_for_form_field(self, field, field_type=None):
        constraints = {}
        if field_type is str and isinstance(field, forms.CharField):
            if getattr(field, "min_length", None) is not None:
                constraints["min_length"] = field.min_length
            if getattr(field, "max_length", None) is not None:
                constraints["max_length"] = field.max_length
            constraints.update(self.get_pydantic_string_validator_constraints_for_form_field(field))
            pattern = self.get_pydantic_pattern_for_form_field(field)
            if pattern:
                constraints["pattern"] = pattern
        if isinstance(field, (forms.DecimalField, forms.FloatField, forms.IntegerField)):
            if getattr(field, "min_value", None) is not None:
                constraints["ge"] = field.min_value
            if getattr(field, "max_value", None) is not None:
                constraints["le"] = field.max_value
            validator_constraints = self.get_pydantic_numeric_validator_constraints_for_form_field(field)
            if "ge" in validator_constraints:
                constraints["ge"] = max(constraints.get("ge", validator_constraints["ge"]), validator_constraints["ge"])
            if "le" in validator_constraints:
                constraints["le"] = min(constraints.get("le", validator_constraints["le"]), validator_constraints["le"])
        if isinstance(field, forms.DecimalField):
            if getattr(field, "max_digits", None) is not None:
                constraints["max_digits"] = field.max_digits
            if getattr(field, "decimal_places", None) is not None:
                constraints["decimal_places"] = field.decimal_places
        step_validator = self.get_step_value_validator(field)
        if step_validator is not None and self.step_validator_has_zero_offset(step_validator):
            constraints["multiple_of"] = self.pydantic_step_value(field, step_validator.limit_value)
        return constraints

    def should_clean_with_pydantic(self, field):
        return self.get_step_value_validator(field) is not None

    def get_step_value_validator(self, field):
        for validator in getattr(field, "validators", ()):
            if isinstance(validator, StepValueValidator):
                return validator
        return None

    def get_pydantic_numeric_validator_constraints_for_form_field(self, field):
        constraints = {}
        for validator in getattr(field, "validators", ()):
            limit_value = getattr(validator, "limit_value", None)
            if callable(limit_value):
                try:
                    limit_value = limit_value()
                except Exception:
                    continue
            if isinstance(validator, MinValueValidator):
                constraints["ge"] = max(
                    constraints.get("ge", limit_value),
                    self.pydantic_numeric_bound_value(field, limit_value),
                )
            elif isinstance(validator, MaxValueValidator):
                constraints["le"] = min(
                    constraints.get("le", limit_value),
                    self.pydantic_numeric_bound_value(field, limit_value),
                )
        return constraints

    def step_validator_has_zero_offset(self, validator):
        offset = getattr(validator, "offset", None)
        if offset is None:
            return True
        try:
            return Decimal(str(offset)) == 0
        except Exception:
            return False

    def pydantic_step_value(self, field, value):
        if isinstance(field, (forms.DecimalField, models.DecimalField)):
            return Decimal(str(value))
        if isinstance(field, (forms.IntegerField, models.IntegerField)):
            return int(value)
        if isinstance(field, (forms.FloatField, models.FloatField)):
            return float(value)
        return value

    def pydantic_numeric_bound_value(self, field, value):
        if isinstance(field, (forms.DecimalField, models.DecimalField)):
            return Decimal(str(value))
        if isinstance(field, (forms.FloatField, models.FloatField)):
            return float(value)
        if isinstance(field, (forms.IntegerField, models.IntegerField)):
            return int(value)
        return value

    def get_pydantic_string_validator_constraints_for_form_field(self, field):
        constraints = {}
        field_max_length = getattr(field, "max_length", None)
        for validator in getattr(field, "validators", ()):
            limit_value = getattr(validator, "limit_value", None)
            if callable(limit_value):
                try:
                    limit_value = limit_value()
                except Exception:
                    continue
            if isinstance(validator, MinLengthValidator):
                constraints["min_length"] = max(constraints.get("min_length", limit_value), limit_value)
            elif isinstance(validator, MaxLengthValidator) and (
                field_max_length is None or limit_value < field_max_length
            ):
                constraints["max_length"] = min(constraints.get("max_length", limit_value), limit_value)
        return constraints

    def get_pydantic_pattern_for_form_field(self, field):
        pattern = self.normalize_pydantic_pattern(getattr(field, "regex", None))
        if pattern and self.pydantic_pattern_is_supported(pattern):
            return pattern
        for validator in getattr(field, "validators", ()):
            if isinstance(validator, RegexValidator):
                pattern = self.normalize_pydantic_pattern(getattr(validator, "regex", None))
                if pattern and self.pydantic_pattern_is_supported(pattern):
                    return pattern
        return None

    def normalize_pydantic_pattern(self, regex):
        pattern = getattr(regex, "pattern", regex)
        if not isinstance(pattern, str):
            return None
        return pattern.replace(r"\A", "^").replace(r"\Z", r"\z")

    def pydantic_pattern_is_supported(self, pattern):
        try:
            TypeAdapter(Annotated[str, Field(pattern=pattern)])
        except Exception:
            return False
        return True

    def get_pydantic_type_for_typed_choice_field(self, field, *, choices_as_literal=True):
        coerce = getattr(field, "coerce", None)
        if coerce in {str, int, float, bool, Decimal, UUID}:
            values = self.get_pydantic_choice_values(field.choices, coerce=coerce)
            if choices_as_literal and values:
                return Annotated[
                    coerce,
                    AfterValidator(_choice_membership_validator(values)),
                    Field(json_schema_extra={"enum": list(values)}),
                ]
            return coerce
        return self.get_pydantic_type_for_choices(field.choices, as_literal=choices_as_literal)

    def get_pydantic_type_for_combo_field(self, field):
        metadata = []
        constraints = self.get_pydantic_constraints_for_combo_field(field)
        if constraints:
            metadata.append(Field(**constraints))
        metadata.append(AfterValidator(_form_field_clean_validator(field)))
        return Annotated[str, *metadata]

    def get_pydantic_constraints_for_combo_field(self, field):
        constraints = {}
        for subfield in field.fields:
            if not isinstance(subfield, forms.CharField):
                continue
            if "min_length" not in constraints and getattr(subfield, "min_length", None) is not None:
                constraints["min_length"] = subfield.min_length
            if "max_length" not in constraints and getattr(subfield, "max_length", None) is not None:
                constraints["max_length"] = subfield.max_length
            validator_constraints = self.get_pydantic_string_validator_constraints_for_form_field(subfield)
            if "min_length" in validator_constraints:
                constraints["min_length"] = max(
                    constraints.get("min_length", validator_constraints["min_length"]),
                    validator_constraints["min_length"],
                )
            if "max_length" in validator_constraints:
                constraints["max_length"] = min(
                    constraints.get("max_length", validator_constraints["max_length"]),
                    validator_constraints["max_length"],
                )
            if "pattern" not in constraints:
                pattern = self.get_pydantic_pattern_for_form_field(subfield)
                if pattern:
                    constraints["pattern"] = pattern
        return constraints

    def get_pydantic_type_for_multivalue_field(self, field, *, choices_as_literal=True):
        field_types = tuple(
            self.get_pydantic_type_for_form_field(subfield, choices_as_literal=choices_as_literal)
            for subfield in field.fields
        )
        if not field_types:
            return list[Any]
        return tuple.__class_getitem__(field_types)

    def get_pydantic_type_for_choices(self, choices, *, as_literal=True):
        literal_type = self.get_pydantic_literal_for_choices(choices) if as_literal else None
        if literal_type is not None:
            return literal_type
        value_types = set()
        for value in self.iter_choice_values(choices):
            if value not in ("", None):
                value_types.add(type(value))
        if not value_types:
            return str
        if value_types <= {int}:
            return int
        if value_types <= {str}:
            return str
        if value_types <= {int, str}:
            return int | str
        if value_types <= {bool}:
            return bool
        return str

    def get_model_choice_target_field(self, field):
        model = field.queryset.model
        if field.to_field_name:
            try:
                return model._meta.get_field(field.to_field_name)
            except FieldDoesNotExist:
                pass
        return model._meta.pk

    def _relation_form_field_example_value(self, field):
        return self._model_field_example_value(self.get_model_choice_target_field(field))

    def get_pydantic_literal_for_choices(self, choices):
        values = self.get_pydantic_choice_values(choices)
        if not values:
            return None
        return Literal.__getitem__(tuple(values))

    def get_pydantic_choice_values(self, choices, *, coerce=None):
        values = []
        seen = set()
        allowed_types = (str, int, bool)
        if coerce is not None:
            allowed_types = (str, int, bool, float, Decimal, UUID)
        for value in self.iter_choice_values(choices):
            if value in ("", None):
                continue
            if coerce is not None:
                try:
                    value = coerce(value)
                except (TypeError, ValueError):
                    continue
            elif not isinstance(value, allowed_types):
                value = str(value)
            if not isinstance(value, allowed_types):
                continue
            key = (type(value), value)
            if key not in seen:
                seen.add(key)
                values.append(value)
        return tuple(values)

    def iter_choice_values(self, choices):
        for value, label in choices:
            if isinstance(label, (list, tuple)):
                yield from self.iter_choice_values(label)
            else:
                yield value

    def _output_schema_for_fields(self, fields_key, custom_fields):
        from ninja.orm import create_schema

        cache = getattr(self, "_output_schema_cache", {})
        cache_key = (
            fields_key,
            tuple((name, repr(field_type), repr(default)) for name, field_type, default in custom_fields),
        )
        if cache_key not in cache:
            fields = list(fields_key)
            base_class = type(
                f"{self.model.__name__}AdminOutBase",
                (Schema,),
                {
                    "__module__": self.__class__.__module__,
                    "model_config": ConfigDict(
                        json_schema_extra={"examples": [self._output_schema_example(fields_key, custom_fields)]}
                    ),
                },
            )
            cache[cache_key] = create_schema(
                self.model,
                name=f"{self.model.__name__}AdminOut",
                fields=fields,
                custom_fields=custom_fields,
                base_class=base_class,
            )
            self._output_schema_cache = cache
        return cache[cache_key]

    def _output_schema_example(self, fields_key, custom_fields):
        data = {}
        field_names = set(fields_key)
        custom_field_names = {name for name, _field_type, _default in custom_fields}
        for field in self.model._meta.fields:
            if self._is_auth_password_field(field):
                continue
            if isinstance(field, models.ImageField):
                data[field.name] = {
                    "name": f"{field.name}/example.png",
                    "url": f"/media/{field.name}/example.png",
                    "width": 640,
                    "height": 480,
                }
                continue
            if isinstance(field, models.FileField):
                data[field.name] = {
                    "name": f"{field.name}/example.dat",
                    "url": f"/media/{field.name}/example.dat",
                }
                continue
            if field.remote_field and field.attname in custom_field_names:
                data[field.attname] = self._model_field_example_value(field.target_field)
                data[f"{field.name}_label"] = "Example"
                continue
            if field.name not in field_names:
                continue
            key = field.attname if field.remote_field else field.name
            example_field = field.target_field if field.remote_field else field
            data[key] = self._model_field_example_value(example_field)
            if field.remote_field:
                data[f"{field.name}_label"] = "Example"
        for field in self.model._meta.many_to_many:
            data[field.name] = [self._model_field_example_value(field.target_field)]
        for name, field_type, default in custom_fields:
            data.setdefault(name, self._schema_type_example(field_type, default))
        return data

    def _model_field_example_value(self, field):
        if field.choices:
            return self._choice_example_value(field.choices)
        if isinstance(
            field,
            models.AutoField
            | models.BigAutoField
            | models.SmallAutoField
            | models.IntegerField
            | models.BigIntegerField
            | models.PositiveIntegerField
            | models.PositiveSmallIntegerField
            | models.SmallIntegerField,
        ):
            return 1
        if isinstance(field, models.BooleanField):
            return True
        if isinstance(field, models.DecimalField):
            return "9.99"
        if isinstance(field, models.FloatField):
            return 1.5
        if isinstance(field, models.DateTimeField):
            return "2026-07-02T12:00:00+00:00"
        if isinstance(field, models.DateField):
            return "2026-07-02"
        if isinstance(field, models.TimeField):
            return "12:00:00"
        if isinstance(field, models.DurationField):
            return "01:00:00"
        if isinstance(field, models.UUIDField):
            return "00000000-0000-4000-8000-000000000000"
        if isinstance(field, models.EmailField):
            return "user@example.com"
        if isinstance(field, models.URLField):
            return "https://example.com/"
        if isinstance(field, models.GenericIPAddressField):
            return "192.0.2.1"
        if isinstance(field, models.JSONField):
            return {"example": True}
        if isinstance(field, models.BinaryField):
            return "ZXhhbXBsZQ=="
        registered_type = self.get_registered_pydantic_type_for_model_field(field)
        if registered_type is not None:
            return self._schema_type_example(registered_type, None)
        return "example"

    def _schema_type_example(self, field_type, default):
        if default is not None and default is not ...:
            return default
        origin = get_origin(field_type)
        args = get_args(field_type)
        if origin is Annotated and args:
            return self._annotated_schema_type_example(field_type, args[0], args[1:])
        if origin is Literal and args:
            return args[0]
        if origin in {list, set}:
            return [self._schema_type_example(args[0] if args else str, None)]
        if origin is tuple:
            if len(args) == 2 and args[1] is Ellipsis:
                return [self._schema_type_example(args[0], None)]
            return [self._schema_type_example(arg, None) for arg in args]
        if origin in {dict}:
            value_type = args[1] if len(args) > 1 else Any
            return {"example": self._schema_type_example(value_type, None)}
        if args:
            non_null_args = [arg for arg in args if arg is not type(None)]
            if non_null_args:
                return self._schema_type_example(non_null_args[0], None)
        if field_type is str:
            return "example"
        if field_type is int:
            return 1
        if field_type is float:
            return 1.5
        if field_type is bool:
            return True
        if field_type is Decimal:
            return "9.99"
        if field_type is UUID:
            return "00000000-0000-4000-8000-000000000000"
        if field_type is date:
            return "2026-07-02"
        if field_type is datetime:
            return "2026-07-02T12:00:00+00:00"
        if field_type is time:
            return "12:00:00"
        if field_type is timedelta:
            return "01:00:00"
        if field_type is AnyUrl:
            return "https://example.com/"
        if field_type is IPvAnyAddress:
            return "192.0.2.1"
        if field_type is FileFieldValue:
            return {"name": "files/example.dat", "url": "/media/files/example.dat"}
        if field_type is ImageFieldValue:
            return {
                "name": "images/example.png",
                "url": "/media/images/example.png",
                "width": 640,
                "height": 480,
            }
        return "example"

    def _annotated_schema_type_example(self, field_type, base_type, metadata):
        candidates = [
            self._schema_type_example(base_type, None),
            *self._constraint_example_candidates(base_type, metadata),
        ]
        adapter = TypeAdapter(field_type)
        for candidate in candidates:
            try:
                adapter.validate_python(candidate)
            except Exception:
                continue
            return candidate
        return candidates[0]

    def _constraint_example_candidates(self, base_type, metadata):
        constraints = self._constraint_metadata(metadata)
        origin = get_origin(base_type)
        args = get_args(base_type)
        if base_type is str:
            min_length = constraints.get("min_length")
            max_length = constraints.get("max_length")
            length = min_length if min_length is not None else 1
            if max_length is not None:
                length = min(length, max_length)
            return ["x" * max(0, length)]
        if base_type is int:
            return self._integer_constraint_candidates(constraints)
        if base_type is float:
            return self._float_constraint_candidates(constraints)
        if base_type is Decimal:
            return self._decimal_constraint_candidates(constraints)
        if origin in {list, set}:
            min_length = constraints.get("min_length") or 1
            item_example = self._schema_type_example(args[0] if args else str, None)
            return [[item_example for _ in range(min_length)]]
        return []

    def _constraint_metadata(self, metadata):
        constraints = {}
        for item in metadata:
            for nested in getattr(item, "metadata", ()):
                constraints.update(self._constraint_metadata((nested,)))
            for name in ("ge", "gt", "le", "lt", "min_length", "max_length"):
                value = getattr(item, name, None)
                if value is not None:
                    constraints[name] = value
        return constraints

    def _integer_constraint_candidates(self, constraints):
        candidates = []
        if "ge" in constraints:
            candidates.append(ceil(constraints["ge"]))
        if "gt" in constraints:
            candidates.append(floor(constraints["gt"]) + 1)
        if "le" in constraints:
            candidates.append(floor(constraints["le"]))
        if "lt" in constraints:
            candidates.append(ceil(constraints["lt"]) - 1)
        return candidates

    def _float_constraint_candidates(self, constraints):
        return self._ordered_numeric_constraint_candidates(constraints, float, 0.5)

    def _decimal_constraint_candidates(self, constraints):
        return [
            str(candidate)
            for candidate in self._ordered_numeric_constraint_candidates(
                constraints,
                Decimal,
                Decimal("0.01"),
            )
        ]

    def _ordered_numeric_constraint_candidates(self, constraints, coerce, exclusive_step):
        lower = None
        upper = None
        if "ge" in constraints:
            lower = coerce(constraints["ge"])
        if "gt" in constraints:
            lower = coerce(constraints["gt"]) + exclusive_step
        if "le" in constraints:
            upper = coerce(constraints["le"])
        if "lt" in constraints:
            upper = coerce(constraints["lt"]) - exclusive_step
        candidates = []
        if lower is not None and upper is not None:
            candidates.append((lower + upper) / 2)
        candidates.extend(candidate for candidate in (lower, upper) if candidate is not None)
        return candidates

    def get_output_schema(self, request=None):
        if self.output_schema is not None:
            return self.output_schema
        overrides = self.get_schema_field_overrides(request) or {}
        fields = []
        custom_fields = [self._model_field_output_custom_field(self.model._meta.pk)]
        for field in self.model._meta.fields:
            if field.name == self.model._meta.pk.name or self._is_auth_password_field(field):
                continue
            if isinstance(field, models.ImageField):
                custom_fields.append((field.name, ImageFieldValue | None, None))
            elif isinstance(field, models.FileField):
                custom_fields.append((field.name, FileFieldValue | None, None))
            elif field.remote_field:
                custom_fields.append(self._relation_output_custom_field(field))
            elif field.choices:
                custom_fields.append(self._choice_output_custom_field(field))
            elif (
                isinstance(
                    field,
                    (models.DecimalField, models.EmailField, models.URLField, models.BinaryField, models.JSONField),
                )
                or self.get_pydantic_pattern_for_model_field(field)
                or self.get_pydantic_string_validator_constraints_for_model_field(field)
                or self.get_pydantic_step_constraint_for_model_field(field)
                or self.get_pydantic_numeric_bounds_for_model_field(field)
                or (field.blank and not field.null)
            ):
                custom_fields.append(self._model_field_output_custom_field(field))
            else:
                fields.append(field.name)
        for field in self.model._meta.fields:
            if field.remote_field and not self._is_auth_password_field(field):
                custom_fields.append((f"{field.name}_label", str, None))
        for field in self.model._meta.many_to_many:
            custom_fields.append(
                (field.name, list[self.get_pydantic_type_for_model_output_field(field.target_field)], [])
            )
        custom_fields.extend(
            (name, field_type, default)
            for name, value in overrides.items()
            for field_type, default in [self._normalize_schema_override(value)]
        )
        return self._output_schema_for_fields(tuple(fields), tuple(custom_fields))

    def _model_field_output_custom_field(self, field):
        field_type = self.get_pydantic_type_for_model_output_field(field)
        if field.null:
            return field.name, field_type | None, None
        return field.name, field_type, ...

    def get_pydantic_type_for_model_output_field(self, field):
        field_type = self.get_pydantic_type_for_model_field(field)
        constraints = self.get_pydantic_constraints_for_model_field(field, field_type)
        if constraints:
            return Annotated[field_type, Field(**constraints)]
        return field_type

    def get_pydantic_constraints_for_model_field(self, field, field_type=None):
        constraints = {}
        if field_type is str:
            if getattr(field, "max_length", None) is not None:
                constraints["max_length"] = field.max_length
            constraints.update(self.get_pydantic_string_validator_constraints_for_model_field(field))
            pattern = self.get_pydantic_pattern_for_model_field(field)
            if pattern:
                constraints["pattern"] = pattern
        if isinstance(field, models.EmailField):
            constraints["json_schema_extra"] = {"format": "email"}
        elif isinstance(field, models.URLField):
            constraints["json_schema_extra"] = {"format": "uri"}
        elif isinstance(field, models.BinaryField):
            constraints["json_schema_extra"] = {
                "contentEncoding": "base64",
                "contentMediaType": "application/octet-stream",
            }
        if isinstance(field, models.DecimalField):
            if getattr(field, "max_digits", None) is not None:
                constraints["max_digits"] = field.max_digits
            if getattr(field, "decimal_places", None) is not None:
                constraints["decimal_places"] = field.decimal_places
        constraints.update(self.get_pydantic_numeric_bounds_for_model_field(field))
        constraints.update(self.get_pydantic_step_constraint_for_model_field(field))
        return constraints

    def get_pydantic_numeric_bounds_for_model_field(self, field):
        bounds = {}
        for validator in getattr(field, "validators", ()):
            limit_value = getattr(validator, "limit_value", None)
            if callable(limit_value):
                try:
                    limit_value = limit_value()
                except Exception:
                    continue
            if isinstance(validator, MinValueValidator):
                bound = self.pydantic_numeric_bound_value(field, limit_value)
                bounds["ge"] = max(bounds.get("ge", bound), bound)
            elif isinstance(validator, MaxValueValidator):
                bound = self.pydantic_numeric_bound_value(field, limit_value)
                bounds["le"] = min(bounds.get("le", bound), bound)
        return bounds

    def get_pydantic_step_constraint_for_model_field(self, field):
        step_validator = self.get_step_value_validator(field)
        if step_validator is None or not self.step_validator_has_zero_offset(step_validator):
            return {}
        limit_value = getattr(step_validator, "limit_value", None)
        if callable(limit_value):
            try:
                limit_value = limit_value()
            except Exception:
                return {}
        return {"multiple_of": self.pydantic_step_value(field, limit_value)}

    def get_pydantic_string_validator_constraints_for_model_field(self, field):
        constraints = {}
        field_max_length = getattr(field, "max_length", None)
        for validator in getattr(field, "validators", ()):
            limit_value = getattr(validator, "limit_value", None)
            if callable(limit_value):
                try:
                    limit_value = limit_value()
                except Exception:
                    continue
            if isinstance(validator, MinLengthValidator):
                constraints["min_length"] = max(constraints.get("min_length", limit_value), limit_value)
            elif isinstance(validator, MaxLengthValidator) and (
                field_max_length is None or limit_value < field_max_length
            ):
                constraints["max_length"] = min(constraints.get("max_length", limit_value), limit_value)
        return constraints

    def get_pydantic_pattern_for_model_field(self, field):
        for validator in getattr(field, "validators", ()):
            if isinstance(validator, RegexValidator):
                pattern = self.normalize_pydantic_pattern(getattr(validator, "regex", None))
                if pattern and self.pydantic_pattern_is_supported(pattern):
                    return pattern
        return None

    def _relation_output_custom_field(self, field):
        field_type = self.get_pydantic_type_for_model_output_field(field.target_field)
        if field.null:
            return field.attname, field_type | None, None
        return field.attname, field_type, ...

    def _choice_output_custom_field(self, field):
        field_type = self.get_pydantic_type_for_choices(field.choices)
        if field.null:
            return field.name, field_type | None, None
        if field.default is not models.NOT_PROVIDED and not callable(field.default):
            return field.name, field_type, field.default
        return field.name, field_type, ...

    def _normalize_schema_override(self, value):
        if isinstance(value, tuple):
            if len(value) == 2:
                return value
            if len(value) == 1:
                return value[0], None
        return value, None

    def get_pydantic_type_for_model_field(self, field):
        if isinstance(
            field,
            models.AutoField
            | models.BigAutoField
            | models.SmallAutoField
            | models.IntegerField
            | models.BigIntegerField
            | models.PositiveIntegerField
            | models.PositiveSmallIntegerField
            | models.SmallIntegerField,
        ):
            return int
        if isinstance(field, models.BooleanField):
            return bool
        if isinstance(field, models.DecimalField):
            return Decimal
        if isinstance(field, models.FloatField):
            return float
        if isinstance(field, models.DateTimeField):
            return datetime
        if isinstance(field, models.DateField):
            return date
        if isinstance(field, models.TimeField):
            return time
        if isinstance(field, models.DurationField):
            return timedelta
        if isinstance(field, models.UUIDField):
            return UUID
        if isinstance(field, models.GenericIPAddressField):
            return IPvAnyAddress
        if isinstance(field, models.JSONField):
            return AdminJsonValue
        if isinstance(field, models.BinaryField):
            return str
        registered_type = self.get_registered_pydantic_type_for_model_field(field)
        if registered_type is not None:
            return registered_type
        return str

    def get_registered_pydantic_type_for_model_field(self, field):
        from ninja.orm.fields import TYPES

        return TYPES.get(field.get_internal_type())

    def _schema_override_cache_key(self, overrides):
        return tuple((name, repr(value)) for name, value in overrides.items())

    def get_form_fields_description(self, request, obj=None, *, initial=None, form=None):
        form_class = form.__class__ if form is not None else self.get_form_class(request, obj, change=obj is not None)
        descriptions = form_field_descriptions(
            form_class,
            request=request,
            form=form,
            readonly_fields=self.get_readonly_fields(request, obj),
            instance=obj,
            initial=initial,
            model_admin=self,
            empty_value_display=self.get_empty_value_display(),
            autocomplete_fields=self.get_autocomplete_fields(request),
            raw_id_fields=self.raw_id_fields,
            filter_horizontal=self.filter_horizontal,
            filter_vertical=self.filter_vertical,
            radio_fields=self.radio_fields,
            prepopulated_fields=self.get_prepopulated_fields(request, obj),
        )
        return self.apply_form_schema_field_override_metadata(
            descriptions,
            request,
            obj,
            change=obj is not None,
        )

    def get_changelist_form_fields_description(self, request, obj=None, *, form=None):
        form_class = form.__class__ if form is not None else self.get_changelist_form_class(request)
        descriptions = form_field_descriptions(
            form_class,
            request=request,
            form=form,
            instance=obj,
            model_admin=self,
            empty_value_display=self.get_empty_value_display(),
            autocomplete_fields=self.get_autocomplete_fields(request),
            raw_id_fields=self.raw_id_fields,
            filter_horizontal=self.filter_horizontal,
            filter_vertical=self.filter_vertical,
            radio_fields=self.radio_fields,
            prepopulated_fields=self.get_prepopulated_fields(request, obj),
        )
        return self.apply_form_schema_field_override_metadata(descriptions, request, obj, change=True)

    def apply_form_schema_field_override_metadata(self, descriptions, request=None, obj=None, *, change=False):
        overrides = self.get_form_schema_field_overrides(request, obj, change=change) or {}
        if not overrides:
            return descriptions
        for description in descriptions:
            override = overrides.get(description["name"])
            if override is None:
                continue
            description["attrs"]["input_schema_override"] = self.form_schema_field_override_metadata(override)
        return descriptions

    def form_schema_field_override_metadata(self, override):
        field_type, _default = self._normalize_schema_override(override)
        return {"schema": TypeAdapter(field_type).json_schema()}

    def get_changeform_initial_data(self, request):
        initial = dict(getattr(request, "GET", {}).items())
        for name, value in list(initial.items()):
            try:
                field = self.opts.get_field(name)
            except FieldDoesNotExist:
                continue
            if isinstance(field, models.ManyToManyField):
                initial[name] = value.split(",") if value else []
        return initial

    def serialize_object(self, obj, request=None):
        schema = self.get_output_schema(request)
        data = {}
        for field in obj._meta.fields:
            if self._is_auth_password_field(field):
                continue
            value = getattr(obj, field.name)
            if isinstance(field, models.ImageField):
                data[field.name] = image_value_metadata(value)
                continue
            if isinstance(field, models.FileField):
                data[field.name] = file_value_metadata(value)
                continue
            field_key = field.attname if field.remote_field else field.name
            field_value = field.value_from_object(obj)
            if isinstance(field, models.BinaryField):
                field_value = _base64_binary_value(field_value)
            data[field_key] = field_value
            if field.remote_field and value is not None:
                data[f"{field.name}_label"] = str(value)
        for field in obj._meta.many_to_many:
            data[field.name] = list(getattr(obj, field.name).values_list("pk", flat=True)) if obj.pk else []
        for name in self.get_schema_field_overrides(request) or {}:
            if name in data:
                continue
            data[name] = self._schema_override_value(obj, name)
        return schema.model_validate(data).model_dump(mode="json", by_alias=True)

    def _is_auth_password_field(self, field):
        return field.name == "password" and issubclass(self.model, AbstractBaseUser)

    def _schema_override_value(self, obj, name):
        if hasattr(obj, name):
            value = getattr(obj, name)
            return value() if callable(value) else value
        value = getattr(self, name, None)
        if callable(value):
            return value(obj)
        return value

    def get_form_description(self, request, obj=None, **kwargs):
        initial = self.get_changeform_initial_data(request) if obj is None else None
        form_class = self.get_form_class(request, obj, change=obj is not None)
        form = form_class(instance=obj, initial=initial)
        fieldsets = self.get_fieldsets(request, obj)
        permissions = {
            "has_add_permission": self.has_add_permission(request),
            "has_change_permission": self.has_change_permission(request, obj),
            "has_delete_permission": self.has_delete_permission(request, obj),
            "has_view_permission": self.has_view_permission(request, obj),
        }
        form_description = {
            "model": f"{self.model._meta.app_label}.{self.model._meta.model_name}",
            "readonly_fields": [field_name_for_display(field) for field in self.get_readonly_fields(request, obj)],
            "fields": self.get_form_fields_description(request, obj, initial=initial),
            "media": form_media_description(form),
            "fieldsets": list(fieldsets),
            "fieldset_layout": fieldset_layout_description(fieldsets),
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
        from django.contrib.admin.widgets import url_params_from_lookup_dict

        from django_ninja_admin.filters import SimpleListFilter

        model = self.model
        for fk_lookup in model._meta.related_fkey_lookups:
            if callable(fk_lookup):
                fk_lookup = fk_lookup()
            if (lookup, value) in url_params_from_lookup_dict(fk_lookup).items():
                return True

        relation_parts = []
        previous_field = None
        lookup_parts = lookup.split("__")
        for part in lookup_parts:
            try:
                field = model._meta.get_field(part)
            except FieldDoesNotExist:
                break
            if not previous_field or (
                previous_field.is_relation
                and field not in model._meta.parents.values()
                and field is not model._meta.auto_field
                and (model._meta.auto_field is None or part not in getattr(previous_field, "to_fields", []))
                and (field.is_relation or not field.primary_key)
            ):
                relation_parts.append(part)
            if not getattr(field, "path_infos", None):
                break
            previous_field = field
            model = field.path_infos[-1].to_opts.model

        if len(relation_parts) <= 1:
            return True

        valid_lookups = {getattr(self, "date_hierarchy", None)}
        for filter_item in self.get_list_filter(request):
            if isinstance(filter_item, type) and issubclass(filter_item, SimpleListFilter):
                valid_lookups.add(filter_item.parameter_name)
            elif isinstance(filter_item, (list, tuple)) and filter_item:
                valid_lookups.add(filter_item[0])
            else:
                valid_lookups.add(filter_item)

        relation_lookup = "__".join(relation_parts)
        relation_lookup_with_part = "__".join([*relation_parts, part])
        return not {relation_lookup, relation_lookup_with_part}.isdisjoint(valid_lookups)

    def to_field_allowed(self, request, to_field):
        try:
            field = self.opts.get_field(to_field)
        except FieldDoesNotExist:
            return False
        if field.primary_key:
            return True
        for many_to_many in self.opts.many_to_many:
            if many_to_many.m2m_target_field_name() == to_field:
                return True
        registered_models = set()
        for model, admin in self.admin_site._registry.items():
            registered_models.add(model)
            for inline in getattr(admin, "inlines", ()) or ():
                inline_model = getattr(inline, "model", None)
                if inline_model is not None:
                    registered_models.add(inline_model)
        related_objects = (
            field for field in self.opts.get_fields(include_hidden=True) if field.auto_created and not field.concrete
        )
        for related_object in related_objects:
            related_model = related_object.related_model
            remote_field = related_object.field.remote_field
            if (
                any(issubclass(model, related_model) for model in registered_models)
                and hasattr(remote_field, "get_related_field")
                and remote_field.get_related_field() == field
            ):
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
