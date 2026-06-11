"""Boilerplate listing text shared across listings."""

from __future__ import annotations

DISCLAIMER = (
    "Ungraded and sold as-is — please inspect the photos closely for condition. "
    "Ships securely in a penny sleeve and top loader with cardboard backing. "
    "Returns are not accepted, so please ask any questions before purchasing."
)


def default_description(title: str) -> str:
    """A simple HTML description: the card title plus the standard disclaimer."""
    return f"<p>{title}</p><p>{DISCLAIMER}</p>"
