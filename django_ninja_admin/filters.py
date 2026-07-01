from __future__ import annotations

import datetime

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

NULL_BOOLEAN_FIELD = getattr(models, "NullBooleanField", None)
BOOLEAN_FIELD_TYPES = (
    (models.BooleanField,)
    if NULL_BOOLEAN_FIELD is None
    else (models.BooleanField, NULL_BOOLEAN_FIELD)
)


def _lookup_value(value):
    raw = getattr(value, "value", value)
    return str(raw) if raw is not None else None


def _bool_value(value):
    return str(value).lower() in {"1", "true", "t", "yes", "y", "on"}


def _display(value):
    return str(value)


def _field_is_empty_lookup_supported(field):
    return isinstance(field, (models.CharField, models.TextField))


class ListFilter:
    title: str | None = None
    parameter_name: str | None = None

    def __init__(self, request, params, model, model_admin):
        self.request = request
        self.params = params
        self.model = model
        self.model_admin = model_admin
        self.used_parameters = {}

    def expected_parameters(self):
        if self.parameter_name is None:
            return []
        return [self.parameter_name]

    def has_output(self):
        return True

    def value(self):
        if self.parameter_name is None:
            return None
        return self.used_parameters.get(self.parameter_name)

    def queryset(self, request, queryset):
        return queryset

    def choices(self, changelist):
        return []

    def as_dict(self, changelist):
        choices = list(self.choices(changelist))
        if changelist.show_facets:
            for choice in choices:
                choice["count"] = changelist.count_for_query_string(choice["query_string"])
        return {
            "title": str(self.title or ""),
            "parameter_name": self.parameter_name or "",
            "choices": choices,
        }


class SimpleListFilter(ListFilter):
    def __init__(self, request, params, model, model_admin):
        super().__init__(request, params, model, model_admin)
        if self.parameter_name is None:
            raise ImproperlyConfigured(
                f"The list filter {self.__class__.__name__!r} does not specify a 'parameter_name'."
            )
        if self.parameter_name in params:
            self.used_parameters[self.parameter_name] = params.get(self.parameter_name)
        if self.title is None:
            self.title = self.parameter_name.replace("_", " ")
        self.lookup_choices = list(self.lookups(request, model_admin) or ())

    def lookups(self, request, model_admin):
        return ()

    def choices(self, changelist):
        current_value = self.value()
        yield {
            "selected": current_value is None,
            "query_string": changelist.get_query_string(remove=self.expected_parameters()),
            "display": _display(_("All")),
        }
        for lookup, title in self.lookup_choices:
            lookup = _lookup_value(lookup)
            yield {
                "selected": str(current_value) == str(lookup),
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": _display(title),
            }

    def has_output(self):
        return bool(self.lookup_choices)


class FieldListFilter(ListFilter):
    lookup_suffix = "__exact"

    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(request, params, model, model_admin)
        self.field = field
        self.field_path = field_path
        self.title = str(getattr(field, "verbose_name", field_path))
        self.parameter_name = f"{field_path}{self.lookup_suffix}"
        self.lookup_kwarg = self.parameter_name
        self.legacy_lookup_kwarg = field_path
        self.used_parameters = self._used_parameters(params)

    @classmethod
    def create(cls, field, request, params, model, model_admin, field_path):
        if getattr(field, "choices", None):
            filter_class = ChoicesFieldListFilter
        elif isinstance(field, BOOLEAN_FIELD_TYPES):
            filter_class = BooleanFieldListFilter
        elif isinstance(field, (models.DateField, models.DateTimeField)):
            filter_class = DateFieldListFilter
        elif getattr(field, "remote_field", None):
            filter_class = RelatedFieldListFilter
        else:
            filter_class = AllValuesFieldListFilter
        return filter_class(field, request, params, model, model_admin, field_path)

    def expected_parameters(self):
        return [self.lookup_kwarg, self.legacy_lookup_kwarg]

    def _used_parameters(self, params):
        used = {}
        if self.lookup_kwarg in params:
            used[self.lookup_kwarg] = params.get(self.lookup_kwarg)
        elif self.legacy_lookup_kwarg in params:
            used[self.lookup_kwarg] = params.get(self.legacy_lookup_kwarg)
        return used

    def queryset(self, request, queryset):
        if not self.used_parameters:
            return queryset
        return queryset.filter(**self.used_parameters)

    def choices(self, changelist):
        current_value = self.used_parameters.get(self.lookup_kwarg)
        yield {
            "selected": current_value is None,
            "query_string": changelist.get_query_string(remove=self.expected_parameters()),
            "display": _display(_("All")),
        }
        for value, label in self.field_choices(changelist):
            value = _lookup_value(value)
            yield {
                "selected": str(current_value) == str(value),
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg: value},
                    remove=[self.legacy_lookup_kwarg],
                ),
                "display": _display(label),
            }

    def field_choices(self, changelist):
        return ()


