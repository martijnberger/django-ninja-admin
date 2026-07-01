from __future__ import annotations

import calendar

from django.core.exceptions import FieldDoesNotExist, FieldError, PermissionDenied, ValidationError
from django.core.paginator import InvalidPage
from django.db import models
from django.http import Http404, QueryDict
from django.utils import timezone

from django_ninja_admin.constants import ShowFacets
from django_ninja_admin.exceptions import AdminValidationError, DisallowedModelAdminLookup
from django_ninja_admin.filters import build_filter_spec
from django_ninja_admin.utils.lookup import (
    field_name_for_display,
    model_field_from_path,
    single_valued_model_field_from_path,
)

IGNORED_LOOKUP_PARAMS = {"q", "p", "page", "pp", "all", "o", "_facets"}
PAGE_PARAMS = {"p", "page"}


class ChangeList:
    def __init__(self, request, model_admin):
        self.request = request
        self.model_admin = model_admin
        self.model = model_admin.model
        self.params = request.GET
        self.list_display = tuple(model_admin.get_list_display(request))
        self.list_display_links = model_admin.get_list_display_links(request, self.list_display)
        self.list_filter = tuple(model_admin.get_list_filter(request))
        self.list_select_related = model_admin.get_list_select_related(request)
        self.search_fields = tuple(model_admin.get_search_fields(request))
        self.sortable_by = tuple(model_admin.get_sortable_by(request))
        self.date_hierarchy_model_field = None
        self.date_hierarchy_field = self.get_date_hierarchy_field()
        self.filter_specs = self.get_filters(self.params)
        self.queryset = self.get_queryset(self.params, self.filter_specs)
        self.show_full_result_count = bool(getattr(model_admin, "show_full_result_count", True))
        self.full_result_count = model_admin.get_queryset(request).count() if self.show_full_result_count else None
        self.result_count = self.queryset.count()
        self.show_admin_actions = not self.show_full_result_count or bool(self.full_result_count)
        self.per_page = self.get_per_page()
        self.show_all = self.can_show_all()
        self.can_show_all_results = self.result_count <= self.model_admin.list_max_show_all
        self.multi_page = self.result_count > self.per_page
        self.pagination_required = self.multi_page and not self.show_all
        self.show_facets = self.should_show_facets()
        page_size = (self.result_count or 1) if self.show_all else self.per_page
        self.paginator = model_admin.paginator(self.queryset, page_size)
        self.page_num = 1 if self.show_all else self.get_page_number()
        self.page = self.get_page()
        self.result_list = list(self.page.object_list)
        self.ordering = self.get_ordering(self.params)

    def get_filters(self, params):
        filter_specs = []
        for list_filter in self.list_filter:
            filter_spec = build_filter_spec(
                list_filter,
                self.request,
                params,
                self.model,
                self.model_admin,
            )
            filter_specs.append(filter_spec)
        return filter_specs

    def expected_filter_params(self, filter_specs):
        expected = set()
        for filter_spec in filter_specs:
            expected.update(filter_spec.expected_parameters())
        return expected

    def expected_special_params(self, filter_specs):
        return IGNORED_LOOKUP_PARAMS | self.expected_filter_params(filter_specs) | set(self.date_hierarchy_param_names)

    def get_queryset(self, params, filter_specs, *, apply_date_hierarchy=True, apply_ordering=True):
        if not self.model_admin.has_view_or_change_permission(self.request):
            raise PermissionDenied

        queryset = self.model_admin.get_queryset(self.request)
        queryset = self.apply_select_related(queryset)
        for filter_spec in filter_specs:
            try:
                queryset = filter_spec.queryset(self.request, queryset)
            except (FieldError, TypeError, ValueError, ValidationError) as exc:
                raise self.lookup_value_error(filter_spec.used_parameters or {}, fallback_param="filters") from exc
        queryset = self.apply_remaining_lookup_params(queryset, params, filter_specs)
        if apply_date_hierarchy:
            queryset = self.apply_date_hierarchy(queryset, params)
        queryset = self.apply_search(queryset, params)
        if apply_ordering:
            queryset = self.apply_ordering(queryset, params)
        return queryset

    def apply_select_related(self, queryset):
        if self.list_select_related is True:
            return queryset.select_related()
        if self.list_select_related:
            return queryset.select_related(*self.list_select_related)
        related_fields = self.auto_select_related_fields()
        if related_fields:
            return queryset.select_related(*related_fields)
        return queryset

    def auto_select_related_fields(self):
        if self.list_select_related is not False:
            return []
        related_fields = []
        for field_name in self.list_display:
            if not isinstance(field_name, str):
                ordering_field = self.get_ordering_field(field_name)
                related_path = self.select_related_path_for_ordering(ordering_field)
                if related_path and related_path not in related_fields:
                    related_fields.append(related_path)
                continue
            field = None
            try:
                field = self.model._meta.get_field(field_name)
            except FieldDoesNotExist:
                pass
            if isinstance(field, (models.ForeignKey, models.OneToOneField)) and field.name not in related_fields:
                related_fields.append(field.name)
                continue
            related_path = self.select_related_path_for_ordering(field_name)
            if related_path and related_path not in related_fields:
                related_fields.append(related_path)
                continue
            ordering_field = self.get_ordering_field(field_name)
            related_path = self.select_related_path_for_ordering(ordering_field)
            if related_path and related_path not in related_fields:
                related_fields.append(related_path)
        return related_fields

    def select_related_path_for_ordering(self, ordering_field):
        if not isinstance(ordering_field, str) or "__" not in ordering_field:
            return None

        opts = self.model._meta
        related_parts = []
        for path_part in ordering_field.split("__")[:-1]:
            if path_part == "pk":
                path_part = opts.pk.name
            try:
                field = opts.get_field(path_part)
            except FieldDoesNotExist:
                return None
            if not isinstance(field, (models.ForeignKey, models.OneToOneField)):
                return None
            related_parts.append(field.name)
            opts = field.remote_field.model._meta
        return "__".join(related_parts) if related_parts else None

    def apply_remaining_lookup_params(self, queryset, params, filter_specs):
        for key, value in params.items():
            if key in self.expected_special_params(filter_specs) or value in ("", None):
                continue
            if not self.model_admin.lookup_allowed(key, value, self.request):
                raise DisallowedModelAdminLookup(f"Filtering by {key!r} is not allowed.")
            try:
                queryset = queryset.filter(**{key: value})
            except (FieldError, TypeError, ValueError, ValidationError) as exc:
                raise self.lookup_value_error({key: value}, fallback_param=key) from exc
        return queryset

    def lookup_value_error(self, params, *, fallback_param):
        param = next(iter(params), fallback_param)
        return AdminValidationError([{"message": "Invalid lookup value.", "param": param}])

    def apply_search(self, queryset, params):
        search_term = params.get("q")
        if not search_term:
            return queryset
        queryset, use_distinct = self.model_admin.get_search_results(self.request, queryset, search_term)
        if use_distinct:
            queryset = queryset.distinct()
        return queryset

    @property
    def date_hierarchy_param_names(self):
        if not self.date_hierarchy_field:
            return ()
        return (
            f"{self.date_hierarchy_field}__year",
            f"{self.date_hierarchy_field}__month",
            f"{self.date_hierarchy_field}__day",
        )

    def get_date_hierarchy_field(self):
        field_name = getattr(self.model_admin, "date_hierarchy", None)
        if not field_name:
            return None
        try:
            field = model_field_from_path(self.model, field_name)
        except FieldDoesNotExist as exc:
            raise AdminValidationError(
                [{"message": f"The date_hierarchy field {field_name!r} does not exist.", "param": "date_hierarchy"}]
            ) from exc
        if not isinstance(field, (models.DateField, models.DateTimeField)):
            raise AdminValidationError(
                [
                    {
                        "message": f"The date_hierarchy field {field_name!r} is not a date field.",
                        "param": "date_hierarchy",
                    }
                ]
            )
        self.date_hierarchy_model_field = field
        return field_name

    def get_date_hierarchy_values(self, params):
        if not self.date_hierarchy_field:
            return {}
        values = {}
        for part, lower, upper in (("year", 1, 9999), ("month", 1, 12), ("day", 1, 31)):
            param = f"{self.date_hierarchy_field}__{part}"
            raw_value = params.get(param)
            if raw_value in (None, ""):
                continue
            try:
                value = int(raw_value)
            except (TypeError, ValueError) as exc:
                raise AdminValidationError([{"message": f"Invalid {part}.", "param": param}]) from exc
            if value < lower or value > upper:
                raise AdminValidationError([{"message": f"Invalid {part}.", "param": param}])
            values[part] = value
        if "day" in values and "month" not in values:
            raise AdminValidationError(
                [{"message": "A day requires a selected month.", "param": f"{self.date_hierarchy_field}__day"}]
            )
        if "month" in values and "year" not in values:
            raise AdminValidationError(
                [{"message": "A month requires a selected year.", "param": f"{self.date_hierarchy_field}__month"}]
            )
        if {"year", "month", "day"} <= set(values):
            max_day = calendar.monthrange(values["year"], values["month"])[1]
            if values["day"] > max_day:
                raise AdminValidationError(
                    [{"message": "Invalid day.", "param": f"{self.date_hierarchy_field}__day"}]
                )
        return values

    def apply_date_hierarchy(self, queryset, params):
        values = self.get_date_hierarchy_values(params)
        for part, value in values.items():
            queryset = queryset.filter(**{f"{self.date_hierarchy_field}__{part}": value})
        return queryset

    def apply_ordering(self, queryset, params):
        ordering = self.get_ordering(params)
        if ordering:
            return queryset.order_by(*ordering)
        return queryset

    def get_ordering(self, params=None):
        params = params or self.params
        ordering_param = params.get("o")
        if not ordering_param:
            return []

        ordering = []
        invalid_fields = []
        for field in [item.strip() for item in ordering_param.split(",") if item.strip()]:
            descending = field.startswith("-")
            raw_field = field.removeprefix("-")
            display_field = self.ordering_field_from_column(raw_field) if raw_field.isdigit() else raw_field
            if display_field is None:
                invalid_fields.append(field)
                continue
            ordering_field = self.get_ordering_field(display_field)
            if ordering_field is None:
                invalid_fields.append(field)
                continue
            ordering.append(f"-{ordering_field}" if descending else ordering_field)

        if invalid_fields:
            raise AdminValidationError(
                [{"message": f"Invalid ordering field: {', '.join(invalid_fields)}.", "param": "o"}]
            )
        return ordering

    def ordering_field_from_column(self, column):
        index = int(column) - 1
        if index < 0 or index >= len(self.list_display):
            return None
        return self.list_display[index]

    def get_ordering_field(self, field_name):
        if not self.is_sortable_field(field_name):
            return None
        if callable(field_name) and not isinstance(field_name, str):
            attrs = (field_name,)
        else:
            attrs = (getattr(self.model_admin, field_name, None), getattr(self.model, field_name, None))
        for attr in attrs:
            ordering = getattr(attr, "admin_order_field", None)
            if ordering:
                return ordering
        if not isinstance(field_name, str):
            return None
        try:
            field = single_valued_model_field_from_path(self.model, field_name)
        except FieldDoesNotExist:
            return None
        if getattr(field, "many_to_many", False) or getattr(field, "one_to_many", False):
            return None
        return field_name

    def is_sortable_field(self, field_name):
        field_key = field_name_for_display(field_name)
        return any(
            field_name == sortable_field or field_key == field_name_for_display(sortable_field)
            for sortable_field in self.sortable_by
        )

    @property
    def ordering_field_columns(self):
        columns = {}
        for index, field_name in enumerate(self.list_display, start=1):
            if self.get_ordering_field(field_name):
                columns[field_name] = str(index)
        return columns

    def column_sort_query_strings(self, field_name):
        index = self.ordering_field_columns.get(field_name)
        if index is None:
            return {
                "sorted": False,
                "ascending": False,
                "sort_priority": None,
                "ascending_query_string": None,
                "descending_query_string": None,
                "remove_sorting_query_string": None,
            }
        active_ordering = self.active_ordering_field_columns()
        other_tokens = [
            self.ordering_token(active_index, direction)
            for active_index, direction in active_ordering.items()
            if active_index != index
        ]
        active_direction = active_ordering.get(index)
        sort_priority = list(active_ordering).index(index) + 1 if active_direction else None
        if other_tokens:
            remove_sorting_query_string = self.get_query_string({"o": ",".join(other_tokens)})
        else:
            remove_sorting_query_string = self.get_query_string(remove=["o"])
        return {
            "sorted": active_direction is not None,
            "ascending": active_direction == "asc",
            "sort_priority": sort_priority,
            "ascending_query_string": self.get_query_string({"o": ",".join([index, *other_tokens])}),
            "descending_query_string": self.get_query_string({"o": ",".join([f"-{index}", *other_tokens])}),
            "remove_sorting_query_string": remove_sorting_query_string,
        }

    def active_ordering_field_columns(self):
        ordering_param = self.params.get("o")
        if not ordering_param:
            return {}

        active = {}
        for token in [item.strip() for item in ordering_param.split(",") if item.strip()]:
            descending = token.startswith("-")
            raw_field = token.removeprefix("-")
            index = self.ordering_column_index(raw_field)
            if index is None:
                continue
            active[index] = "desc" if descending else "asc"
        return active

    def ordering_column_index(self, raw_field):
        if raw_field.isdigit():
            display_field = self.ordering_field_from_column(raw_field)
            if display_field and self.get_ordering_field(display_field):
                return raw_field
            return None
        for index, field_name in enumerate(self.list_display, start=1):
            if field_name_for_display(field_name) == raw_field or self.get_ordering_field(field_name) == raw_field:
                if self.get_ordering_field(field_name):
                    return str(index)
        return None

    def ordering_token(self, index, direction):
        return f"-{index}" if direction == "desc" else str(index)

    def get_per_page(self):
        value = self.params.get("pp") or self.model_admin.list_per_page
        try:
            per_page = int(value)
        except (TypeError, ValueError):
            raise AdminValidationError([{"message": "Invalid page size.", "param": "pp"}])
        if per_page < 1:
            raise AdminValidationError([{"message": "Invalid page size.", "param": "pp"}])
        return per_page

    def can_show_all(self):
        wants_all = self.params.get("all") in {"1", "true", "True"}
        return wants_all and self.result_count <= self.model_admin.list_max_show_all

    def should_show_facets(self):
        show_facets = getattr(self.model_admin, "show_facets", ShowFacets.ALLOW)
        if show_facets is ShowFacets.ALWAYS:
            return True
        if show_facets is ShowFacets.NEVER:
            return False
        return self.params.get("_facets") in {"1", "true", "True"}

    def get_page_number(self):
        value = self.params.get("p") or self.params.get("page") or 1
        if value == "last":
            return self.paginator.num_pages
        try:
            page_number = int(value)
        except (TypeError, ValueError):
            raise Http404(f"Invalid page ({value}).")
        if page_number < 1:
            raise Http404(f"Invalid page ({value}).")
        return page_number

    def get_page(self):
        try:
            return self.paginator.page(self.page_num)
        except InvalidPage as exc:
            raise Http404(f"Invalid page ({self.page_num}): {exc}")

    def get_page_range(self):
        if not self.pagination_required:
            return []
        return list(self.paginator.get_elided_page_range(self.page_num))

    def page_query_string(self, page_number):
        if page_number <= 1:
            return self.get_query_string(remove=PAGE_PARAMS | {"all"})
        return self.get_query_string({"p": page_number}, remove={"all"})

    def pagination_query_strings(self):
        if not self.pagination_required:
            return {
                "first_page_query_string": None,
                "previous_page_query_string": None,
                "next_page_query_string": None,
                "last_page_query_string": None,
            }
        return {
            "first_page_query_string": self.page_query_string(1) if self.page.has_previous() else None,
            "previous_page_query_string": (
                self.page_query_string(self.page.previous_page_number()) if self.page.has_previous() else None
            ),
            "next_page_query_string": (
                self.page_query_string(self.page.next_page_number()) if self.page.has_next() else None
            ),
            "last_page_query_string": (
                self.page_query_string(self.paginator.num_pages) if self.page.has_next() else None
            ),
        }

    def get_query_string(self, new_params=None, remove=None):
        new_params = new_params or {}
        remove = PAGE_PARAMS | set(remove or [])
        query = self.params.copy()
        for parameter in remove:
            for key in list(query):
                if self.should_remove_query_param(key, parameter):
                    query.pop(key, None)
        for key, value in new_params.items():
            if value is None:
                query.pop(key, None)
            else:
                query[key] = value
        encoded = query.urlencode(safe=",")
        return f"?{encoded}" if encoded else "?"

    def should_remove_query_param(self, key, parameter):
        if key == parameter:
            return True
        return parameter.endswith("__") and key.startswith(parameter)

    def params_from_query_string(self, query_string):
        query = QueryDict(query_string[1:] if query_string.startswith("?") else query_string, mutable=True)
        for parameter in ("p", "page", "all", "pp", "o"):
            query.pop(parameter, None)
        return query

    def count_for_query_string(self, query_string):
        params = self.params_from_query_string(query_string)
        filter_specs = self.get_filters(params)
        return self.get_queryset(params, filter_specs, apply_ordering=False).count()

    def date_queryset(self):
        return self.get_queryset(self.params, self.filter_specs, apply_date_hierarchy=False, apply_ordering=False)

    def date_hierarchy_description(self):
        if not self.date_hierarchy_field:
            return None

        field = self.date_hierarchy_model_field
        values = self.get_date_hierarchy_values(self.params)
        year_param, month_param, day_param = self.date_hierarchy_param_names
        queryset = self.date_queryset()
        if "year" in values:
            queryset = queryset.filter(**{year_param: values["year"]})
        if "month" in values:
            queryset = queryset.filter(**{month_param: values["month"]})

        if "year" not in values:
            level = "year"
        elif "month" not in values:
            level = "month"
        else:
            level = "day"

        choices = []
        for date_value in self.date_values(queryset, field, level):
            choice = self.date_hierarchy_choice(date_value, level, values)
            if self.show_facets:
                choice["count"] = self.count_for_query_string(choice["query_string"])
            choices.append(choice)

        return {
            "field": self.date_hierarchy_field,
            "title": str(field.verbose_name),
            "field_type": (
                field.get_internal_type() if hasattr(field, "get_internal_type") else field.__class__.__name__
            ),
            "timezone": timezone.get_current_timezone_name() if isinstance(field, models.DateTimeField) else None,
            "level": level,
            "params": values,
            "clear_query_string": self.date_hierarchy_clear_query_string(),
            "back_query_string": self.date_hierarchy_back_query_string(values),
            "choices": choices,
        }

    def date_hierarchy_clear_query_string(self):
        return self.get_query_string({}, remove=self.date_hierarchy_param_names)

    def date_hierarchy_back_query_string(self, values):
        year_param, month_param, day_param = self.date_hierarchy_param_names
        if "day" in values:
            return self.get_query_string({}, remove=[day_param])
        if "month" in values:
            return self.get_query_string({}, remove=[month_param, day_param])
        if "year" in values:
            return self.get_query_string({}, remove=[year_param, month_param, day_param])
        return None

    def date_values(self, queryset, field, level):
        if isinstance(field, models.DateTimeField):
            return queryset.datetimes(
                self.date_hierarchy_field,
                level,
                order="ASC",
                tzinfo=timezone.get_current_timezone(),
            )
        return queryset.dates(self.date_hierarchy_field, level, order="ASC")

    def date_hierarchy_choice(self, date_value, level, current_values):
        year_param, month_param, day_param = self.date_hierarchy_param_names
        if level == "year":
            params = {year_param: date_value.year}
            remove = [month_param, day_param]
            display = str(date_value.year)
            selected = current_values.get("year") == date_value.year
            value = date_value.year
        elif level == "month":
            params = {year_param: date_value.year, month_param: date_value.month}
            remove = [day_param]
            display = date_value.strftime("%B %Y")
            selected = current_values.get("month") == date_value.month
            value = date_value.month
        else:
            params = {year_param: date_value.year, month_param: date_value.month, day_param: date_value.day}
            remove = []
            display = date_value.strftime("%Y-%m-%d")
            selected = current_values.get("day") == date_value.day
            value = date_value.day

        return {
            "selected": selected,
            "query_string": self.get_query_string(params, remove=remove),
            "display": display,
            "level": level,
            "value": value,
        }

    def filter_descriptions(self):
        return [filter_spec.as_dict(self) for filter_spec in self.filter_specs if filter_spec.has_output()]
