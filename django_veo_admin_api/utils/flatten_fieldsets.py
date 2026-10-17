from django_veo_admin_api.utils.flatten import flatten


def flatten_fieldsets(fieldsets):
    field_names = []
    for _, opts in fieldsets:
        field_names.extend(flatten(opts.get("fields", [])))
    return field_names
