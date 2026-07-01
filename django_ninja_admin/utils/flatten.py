def flatten(fields):
    for field in fields:
        if isinstance(field, (list, tuple)):
            yield from flatten(field)
        else:
            yield field

