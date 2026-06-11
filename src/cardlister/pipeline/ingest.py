"""Ingest stage: scan a root directory of per-card folders into the database.

Each immediate subfolder that contains at least one image is one card. Photo roles
(front/back/extra) are assigned by filename hints first, then by order — and are always
overridable later in the UI. Re-running ingest on the same root is a no-op for cards
whose photos haven't changed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from cardlister.db.models import Card, Photo
from cardlister.db.repository import CardRepository
from cardlister.domain.identifiers import make_sku
from cardlister.domain.states import CardState, PhotoRole
from cardlister.logging import get_logger

log = get_logger(__name__)

VALID_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".tga"})

_FRONT_HINTS = ("front", "obverse")
_BACK_HINTS = ("back", "reverse")


@dataclass(frozen=True)
class DiscoveredPhoto:
    path: Path
    role: PhotoRole
    order_index: int
    content_hash: str


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_files(folder: Path) -> list[Path]:
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VALID_IMAGE_EXTS),
        key=lambda p: p.name.lower(),
    )


def _hint_role(stem: str) -> PhotoRole | None:
    lowered = stem.lower()
    if any(h in lowered for h in _FRONT_HINTS):
        return PhotoRole.FRONT
    if any(h in lowered for h in _BACK_HINTS):
        return PhotoRole.BACK
    return None


def discover_photos(folder: Path) -> list[DiscoveredPhoto]:
    """Assign a role and order to each image in a card folder.

    Filename hints win; otherwise the first un-hinted image becomes FRONT, the next
    BACK, and the rest EXTRA — but a role is never assigned twice.
    """
    files = _image_files(folder)
    hinted: dict[int, PhotoRole] = {i: r for i, p in enumerate(files) if (r := _hint_role(p.stem))}
    used = set(hinted.values())

    discovered: list[DiscoveredPhoto] = []
    for index, path in enumerate(files):
        role = hinted.get(index)
        if role is None:
            if PhotoRole.FRONT not in used:
                role = PhotoRole.FRONT
            elif PhotoRole.BACK not in used:
                role = PhotoRole.BACK
            else:
                role = PhotoRole.EXTRA
            if role is not PhotoRole.EXTRA:
                used.add(role)
        discovered.append(
            DiscoveredPhoto(
                path=path,
                role=role,
                order_index=index,
                content_hash=_hash_file(path),
            )
        )
    return discovered


def _photos_match(existing: Sequence[Photo], discovered: Sequence[DiscoveredPhoto]) -> bool:
    if len(existing) != len(discovered):
        return False
    by_path = {p.original_path: p for p in existing}
    return all(
        (found := by_path.get(str(d.path))) is not None and found.content_hash == d.content_hash
        for d in discovered
    )


def ingest_folder(repo: CardRepository, folder: Path) -> Card | None:
    """Create or update one card from a folder. Returns ``None`` if it has no images."""
    folder = folder.resolve()
    discovered = discover_photos(folder)
    if not discovered:
        log.debug("Skipping %s: no images", folder)
        return None

    source_folder = str(folder)
    card = repo.get_by_folder(source_folder)
    if card is None:
        card = repo.add(
            Card(
                sku=make_sku(folder.name),
                source_folder=source_folder,
                state=CardState.INGESTED,
                display_name=folder.name,
            )
        )
    elif _photos_match(card.photos, discovered):
        log.debug("Card %s unchanged", card.sku)
        return card

    repo.replace_photos(
        card,
        [
            Photo(
                role=d.role,
                original_path=str(d.path),
                order_index=d.order_index,
                content_hash=d.content_hash,
            )
            for d in discovered
        ],
    )
    log.info("Ingested %s (%d photos) from %s", card.sku, len(discovered), folder.name)
    return card


def _card_folders(root: Path) -> Iterable[Path]:
    return sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.lower())


def ingest_root(repo: CardRepository, root: Path) -> list[Card]:
    """Ingest every per-card subfolder under ``root``."""
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Cards root is not a directory: {root}")
    cards = [card for folder in _card_folders(root) if (card := ingest_folder(repo, folder))]
    log.info("Ingest complete: %d card(s) under %s", len(cards), root)
    return cards
