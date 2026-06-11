"""Logging setup. Call :func:`configure_logging` once at process start."""

from __future__ import annotations

import logging

_CONFIGURED = False


def configure_logging(level: int | str = logging.INFO) -> None:
    """Configure root logging idempotently with a concise console format."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
