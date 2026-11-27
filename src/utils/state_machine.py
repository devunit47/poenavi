"""Lightweight explicit finite state machine primitive."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum
from typing import Generic, TypeVar

S = TypeVar("S", bound=Enum)


class InvalidStateTransitionError(ValueError):
    """Raised when a state machine attempts a disallowed state transition."""

    def __init__(
        self,
        name: str,
        current: Enum,
        target: Enum,
        *,
        reason: str | None = None,
    ):
        self.machine_name = name
        self.current_state = current
        self.target_state = target
        detail = f" ({reason})" if reason else ""
        super().__init__(
            f"{name}: invalid state transition {current.value!r} -> {target.value!r}{detail}"
        )


class StateMachine(Generic[S]):
    """Validated finite state machine backed by an explicit transition table."""

    def __init__(
        self,
        name: str,
        initial: S,
        transitions: Mapping[S, frozenset[S]],
        *,
        on_transition: Callable[[S, S], None] | None = None,
    ):
        if initial not in transitions:
            raise ValueError(
                f"{name}: initial state {initial!r} is missing from transition table"
            )
        self._name = name
        self._state: S = initial
        self._transitions: dict[S, frozenset[S]] = {
            state: frozenset(targets) for state, targets in transitions.items()
        }
        self._on_transition = on_transition

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> S:
        return self._state

    @property
    def transitions(self) -> Mapping[S, frozenset[S]]:
        return self._transitions

    def is_in(self, *states: S) -> bool:
        return self._state in states

    def can_transition(self, target: S, *, allow_same: bool = False) -> bool:
        if target == self._state and allow_same:
            return True
        return target in self._transitions.get(self._state, frozenset())

    def transition(
        self,
        target: S,
        *,
        allow_same: bool = False,
        reason: str | None = None,
    ) -> S:
        if target == self._state:
            if allow_same or target in self._transitions.get(self._state, frozenset()):
                return self._state
            raise InvalidStateTransitionError(
                self._name, self._state, target, reason=reason
            )
        if target not in self._transitions.get(self._state, frozenset()):
            raise InvalidStateTransitionError(
                self._name, self._state, target, reason=reason
            )
        previous = self._state
        self._state = target
        if self._on_transition is not None:
            self._on_transition(previous, target)
        return self._state

    def require(self, *allowed: S, action: str | None = None) -> S:
        if self._state not in allowed:
            expected = ", ".join(repr(state.value) for state in allowed)
            prefix = f"{self._name} ({action})" if action else self._name
            raise InvalidStateTransitionError(
                prefix,
                self._state,
                self._state,
                reason=f"expected one of [{expected}]",
            )
        return self._state
