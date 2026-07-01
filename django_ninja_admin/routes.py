from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ninja.constants import NOT_SET


@dataclass(frozen=True)
class AdminRoute:
    path: str
    view_func: Callable[..., Any]
    methods: tuple[str, ...] = ("GET",)
    response: Any = dict[str, Any]
    operation_id: str | None = None
    summary: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    auth: Any = NOT_SET
    include_in_schema: bool = True
