from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy

from django_ninja_admin.utils.json_values import jsonish_value


class ObjectWithPk:
    pk = 7


class StringableObject:
    def __str__(self):
        return "stringified"


def test_jsonish_value_normalizes_common_metadata_values():
    assert jsonish_value(gettext_lazy("Lazy label")) == "Lazy label"
    assert jsonish_value(Decimal("1.25")) == "1.25"
    assert jsonish_value(lambda: "not serialized") is None
    assert jsonish_value(ObjectWithPk()) == 7
    assert jsonish_value(StringableObject()) == "stringified"
    assert jsonish_value({"answer": Decimal("2.50"), 3: [ObjectWithPk()]}) == {
        "answer": "2.50",
        "3": [7],
    }


def test_jsonish_value_serializes_q_objects():
    query = models.Q(name=Decimal("1.25")) | ~models.Q(active=True)

    assert jsonish_value(query) == {
        "connector": "OR",
        "negated": False,
        "children": [
            {"lookup": "name", "value": "1.25"},
            {
                "connector": "AND",
                "negated": True,
                "children": [{"lookup": "active", "value": True}],
            },
        ],
    }
