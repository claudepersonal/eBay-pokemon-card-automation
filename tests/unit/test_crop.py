"""Crop: non-destructive, idempotent, and graceful on un-croppable images."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from cardlister.db.repository import CardRepository
from cardlister.pipeline.crop import CropError, crop_card_photos, crop_image
from cardlister.pipeline.ingest import ingest_root


def _make_card_photo(path: Path, *, landscape: bool = False) -> None:
    width, height = (200, 120) if landscape else (120, 200)
    array = np.full((height, width, 3), 255, dtype=np.uint8)
    array[15:-15, 15:-15] = 30
    Image.fromarray(array).save(path)


def test_crop_image_trims_to_card_and_portrait_orients(tmp_path: Path) -> None:
    src = tmp_path / "src.jpg"
    dst = tmp_path / "out.jpg"
    _make_card_photo(src, landscape=True)

    crop_image(src, dst, margin=5)

    with Image.open(dst) as result:
        w, h = result.size
    assert dst.exists()
    assert h >= w  # landscape input auto-rotated to portrait


def test_crop_image_does_not_touch_original(tmp_path: Path) -> None:
    src = tmp_path / "src.jpg"
    dst = tmp_path / "out.jpg"
    _make_card_photo(src)
    before = src.read_bytes()

    crop_image(src, dst, margin=5)

    assert src.read_bytes() == before


def test_crop_image_raises_on_blank(tmp_path: Path) -> None:
    src = tmp_path / "blank.jpg"
    Image.fromarray(np.full((100, 100, 3), 255, dtype=np.uint8)).save(src)
    with pytest.raises(CropError):
        crop_image(src, tmp_path / "out.jpg")


def test_crop_card_photos_sets_derived_path_and_is_idempotent(
    repo: CardRepository, cards_root: Path, tmp_path: Path
) -> None:
    cards = ingest_root(repo, cards_root)
    derived = tmp_path / "derived"

    count = crop_card_photos(cards[0], derived)
    assert count == 2
    assert all(p.derived_path is not None for p in cards[0].photos)

    # Second run reuses existing derived files.
    assert crop_card_photos(cards[0], derived) == 2
