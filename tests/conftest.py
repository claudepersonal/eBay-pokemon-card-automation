"""Shared test fixtures: an in-memory database and a sample card folder tree."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from cardlister.db.base import Database
from cardlister.db.repository import CardRepository


@pytest.fixture
def database() -> Iterator[Database]:
    db = Database("sqlite://")  # in-memory, shared connection via StaticPool
    db.create_all()
    yield db


@pytest.fixture
def repo(database: Database) -> Iterator[CardRepository]:
    with database.session() as session:
        yield CardRepository(session)


def _write_card_image(path: Path, *, landscape: bool = False) -> None:
    """Write a small image with a dark 'card' rectangle on a white background."""
    width, height = (240, 160) if landscape else (160, 240)
    array = np.full((height, width, 3), 255, dtype=np.uint8)
    array[20:-20, 20:-20] = 40  # the 'card'
    Image.fromarray(array).save(path)


@pytest.fixture
def cards_root(tmp_path: Path) -> Path:
    """A root with two card folders, each holding a front and back image."""
    root = tmp_path / "cards"
    for name in ("Charizard 4-102", "Pikachu 58-102"):
        folder = root / name
        folder.mkdir(parents=True)
        _write_card_image(folder / "front.jpg")
        _write_card_image(folder / "back.jpg", landscape=True)
    return root