class ChoicesFieldListFilter(FieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        self.lookup_kwarg_isnull = f"{field_path}__isnull"
        if self.lookup_kwarg_isnull in params:
            self.used_parameters = {self.lookup_kwarg_isnull: _bool_value(params.get(self.lookup_kwarg_isnull))}

    def expected_parameters(self):
        return [self.lookup_kwarg, self.legacy_lookup_kwarg, self.lookup_kwarg_isnull]

    def field_choices(self, changelist):
        return list(self.field.flatchoices)

    def choices(self, changelist):
        current_value = self.used_parameters.get(self.lookup_kwarg)
        selected_isnull = self.used_parameters.get(self.lookup_kwarg_isnull)
        yield {
            "selected": not self.used_parameters,
            "query_string": changelist.get_query_string(remove=self.expected_parameters()),
            "display": _display(_("All")),
        }
        none_label = None
        for value, label in self.field_choices(changelist):
            if value is None:
                none_label = label
                continue
            value = _lookup_value(value)
            yield {
                "selected": str(current_value) == str(value),
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg: value},
                    remove=[self.lookup_kwarg_isnull, self.legacy_lookup_kwarg],
                ),
                "display": _display(label),
            }
        if none_label is not None:
            yield {
                "selected": selected_isnull is True,
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg_isnull: "1"},
                    remove=[self.lookup_kwarg, self.legacy_lookup_kwarg],
                ),
                "display": _display(none_label),
            }


class BooleanFieldListFilter(FieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        self.lookup_kwarg_isnull = f"{field_path}__isnull"
        if self.lookup_kwarg_isnull in params:
            self.used_parameters = {self.lookup_kwarg_isnull: _bool_value(params.get(self.lookup_kwarg_isnull))}

    def expected_parameters(self):
        return [self.lookup_kwarg, self.legacy_lookup_kwarg, self.lookup_kwarg_isnull]

    def choices(self, changelist):
        selected_exact = self.used_parameters.get(self.lookup_kwarg)
        selected_isnull = self.used_parameters.get(self.lookup_kwarg_isnull)
        yield {
            "selected": not self.used_parameters,
            "query_string": changelist.get_query_string(remove=self.expected_parameters()),
            "display": _display(_("All")),
        }
        for value, label in (("1", _("Yes")), ("0", _("No"))):
            yield {
                "selected": str(selected_exact) == value,
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg: value},
                    remove=[self.lookup_kwarg_isnull, self.legacy_lookup_kwarg],
                ),
                "display": _display(label),
            }
        if self.field.null:
            yield {
                "selected": selected_isnull is True,
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg_isnull: "1"},
                    remove=[self.lookup_kwarg, self.legacy_lookup_kwarg],
                ),
                "display": _display(_("Unknown")),
            }


