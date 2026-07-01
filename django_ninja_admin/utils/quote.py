from urllib.parse import quote as urlquote
from urllib.parse import unquote as urlunquote


def quote(s):
    return urlquote(str(s), safe="")


def unquote(s):
    return urlunquote(str(s))

