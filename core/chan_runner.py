"""Server-only adapter for the vendored chan.py structural engine (MIT)."""
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]


def apply_child_resource_limits():
    """Apply limits from the child environment, never from a parent preexec hook."""
    if os.name == "nt":
        return
    try:
        import resource
        cpu_seconds = max(1, int(os.environ.get("HUNTALPHA_INDICATOR_CPU_LIMIT_SECONDS", "0")))
        memory_bytes = max(0, int(os.environ.get("HUNTALPHA_INDICATOR_MEMORY_LIMIT_BYTES", "0")))
        if cpu_seconds:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        if memory_bytes and hasattr(resource, "RLIMIT_AS"):
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    except (ImportError, OSError, ValueError):
        # Timeout and bounded parent-side output validation remain active if
        # the host does not expose POSIX resource limits.
        return


if __name__ == "__main__":
    apply_child_resource_limits()

sys.path.insert(0, str(ROOT / "vendor" / "chan.py-main"))

from Chan import CChan  # noqa: E402
from ChanConfig import CChanConfig  # noqa: E402
from Common.CEnum import DATA_FIELD, KL_TYPE  # noqa: E402
from Common.CTime import CTime  # noqa: E402
from KLine.KLine_Unit import CKLine_Unit  # noqa: E402


def line(name, color, size, start, end, first, last, dotted=False, width=2):
    values = [None] * size
    if 0 <= start < size:
        values[start] = first
    if 0 <= end < size:
        values[end] = last
    return {"name": name, "color": color, "dotted": dotted, "width": width, "values": values}


PERIOD_TYPES = {
    "1分": KL_TYPE.K_1M,
    "5分": KL_TYPE.K_5M,
    "15分": KL_TYPE.K_15M,
    "30分": KL_TYPE.K_30M,
    "60分": KL_TYPE.K_60M,
    # Chan.py's public KL enum ends at 60 minutes.  These are still genuine
    # OpenD 120/240-minute bars; because this adapter only supplies one level
    # to the structural engine, the 60-minute enum is a neutral container tag.
    "2小时": KL_TYPE.K_60M,
    "4小时": KL_TYPE.K_60M,
    "日线": KL_TYPE.K_DAY,
    "周线": KL_TYPE.K_WEEK,
    "月线": KL_TYPE.K_MON,
}


def normalized_ohlc(bar):
    open_price = float(bar["open"])
    high_price = float(bar["high"])
    low_price = float(bar["low"])
    close_price = float(bar["close"])
    values = (open_price, high_price, low_price, close_price)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("行情 OHLC 数据包含无效数值")
    # Some public adjusted-bar responses can violate the OHLC envelope by a
    # few ticks. Chan.py rejects such records, so only repair the envelope
    # used by the structural engine; the chart still displays provider data.
    return open_price, max(high_price, open_price, close_price), min(low_price, open_price, close_price), close_price


def epoch_to_chan_time(timestamp, timezone_name="UTC"):
    """Build a deterministic Chan.py time value from a provider epoch.

    The calendar fields use the instrument's exchange timezone, never the
    host's local timezone.  Chan.py stores a timestamp on ``CTime`` using a
    naive datetime, so assign the original epoch after constructing the local
    market fields.  The vendored algorithm remains unchanged; only the
    adapter's input normalization is deterministic across Windows and Linux.
    """
    epoch = int(timestamp)
    date = datetime.fromtimestamp(epoch, tz=ZoneInfo(str(timezone_name or "UTC")))
    chan_time = CTime(date.year, date.month, date.day, date.hour, date.minute, auto=False)
    chan_time.ts = epoch
    return chan_time


def run(raw_bars, period="日线", market_timezone="UTC"):
    kl_type = PERIOD_TYPES.get(period, KL_TYPE.K_DAY)
    units = []
    for bar in raw_bars:
        open_price, high_price, low_price, close_price = normalized_ohlc(bar)
        units.append(CKLine_Unit({
            DATA_FIELD.FIELD_TIME: epoch_to_chan_time(bar["time"], market_timezone),
            DATA_FIELD.FIELD_OPEN: open_price,
            DATA_FIELD.FIELD_HIGH: high_price,
            DATA_FIELD.FIELD_LOW: low_price,
            DATA_FIELD.FIELD_CLOSE: close_price,
            DATA_FIELD.FIELD_VOLUME: float(bar.get("volume", 0)),
            DATA_FIELD.FIELD_TURNOVER: float(bar.get("amount", 0)),
        }))
    config = CChanConfig({"trigger_step": True, "print_warning": False, "print_err_time": False})
    chan = CChan("LOCAL", lv_list=[kl_type], config=config)
    chan.trigger_load({kl_type: units})
    result = chan[0]
    size = len(raw_bars)
    lines = []
    for item in result.bi_list:
        begin, end = item.get_begin_klu(), item.get_end_klu()
        lines.append(line("缠论笔", "#f5bf4d" if item.is_sure else "#94a3b8", size, begin.idx, end.idx, item.get_begin_val(), item.get_end_val(), not item.is_sure, 2))
    for item in result.seg_list:
        begin, end = item.get_begin_klu(), item.get_end_klu()
        lines.append(line("缠论线段", "#22d3ee" if item.is_sure else "#60a5fa", size, begin.idx, end.idx, item.get_begin_val(), item.get_end_val(), not item.is_sure, 3))
    sticks = []
    for item in result.zs_list:
        points = [
            {"barIndex": index, "from": item.low, "to": item.high, "width": 9, "empty": True}
            for index in range(item.begin.idx, item.end.idx + 1)
        ]
        sticks.append({"color": "#64748b", "points": points})
    markers = []
    for point in result.bs_point_lst.getSortedBspList():
        markers.append({
            "color": "#ef5350" if point.is_buy else "#20bd92",
            "text": f"{'买' if point.is_buy else '卖'}{point.type2str()}",
            "barIndex": point.klu.idx,
            "value": point.klu.low if point.is_buy else point.klu.high,
        })
    return {"lines": lines, "sticks": sticks, "markers": markers, "engine": "chan.py"}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    if isinstance(request, dict):
        result = run(request["bars"], request.get("period", "日线"), request.get("market_timezone", "UTC"))
    else:
        result = run(request)
    print(json.dumps(result, ensure_ascii=False))
