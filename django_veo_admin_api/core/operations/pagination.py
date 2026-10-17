from django_veo_admin_api.schemas import Pagination


def pagination_result(paginator, page_obj) -> Pagination:
    has_next = page_obj.has_next()
    return Pagination(
        count=paginator.count,
        num_pages=paginator.num_pages,
        page=page_obj.number,
        per_page=paginator.per_page,
        has_next=has_next,
        has_previous=page_obj.has_previous(),
        more=has_next,
    )


def visibility_filtered_pagination_result(page_obj, visible_items) -> Pagination:
    visible_count = len(visible_items)
    return Pagination(
        count=visible_count,
        num_pages=1 if visible_count else 0,
        page=page_obj.number,
        per_page=page_obj.paginator.per_page,
        has_next=False,
        has_previous=page_obj.has_previous(),
        more=False,
    )
