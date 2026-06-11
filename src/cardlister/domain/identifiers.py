"""Deterministic identifier helpers (slugs and eBay SKUs).

Pure functions, kept separate from I/O so they're trivially unit-testable. The SKU is
derived deterministically from the card's folder so re-ingesting the same folder always
yields the same SKU — which is what makes every eBay write idempotent.
"""

from __future__ import annotations

import hashlib
import re

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_EBAY_SKU_MAX = 50
_SKU_PREFIX = "PKM-"
_HASH_LEN = 6


def slugify(value: str) -> str:
    """Lowercase, collapse non-alphanumerics to single dashes, trim dashes."""
    return _SLUG_STRIP.sub("-", value.lower()).strip("-")


def make_sku(folder_name: str) -> str:
    """Build a stable, eBay-safe SKU (``[A-Za-z0-9-]``, <=50 chars) from a folder name.

    A short hash of the (already case-normalized) name is appended so that two folders
    that slugify to the same string still get distinct SKUs, while the same folder is
    always mapped to the same SKU.
    """
    slug = slugify(folder_name)
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:_HASH_LEN]
    budget = _EBAY_SKU_MAX - len(_SKU_PREFIX) - 1 - _HASH_LEN
    truncated = slug[:budget].strip("-") or "card"
    return f"{_SKU_PREFIX}{truncated}-{digest}"
