"""Ingest: folder scanning, role assignment, idempotency, and re-scan behavior."""

from __future__ import annotations

from pathlib import Path

from cardlister.db.repository import CardRepository
from cardlister.domain.states import CardState, PhotoRole
from cardlister.pipeline.ingest import discover_photos, ingest_folder, ingest_root


def test_discover_photos_assigns_roles_by_filename_hint(tmp_path: Path) -> None:
    folder = tmp_path / "card"
    folder.mkdir()
    (folder / "back.jpg").write_bytes(b"b")
    (folder / "front.jpg").write_bytes(b"f")
    (folder / "closeup.jpg").write_bytes(b"c")

    roles = {Path(d.path).name: d.role for d in discover_photos(folder)}
    assert roles == {
        "front.jpg": PhotoRole.FRONT,
        "back.jpg": PhotoRole.BACK,
        "closeup.jpg": PhotoRole.EXTRA,
    }


def test_discover_photos_falls_back_to_order(tmp_path: Path) -> None:
    folder = tmp_path / "card"
    folder.mkdir()
    for name in ("1.jpg", "2.jpg", "3.jpg"):
        (folder / name).write_bytes(name.encode())

    roles = [d.role for d in discover_photos(folder)]
    assert roles == [PhotoRole.FRONT, PhotoRole.BACK, PhotoRole.EXTRA]


def test_ingest_root_creates_cards(repo: CardRepository, cards_root: Path) -> None:
    cards = ingest_root(repo, cards_root)
    assert len(cards) == 2
    for card in cards:
        assert card.state is CardState.INGESTED
        assert len(card.photos) == 2
        assert {p.role for p in card.photos} == {PhotoRole.FRONT, PhotoRole.BACK}


def test_ingest_is_idempotent(repo: CardRepository, cards_root: Path) -> None:
    first = ingest_root(repo, cards_root)
    second = ingest_root(repo, cards_root)
    assert {c.sku for c in first} == {c.sku for c in second}
    assert len(repo.list_cards()) == 2  # no duplicates created


def test_reingest_picks_up_new_photo(repo: CardRepository, cards_root: Path) -> None:
    ingest_root(repo, cards_root)
    folder = next(cards_root.iterdir())
    (folder / "extra.jpg").write_bytes(b"new-photo-bytes")

    card = ingest_folder(repo, folder)
    assert card is not None
    assert len(card.photos) == 3


def test_folder_without_images_is_skipped(repo: CardRepository, tmp_path: Path) -> None:
    empty = tmp_path / "not-a-card"
    empty.mkdir()
    (empty / "notes.txt").write_text("no images here")
    assert ingest_folder(repo, empty) is None
