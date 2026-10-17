from dataclasses import dataclass
from typing import Any, cast

from django.http import HttpRequest


@dataclass(frozen=True, slots=True)
class AdminRequestContext:
    """Authenticated Django request state supplied to every core operation."""

    request: HttpRequest

    @property
    def user(self):
        return cast(Any, self.request).user


@dataclass(frozen=True, slots=True)
class OperationResult[ResultT]:
    """Transport-neutral successful operation result."""

    data: ResultT
    status_code: int = 200
