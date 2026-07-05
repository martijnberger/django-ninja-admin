from decimal import Decimal

from django.db import models
from django.utils.functional import Promise


def jsonish_value(value):
    if isinstance(value, Promise):
        return str(value)
    if callable(value):
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, models.Q):
        return {
            "connector": value.connector,
            "negated": value.negated,
            "children": [jsonish_q_child(child) for child in value.children],
        }
    if hasattr(value, "pk"):
        return value.pk
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [jsonish_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonish_value(item) for key, item in value.items()}
    return str(value)


def jsonish_q_child(child):
    if isinstance(child, tuple) and len(child) == 2 and isinstance(child[0], str):
        return {"lookup": child[0], "value": jsonish_value(child[1])}
    return jsonish_value(child)
