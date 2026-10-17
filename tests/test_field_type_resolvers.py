from django.db import models

from django_veo_admin_api.core.field_types import ModelFieldTypeResolver, resolve_model_field_type


class FixedResolver:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def resolve(self, field):
        self.calls.append(field)
        return self.result


def test_field_type_resolver_chain_uses_first_match():
    field = models.CharField(max_length=20)
    missing = FixedResolver(None)
    match = FixedResolver(int)
    skipped = FixedResolver(str)

    assert isinstance(match, ModelFieldTypeResolver)
    assert resolve_model_field_type(field, (missing, match, skipped)) is int
    assert missing.calls == [field]
    assert match.calls == [field]
    assert skipped.calls == []


def test_field_type_resolver_chain_can_fall_back():
    assert resolve_model_field_type(models.CharField(max_length=20), ()) is None
