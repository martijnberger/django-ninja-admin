from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from ninja.constants import NOT_SET

from django_ninja_admin.schemas import JsonObjectResponse
from django_ninja_admin.utils.schema_contracts import iter_contract_schemas, open_object_schema_paths

ALLOWED_ROUTE_METHODS = {"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"}


def normalize_route_methods(methods: Any) -> tuple[str, ...]:
    if isinstance(methods, str):
        route_methods = (methods,)
    else:
        try:
            route_methods = tuple(methods)
        except TypeError as exc:
            raise ImproperlyConfigured("Custom admin route methods must be a string or iterable of strings.") from exc
    if not route_methods:
        raise ImproperlyConfigured("Custom admin routes must declare at least one HTTP method.")

    normalized = []
    seen = set()
    for method in route_methods:
        if not isinstance(method, str) or not method.strip():
            raise ImproperlyConfigured("Custom admin route methods must be non-empty strings.")
        normalized_method = method.strip().upper()
        if normalized_method not in ALLOWED_ROUTE_METHODS:
            raise ImproperlyConfigured(f"Unsupported custom admin route HTTP method: {normalized_method}.")
        if normalized_method in seen:
            continue
        seen.add(normalized_method)
        normalized.append(normalized_method)
    return tuple(normalized)


def validate_route_response_contract(path: str, response: Any) -> None:
    for label, schema_type in iter_contract_schemas(response, "response"):
        if open_object_schema_paths(schema_type):
            raise ImproperlyConfigured(
                f"Custom admin route {label} schema for '{path}' must forbid extra object properties."
            )


@dataclass(frozen=True)
class AdminRoute:
    path: str
    view_func: Callable[..., Any]
    methods: tuple[str, ...] = ("GET",)
    response: Any = JsonObjectResponse
    operation_id: str | None = None
    summary: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    auth: Any = NOT_SET
    throttle: Any = NOT_SET
    include_in_schema: bool = True

    def __post_init__(self) -> None:
        validate_route_response_contract(self.path, self.response)
