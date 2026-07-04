# Private Django API Audit

Audit date: 2026-07-04.

This package delegates to public Django admin utilities where possible. The
private or semi-private Django APIs below remain in use because they preserve
Django-admin semantics while this package exposes JSON instead of HTML. Run
`just private-api-audit` before release candidates and after every Django
feature-version upgrade.

## Private API Inventory

| Private API | Locations | Reason | Upgrade Check |
| --- | --- | --- | --- |
| `_get_foreign_key` | `django_ninja_admin/admins/inline.py`, `django_ninja_admin/checks.py`, `django_ninja_admin/sites.py` | Match Django inline parent foreign-key resolution for formsets and system checks. | Compare with `django.forms.models._get_foreign_key` when upgrading Django. |
| `request.parse_file_upload` | `django_ninja_admin/sites.py` | Parse multipart JSON+file requests through Django's request upload parser. | Verify Django request upload parsing still accepts the same `META`/request arguments. |
| `queryset.query.order_by` | `django_ninja_admin/changelist.py` | Detect explicit queryset ordering before applying deterministic changelist fallback ordering. | Confirm `Query.order_by` remains the correct low-level source for explicit ordering. |
| `_get_FIELD_display` | `django_ninja_admin/utils/lookup.py` | Reuse Django's choice-label conversion while serializing list/detail display values. | Compare with `Model._get_FIELD_display` and public `get_FOO_display()` behavior. |
| `media._css/_js` | `django_ninja_admin/utils/forms.py` | Expose form/widget media assets as structured JSON for frontend clients. | Verify `django.forms.Media` still stores CSS/JS assets on `_css` and `_js`. |
| `widget._parse_date_fmt` | `django_ninja_admin/utils/forms.py` | Expose `SelectDateWidget` ordering metadata without rendering HTML. | Check `SelectDateWidget` date-format parsing on each Django feature release. |

## Delegated Django Admin Helpers

The package intentionally delegates some HTML-free admin behavior to public
Django admin helpers:

- `django.contrib.admin.utils.NestedObjects` in
  `django_ninja_admin/utils/deletion.py` for protected-delete collection.
- `django.contrib.admin.widgets.url_params_from_lookup_dict` in
  `django_ninja_admin/admins/base.py` for relation lookup query metadata.

These helpers are not private API, but they should still be reviewed during
Django feature-version upgrades because they influence admin semantics.
