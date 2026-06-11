"""The card state machine: legal transitions allowed, illegal ones rejected."""

from __future__ import annotations

import pytest

from cardlister.domain.states import (
    CardState,
    IllegalTransitionError,
    assert_transition,
    can_transition,
)


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (CardState.INGESTED, CardState.IDENTIFIED),
        (CardState.IDENTIFIED, CardState.PRICED),
        (CardState.PRICED, CardState.REVIEWED),
        (CardState.REVIEWED, CardState.LISTING),
        (CardState.LISTING, CardState.LISTED),
        (CardState.LISTING, CardState.FAILED),
        (CardState.FAILED, CardState.LISTING),  # retry
        (CardState.PRICED, CardState.IDENTIFIED),  # re-identify
        (CardState.REVIEWED, CardState.PRICED),  # re-price after confirm
    ],
)
def test_legal_transitions(from_state: CardState, to_state: CardState) -> None:
    assert can_transition(from_state, to_state)
    assert_transition(from_state, to_state)  # does not raise


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (CardState.INGESTED, CardState.LISTING),  # can't skip the gate
        (CardState.INGESTED, CardState.PRICED),  # can't skip identify
        (CardState.LISTED, CardState.LISTING),  # terminal
        (CardState.PRICED, CardState.LISTING),  # must be reviewed first
    ],
)
def test_illegal_transitions(from_state: CardState, to_state: CardState) -> None:
    assert not can_transition(from_state, to_state)
    with pytest.raises(IllegalTransitionError):
        assert_transition(from_state, to_state)


def test_listing_is_the_only_path_to_listed() -> None:
    assert not can_transition(CardState.REVIEWED, CardState.LISTED)
    assert can_transition(CardState.LISTING, CardState.LISTED)
