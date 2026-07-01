from django_ninja_admin.utils.flatten import flatten


def flatten_fieldsets(fieldsets):
    field_names = []
    for _, opts in fieldsets:
        field_names.extend(flatten(opts.get("fields", [])))
    return field_names

