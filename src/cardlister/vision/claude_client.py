"""Identify a card from its photos using Claude vision + structured output."""

from __future__ import annotations

import base64
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import anthropic

from cardlister.domain.schemas import Identification
from cardlister.vision.prompts import SYSTEM_PROMPT, USER_PROMPT

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class VisionError(RuntimeError):
    """Raised when a card can't be identified from its images."""


class CardIdentifier(Protocol):
    """Anything that can turn a card's photos into an :class:`Identification`."""

    def identify(self, image_paths: Sequence[Path]) -> Identification: ...


class AnthropicCardIdentifier:
    """Identifies cards with the Anthropic API (default model: Claude Haiku 4.5)."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        max_images: int = 4,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._client = client or anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_images = max_images

    def identify(self, image_paths: Sequence[Path]) -> Identification:
        content: list[dict[str, Any]] = []
        for path in list(image_paths)[: self._max_images]:
            media_type = _MEDIA_TYPES.get(path.suffix.lower())
            if media_type is None:
                continue
            data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": data},
                }
            )
        if not content:
            raise VisionError("no usable images to identify")
        content.append({"type": "text", "text": USER_PROMPT})

        message = self._client.messages.parse(
            model=self._model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            # Plain dict content blocks; the SDK accepts these at runtime.
            messages=[{"role": "user", "content": content}],  # type: ignore[typeddict-item]
            output_format=Identification,
        )
        if message.parsed_output is None:
            raise VisionError("the model returned no structured identification")
        return message.parsed_output
