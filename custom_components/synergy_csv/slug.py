"""Slug helper shared by the parser and the statistics adapter."""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, collapse runs of non-alphanumerics to '_', trim '_'."""
    return _NON_ALNUM.sub("_", text.lower()).strip("_")
