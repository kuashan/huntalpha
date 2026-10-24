Upstream: https://github.com/ZhuLinsen/daily_stock_analysis
Pinned source commit: ec66bf46caf6993f673bd4be59c883754667b686
Original copyright (c) 2026 ZhuLinsen. MIT license is included in LICENSE.

stock_analyzer.py is the upstream src/stock_analyzer.py with ONLY the two import
paths adjusted to reference modules in this vendor package. Its indicator
formulas, status classifications, six-dimensional score, signal gates, thresholds
and labels are unchanged.
decision_scale.py is the unmodified original src/schemas/decision_scale.py.
config.py provides the original default BIAS_THRESHOLD (5.0), without importing
the upstream application's extensive LLM/email/settings system.

Source algorithms are not tied to SiftAlpha's existing chart indicators,
trading strategies, member rules or automatic execution.
