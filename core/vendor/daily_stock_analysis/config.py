"""Minimal default compatibility for the upstream StockTrendAnalyzer.

The original Config.bias_threshold default is 5.0 percentage points.
No SiftAlpha-specific thresholds or weights are introduced.
"""
from types import SimpleNamespace

_DEFAULT = SimpleNamespace(bias_threshold=5.0)


def get_config():
    return _DEFAULT
