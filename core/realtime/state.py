from dataclasses import dataclass, replace
from threading import Condition, RLock
from uuid import uuid4

from ..marketdata.calendar import canonical_calendar_time
from .contracts import NormalizedBar, merge_realtime_bar


@dataclass
class RealtimeState:
    key: tuple
    epoch: str
    current_bar: NormalizedBar | None = None
    last_closed_bar: NormalizedBar | None = None
    revision: int = 0
    status: str = "connecting"
    mode: str = "streaming"
    source: str | None = None
    data_status: str = "realtime"
    error: str | None = None

    def to_dict(self):
        if len(self.key) >= 4:
            provider, market, symbol, period = self.key[:4]
        else:
            provider, symbol, period = self.key[:3]
            market = None
        return {
            "epoch": self.epoch,
            "provider": provider,
            "market": market,
            "symbol": symbol,
            "period": period,
            "bar": self.current_bar.to_dict() if self.current_bar else None,
            "last_closed_bar": self.last_closed_bar.to_dict() if self.last_closed_bar else None,
            "revision": self.revision,
            "status": self.status,
            "mode": self.mode,
            "source": self.source,
            "data_status": self.data_status,
            "error": self.error,
        }


@dataclass(frozen=True)
class RealtimeCalculationSnapshot:
    key: tuple
    epoch: str
    revision: int
    current_bar: NormalizedBar | None
    source: str | None
    status: str
    mode: str


class RealtimeStateStore:
    def __init__(self):
        self._states = {}
        self.epoch = uuid4().hex
        self._revision = 0
        self._condition = Condition(RLock())

    def _state(self, key):
        return self._states.setdefault(key, RealtimeState(key=key, epoch=self.epoch))

    def get(self, key):
        with self._condition:
            state = self._states.get(key)
            if state is None:
                return None
            return RealtimeState(**state.__dict__)

    def apply_bar(self, key, bar, status="live", mode="streaming", source=None):
        with self._condition:
            state = self._state(key)
            # Real-time and historical windows must use the same exchange-local bucket.
            normalized_time = canonical_calendar_time(bar.time, bar.market, bar.period)
            if normalized_time != bar.time:
                bar = replace(bar, time=normalized_time)
            # The public polling registry survives an admin source switch: never
            # carry a previous provider's closed/current bar into the new source.
            if state.current_bar is not None and state.current_bar.provider != bar.provider:
                state.current_bar = None
                state.last_closed_bar = None
            result = merge_realtime_bar(state.current_bar, bar)
            if not result.accepted:
                return RealtimeState(**state.__dict__), result
            if result.relation == "appended" and state.current_bar is not None:
                state.last_closed_bar = state.current_bar.__class__(**{
                    **state.current_bar.__dict__, "is_closed": True,
                })
            self._revision += 1
            state.revision = self._revision
            state.current_bar = result.bar.__class__(**{
                **result.bar.__dict__, "revision": state.revision,
            })
            state.status = status
            state.mode = mode
            state.source = source or result.bar.provider
            state.data_status = getattr(result.bar, "data_status", "realtime") or "realtime"
            state.error = None
            self._condition.notify_all()
            return RealtimeState(**state.__dict__), result

    def set_status(self, key, status, mode="streaming", source=None, error=None):
        with self._condition:
            state = self._state(key)
            changed = (state.status, state.mode, state.source, state.error) != (status, mode, source, error)
            if changed:
                self._revision += 1
                state.revision = self._revision
            state.status = status
            state.mode = mode
            state.source = source or state.source
            state.error = error
            self._condition.notify_all()
            return RealtimeState(**state.__dict__)

    def revision_for(self, key):
        with self._condition:
            return self._states.get(key, RealtimeState(key=key, epoch=self.epoch)).revision

    def capture(self, key):
        """Capture one immutable market state for a calculation run."""
        with self._condition:
            state = self._states.get(key)
            if state is None:
                return RealtimeCalculationSnapshot(
                    key=key, epoch=self.epoch, revision=0, current_bar=None, source=None,
                    status="unavailable", mode="streaming",
                )
            return RealtimeCalculationSnapshot(
                key=key,
                epoch=state.epoch,
                revision=state.revision,
                current_bar=state.current_bar,
                source=state.source,
                status=state.status,
                mode=state.mode,
            )

    def reset(self):
        with self._condition:
            self._states.clear()
            self._revision = 0
