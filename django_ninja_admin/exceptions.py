from django.core.exceptions import SuspiciousOperation


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
        self.errors = errors


class AdminPermissionError(AdminError):
    status_code = 403

    def __init__(self, errors):
        super().__init__("Permission denied")
        self.errors = errors
