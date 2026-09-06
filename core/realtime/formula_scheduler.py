from dataclasses import dataclass
from threading import RLock


@dataclass
class FlightState:
    active_revision: int | None = None
    pending_revision: int | None = None


class FormulaFlightCoordinator:
    """Latest-revision-wins coordination primitive for formula callers."""

    def __init__(self):
        self._states = {}
        self._lock = RLock()

    def begin(self, key, revision):
        revision = int(revision)
        with self._lock:
            state = self._states.setdefault(key, FlightState())
            if state.active_revision is not None:
                state.pending_revision = max(state.pending_revision or revision, revision)
                return False
            state.active_revision = revision
            return True

    def finish(self, key, revision):
        with self._lock:
            state = self._states.get(key)
            if state is None or state.active_revision != int(revision):
                return None
            next_revision = state.pending_revision
            state.active_revision = next_revision
            state.pending_revision = None
            if next_revision is None:
                self._states.pop(key, None)
            return next_revision

    def is_stale(self, key, revision, latest_revision):
        with self._lock:
            state = self._states.get(key)
            active = state.active_revision if state else None
            pending = state.pending_revision if state else None
        return int(revision) < int(latest_revision) or revision != active and revision != pending

    def state(self, key):
        with self._lock:
            current = self._states.get(key)
            return FlightState(**current.__dict__) if current else FlightState()
