"""Crop stage: trim a card photo to the card, non-destructively.

This assumes the card is shot against a mostly solid background. It finds the bounding
box of the high-gradient region (the card edges) and crops to it with a margin. The
**original is never modified** — the crop is written to a derived path keyed by the
photo's content hash. Cropping is best-effort: on failure the original is used as-is.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from cardlister.db.models import Card
from cardlister.logging import get_logger

log = get_logger(__name__)


class CropError(RuntimeError):
    """Raised when an image can't be cropped (e.g. no detectable card edges)."""


def _bounding_box(gray: np.ndarray, sensitivity: float) -> tuple[int, int, int, int]:
    gy, gx = np.gradient(gray)
    magnitude = np.hypot(gx, gy)
    peak = float(magnitude.max())
    if peak == 0.0:
        raise CropError("image has no gradient (blank image)")
    mask = magnitude > (sensitivity * peak)
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        raise CropError("no card edges detected; try a lower sensitivity")
    return int(rows[0]), int(rows[-1]), int(cols[0]), int(cols[-1])


def crop_image(
    src: Path,
    dst: Path,
    *,
    margin: int = 40,
    sensitivity: float = 0.12,
    auto_rotate: bool = True,
) -> None:
    """Crop ``src`` to its card and write the result to ``dst``.

    Raises :class:`CropError` if no card region can be found.
    """
    with Image.open(src) as image:
        rgb = image.convert("RGB")
        array = np.asarray(rgb, dtype=np.float64)

    gray = array.mean(axis=2)
    y_min, y_max, x_min, x_max = _bounding_box(gray, sensitivity)

    height, width = gray.shape
    top = max(y_min - margin, 0)
    bottom = min(y_max + margin, height)
    left = max(x_min - margin, 0)
    right = min(x_max + margin, width)
    if bottom - top < 2 or right - left < 2:
        raise CropError("cropped region is degenerate")

    cropped = array[top:bottom, left:right].astype(np.uint8)
    if auto_rotate and cropped.shape[1] > cropped.shape[0]:
        cropped = np.rot90(cropped)

    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(cropped).save(dst, format="JPEG", quality=92)


def crop_card_photos(
    card: Card,
    derived_dir: Path,
    *,
    force: bool = False,
    margin: int = 40,
    sensitivity: float = 0.12,
) -> int:
    """Crop each of a card's photos into ``derived_dir`` and record the derived path.

    Idempotent: skips a photo whose derived file already exists (unless ``force``).
    Returns the number of photos successfully cropped. Failures are logged and leave
    ``derived_path`` unset so the original is used downstream.
    """
    cropped = 0
    for photo in card.photos:
        dst = derived_dir / f"{photo.content_hash}.jpg"
        if dst.exists() and not force:
            photo.derived_path = str(dst)
            cropped += 1
            continue
        try:
            crop_image(Path(photo.original_path), dst, margin=margin, sensitivity=sensitivity)
        except (CropError, OSError) as exc:
            log.warning("Crop failed for %s (%s); using original", photo.original_path, exc)
            continue
        photo.derived_path = str(dst)
        cropped += 1
    return cropped
