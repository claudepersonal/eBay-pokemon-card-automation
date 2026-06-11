"""Card lifecycle states and the legal transitions between them.

The state machine is enforced centrally (see :mod:`cardlister.db.repository`) so no
pipeline stage can silently corrupt a card's state. ``LISTING`` is the lock that
prevents listing the same card twice; ``LISTED`` is terminal success.
"""

from __future__ import annotations

import enum


class CardState(enum.StrEnum):
    INGESTED = "ingested"
    IDENTIFIED = "identified"
    PRICED = "priced"
    REVIEWED = "reviewed"
    LISTING = "listing"
    LISTED = "listed"
    FAILED = "failed"


class PhotoRole(enum.StrEnum):
    FRONT = "front"
    BACK = "back"
    EXTRA = "extra"


class CompKind(enum.StrEnum):
    ACTIVE = "active"
    SOLD = "sold"


class TokenType(enum.StrEnum):
    USER = "user"
    APP = "app"


# from-state -> set of states it may transition to.
# Re-running an earlier stage (re-identify, re-price, re-confirm) is allowed so the
# pipeline is resumable and the user can redo a card before it is listed.
ALLOWED_TRANSITIONS: dict[CardState, frozenset[CardState]] = {
    CardState.INGESTED: frozenset({CardState.IDENTIFIED}),
    CardState.IDENTIFIED: frozenset({CardState.IDENTIFIED, CardState.PRICED}),
    CardState.PRICED: frozenset(
        {CardState.IDENTIFIED, CardState.PRICED, CardState.REVIEWED}
    ),
    CardState.REVIEWED: frozenset(
        {CardState.IDENTIFIED, CardState.PRICED, CardState.REVIEWED, CardState.LISTING}
    ),
    CardState.LISTING: frozenset({CardState.LISTED, CardState.FAILED}),
    CardState.FAILED: frozenset({CardState.LISTING}),
    CardState.LISTED: frozenset(),
}


class IllegalTransitionError(RuntimeError):
    """Raised when a card is asked to move between states that aren't connected."""

    def __init__(self, from_state: CardState, to_state: CardState) -> None:
        super().__init__(
            f"Illegal card state transition: {from_state.value} -> {to_state.value}"
        )
        self.from_state = from_state
        self.to_state = to_state


def can_transition(from_state: CardState, to_state: CardState) -> bool:
    return to_state in ALLOWED_TRANSITIONS.get(from_state, frozenset())


def assert_transition(from_state: CardState, to_state: CardState) -> None:
    if not can_transition(from_state, to_state):
        raise IllegalTransitionError(from_state, to_state)