class RelatedFieldListFilter(FieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        target_field = field.target_field
        self.lookup_kwarg = f"{field_path}__{target_field.name}__exact"
        self.parameter_name = self.lookup_kwarg
        self.lookup_kwarg_isnull = f"{field_path}__isnull"
        self.used_parameters = self._used_parameters(params)
        if self.lookup_kwarg_isnull in params:
            self.used_parameters = {self.lookup_kwarg_isnull: _bool_value(params.get(self.lookup_kwarg_isnull))}

    def expected_parameters(self):
        return [self.lookup_kwarg, self.legacy_lookup_kwarg, self.lookup_kwarg_isnull]

    @property
    def include_empty_choice(self):
        return self.field.null or (
            getattr(self.field, "is_relation", False) and getattr(self.field, "many_to_many", False)
        )

    def has_output(self):
        extra = 1 if self.include_empty_choice else 0
        return len(self.field_choices(None)) + extra > 1

    def get_related_queryset(self):
        related_model = self.field.remote_field.model
        queryset = related_model._default_manager.all()
        try:
            related_admin = self.model_admin.admin_site.get_model_admin(related_model)
            ordering = related_admin.get_ordering(self.request)
            if ordering:
                queryset = queryset.order_by(*ordering)
        except Exception:
            queryset = queryset.order_by(related_model._meta.pk.name)
        return queryset

    def field_choices(self, changelist):
        return [(obj.pk, str(obj)) for obj in self.get_related_queryset()]

    def choices(self, changelist):
        yield from super().choices(changelist)
        if self.include_empty_choice:
            selected = self.used_parameters.get(self.lookup_kwarg_isnull) is True
            yield {
                "selected": selected,
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg_isnull: "1"},
                    remove=[self.lookup_kwarg, self.legacy_lookup_kwarg],
                ),
                "display": _display(_("None")),
            }


class RelatedOnlyFieldListFilter(RelatedFieldListFilter):
    def field_choices(self, changelist):
        ids = (
            self.model_admin.get_queryset(self.request)
            .exclude(**{f"{self.field_path}__isnull": True})
            .values_list(self.field_path, flat=True)
            .distinct()
        )
        queryset = self.get_related_queryset().filter(pk__in=ids)
        return [(obj.pk, str(obj)) for obj in queryset]


class AllValuesFieldListFilter(FieldListFilter):
    def field_choices(self, changelist):
        queryset = self.model_admin.get_queryset(self.request)
        values = queryset.order_by(self.field_path).values_list(self.field_path, flat=True).distinct()
        return [(value, self.field_display(value)) for value in values]

    def field_display(self, value):
        return self.model_admin.get_empty_value_display() if value in (None, "") else value


