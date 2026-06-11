"""SKU and slug generation: deterministic, collision-resistant, eBay-safe."""

from __future__ import annotations

import re

from cardlister.domain.identifiers import make_sku, slugify

_EBAY_SKU_RE = re.compile(r"^[A-Za-z0-9-]{1,50}$")


def test_slugify_basic() -> None:
    assert slugify("Charizard 4/102") == "charizard-4-102"
    assert slugify("  Pikachu!! ") == "pikachu"


def test_make_sku_is_deterministic() -> None:
    assert make_sku("Charizard 4-102") == make_sku("Charizard 4-102")


def test_make_sku_is_ebay_safe_and_bounded() -> None:
    sku = make_sku("A really long card name " * 5)
    assert _EBAY_SKU_RE.match(sku)
    assert len(sku) <= 50


def test_make_sku_distinguishes_different_folders() -> None:
    assert make_sku("Charizard 4-102") != make_sku("Pikachu 58-102")


def test_make_sku_handles_empty_slug() -> None:
    sku = make_sku("/// !!! ///")
    assert _EBAY_SKU_RE.match(sku)
