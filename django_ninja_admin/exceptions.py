from django.core.exceptions import SuspiciousOperation

NON_FIELD_ERRORS = "non_field_errors"


def normalize_admin_errors(errors):
    normalized = []
    _flatten_admin_errors(errors, (), normalized)
    return normalized or [{"message": "Validation failed.", "param": NON_FIELD_ERRORS}]


def _flatten_admin_errors(value, prefix, normalized):
    if value in ({}, [], (), None):
        return
    if _is_error_item(value):
        normalized.append(_prefixed_error_item(value, prefix))
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _flatten_admin_errors(child, _child_prefix(prefix, key), normalized)
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            child_prefix = prefix
            if _is_indexed_collection(value) and not _is_error_item(child):
                child_prefix = (*prefix, str(index))
            _flatten_admin_errors(child, child_prefix, normalized)
        return
    normalized.append({"message": str(value), "param": _param_from_prefix(prefix)})


def _is_error_item(value):
    return isinstance(value, dict) and {"message", "param"} <= set(value)


def _prefixed_error_item(error, prefix):
    param = str(error.get("param") or NON_FIELD_ERRORS)
    return {
        "message": error.get("message", ""),
        "param": _param_from_prefix(prefix, param),
    }


def _param_from_prefix(prefix, param=NON_FIELD_ERRORS):
    parts = [str(part) for part in prefix if str(part)]
    if param != NON_FIELD_ERRORS:
        parts.append(str(param))
    if not parts:
        return param
    return ".".join(parts)


def _child_prefix(prefix, key):
    key = str(key)
    if not prefix and key == "form":
        return prefix
    if not prefix and key.isdigit():
        return ("data", key)
    if not prefix and "." in key:
        return ("inlines", key)
    return (*prefix, key)


def _is_indexed_collection(value):
    return any(isinstance(item, (dict, list, tuple)) and not _is_error_item(item) for item in value)


class AdminError(Exception):
    status_code = 400


class AlreadyRegistered(AdminError):
    pass


class NotRegistered(AdminError):
    status_code = 404


class NotRelationField(AdminError):
    pass


class IncorrectLookupParameters(AdminError):
    pass


class FieldIsAForeignKeyColumnName(AdminError):
    pass


class DisallowedModelAdminLookup(SuspiciousOperation):
    pass


class DisallowedModelAdminToField(SuspiciousOperation):
    pass


class MissingSearchFields(AdminError):
    status_code = 409


class ProtectedDelete(AdminError):
    status_code = 409


class AdminValidationError(AdminError):
    status_code = 400

    def __init__(self, errors):
        super().__init__("Validation failed")
        self.errors = normalize_admin_errors(errors)


class AdminPermissionError(AdminError):
    status_code = 403

    def __init__(self, errors):
        super().__init__("Permission denied")
        self.errors = normalize_admin_errors(errors)