class EmptyFieldListFilter(FieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        if not (field.empty_strings_allowed or field.null or _field_is_empty_lookup_supported(field)):
            raise ImproperlyConfigured(
                f"The field {field_path!r} cannot use EmptyFieldListFilter because it has no empty value state."
            )
        super().__init__(field, request, params, model, model_admin, field_path)
        self.lookup_kwarg = f"{field_path}__isempty"
        self.parameter_name = self.lookup_kwarg
        self.used_parameters = {}
        if self.lookup_kwarg in params:
            self.used_parameters[self.lookup_kwarg] = params.get(self.lookup_kwarg)

    def expected_parameters(self):
        return [self.lookup_kwarg]

    def queryset(self, request, queryset):
        value = self.used_parameters.get(self.lookup_kwarg)
        if value is None:
            return queryset
        if value not in {"0", "1"}:
            raise ValueError("Invalid empty filter value.")
        empty_q = Q(**{f"{self.field_path}__isnull": True})
        if _field_is_empty_lookup_supported(self.field):
            empty_q |= Q(**{self.field_path: ""})
        if _bool_value(value):
            return queryset.filter(empty_q)
        return queryset.exclude(empty_q)

    def choices(self, changelist):
        current_value = self.used_parameters.get(self.lookup_kwarg)
        yield {
            "selected": current_value is None,
            "query_string": changelist.get_query_string(remove=self.expected_parameters()),
            "display": _display(_("All")),
        }
        for value, label in (("1", _("Empty")), ("0", _("Not empty"))):
            yield {
                "selected": str(current_value) == value,
                "query_string": changelist.get_query_string({self.lookup_kwarg: value}),
                "display": _display(label),
            }


class DateFieldListFilter(FieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        self.field_generic = f"{field_path}__"
        self.lookup_kwarg_since = f"{field_path}__gte"
        self.lookup_kwarg_until = f"{field_path}__lt"
        self.lookup_kwarg_isnull = f"{field_path}__isnull"
        self.used_parameters = {
            key: params.get(key)
            for key in self.expected_parameters()
            if key in params and params.get(key) not in ("", None)
        }
        if self.lookup_kwarg_isnull in self.used_parameters:
            self.used_parameters = {
                self.lookup_kwarg_isnull: _bool_value(self.used_parameters[self.lookup_kwarg_isnull])
            }
        self.links = self.get_links()

    def expected_parameters(self):
        parameters = [self.lookup_kwarg_since, self.lookup_kwarg_until]
        if self.field.null:
            parameters.append(self.lookup_kwarg_isnull)
        return parameters

    def get_links(self):
        now = timezone.now()
        if timezone.is_aware(now):
            now = timezone.localtime(now)
        if isinstance(self.field, models.DateTimeField):
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            today = now.date()
        tomorrow = today + datetime.timedelta(days=1)
        if today.month == 12:
            next_month = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month = today.replace(month=today.month + 1, day=1)
        next_year = today.replace(year=today.year + 1, month=1, day=1)
        links = [
            (_display(_("Any date")), {}),
            (
                _display(_("Today")),
                {self.lookup_kwarg_since: today, self.lookup_kwarg_until: tomorrow},
            ),
            (
                _display(_("Past 7 days")),
                {
                    self.lookup_kwarg_since: today - datetime.timedelta(days=7),
                    self.lookup_kwarg_until: tomorrow,
                },
            ),
            (
                _display(_("This month")),
                {self.lookup_kwarg_since: today.replace(day=1), self.lookup_kwarg_until: next_month},
            ),
            (
                _display(_("This year")),
                {self.lookup_kwarg_since: today.replace(month=1, day=1), self.lookup_kwarg_until: next_year},
            ),
        ]
        if self.field.null:
            links.extend(
                [
                    (_display(_("No date")), {self.lookup_kwarg_isnull: True}),
                    (_display(_("Has date")), {self.lookup_kwarg_isnull: False}),
                ]
            )
        return links

    def choices(self, changelist):
        current_params = {key: str(value) for key, value in self.used_parameters.items()}
        for label, params in self.links:
            params = {key: str(value) for key, value in params.items()}
            if params:
                selected = current_params == params
                query_string = changelist.get_query_string(params, remove=[self.field_generic])
            else:
                selected = not self.used_parameters
                query_string = changelist.get_query_string(remove=[self.field_generic])
            yield {"selected": selected, "query_string": query_string, "display": _display(label)}


def get_fields_from_path(model, field_path):
    pieces = field_path.split("__")
    fields = []
    current_model = model
    for piece in pieces:
        field = current_model._meta.get_field(piece)
        fields.append(field)
        if getattr(field, "remote_field", None) and field.remote_field.model:
            current_model = field.remote_field.model
    return fields


def build_filter_spec(filter_entry, request, params, model, model_admin):
    if isinstance(filter_entry, type) and issubclass(filter_entry, SimpleListFilter):
        return filter_entry(request, params, model, model_admin)

    if isinstance(filter_entry, (tuple, list)):
        field_path, filter_class = filter_entry
    else:
        field_path = filter_entry
        filter_class = None

    if not isinstance(field_path, str):
        raise ImproperlyConfigured(f"Unsupported list_filter entry: {filter_entry!r}.")

    try:
        field = get_fields_from_path(model, field_path)[-1]
    except FieldDoesNotExist as exc:
        raise ImproperlyConfigured(f"The list_filter field {field_path!r} does not exist.") from exc

    if filter_class is None:
        return FieldListFilter.create(field, request, params, model, model_admin, field_path)
    if issubclass(filter_class, SimpleListFilter):
        return filter_class(request, params, model, model_admin)
    if issubclass(filter_class, FieldListFilter):
        return filter_class(field, request, params, model, model_admin, field_path)
    raise ImproperlyConfigured(f"Unsupported list_filter class for {field_path!r}: {filter_class!r}.")


def title_for_parameter(parameter_name):
    return capfirst(parameter_name.replace("_", " "))
