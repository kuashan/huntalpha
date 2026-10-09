import json
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from .python_indicators import (
    PythonIndicatorExecutionError,
    PythonIndicatorRuntimeUnavailable,
    PythonIndicatorTimeout,
    get_python_indicator,
    list_python_indicators,
    run_python_indicator,
    resolve_python_indicator_executable,
)
from .chan_runner import epoch_to_chan_time


class PythonIndicatorRegistryTests(SimpleTestCase):
    def test_registry_contains_only_controlled_builtin_chanlun(self):
        definitions = list_python_indicators()

        self.assertEqual([definition.code for definition in definitions], ["CHANLUN"])
        self.assertEqual(get_python_indicator("chanlun").name, "缠论结构")
        self.assertIsNone(get_python_indicator("USER_SUPPLIED_PYTHON"))

    @override_settings(HUNTALPHA_INDICATOR_PYTHON="python")
    def test_executable_resolution_accepts_platform_command_without_windows_path(self):
        with mock.patch("core.python_indicators.shutil.which", return_value="/usr/bin/python"):
            self.assertEqual(resolve_python_indicator_executable(), "/usr/bin/python")

    @override_settings(HUNTALPHA_INDICATOR_PYTHON="")
    def test_executable_resolution_falls_back_to_current_interpreter(self):
        with mock.patch.dict("os.environ", {"HUNTALPHA_INDICATOR_PYTHON": ""}, clear=False):
            self.assertEqual(resolve_python_indicator_executable(), sys.executable)

    def test_unknown_indicator_is_rejected_before_subprocess(self):
        with self.assertRaises(PythonIndicatorExecutionError) as context:
            run_python_indicator("USER_SUPPLIED_PYTHON", [], "日线")

        self.assertEqual(context.exception.code, "python_indicator_not_registered")

    def test_epoch_conversion_is_utc_and_preserves_original_epoch(self):
        chan_time = epoch_to_chan_time(1_700_000_000)

        self.assertEqual((chan_time.year, chan_time.month, chan_time.day), (2023, 11, 14))
        self.assertEqual(chan_time.ts, 1_700_000_000)


class PythonIndicatorExecutionTests(SimpleTestCase):
    def setUp(self):
        self.bars = [{
            "time": 1_700_000_000,
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10.5,
            "volume": 100,
            "amount": 1_050,
        }]

    def test_successful_result_uses_unified_drawing_shape_without_source(self):
        result = {"lines": [], "sticks": [], "markers": [], "engine": "chan.py", "source": "private-runner-field"}
        completed = SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")
        with mock.patch("core.python_indicators.resolve_python_indicator_executable", return_value=sys.executable), \
             mock.patch("core.python_indicators.python_indicator_dependencies_available", return_value=True), \
             mock.patch("core.python_indicators.subprocess.run", return_value=completed) as run:
            actual = run_python_indicator("CHANLUN", self.bars, "日线")

        self.assertEqual(actual["lines"], result["lines"])
        self.assertEqual(actual["sticks"], result["sticks"])
        self.assertEqual(actual["markers"], result["markers"])
        self.assertEqual(actual["engine"], result["engine"])
        self.assertEqual(actual["fixedTexts"], [])
        self.assertNotIn("source", actual)
        payload = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(payload["bars"], self.bars)
        self.assertEqual(payload["period"], "日线")
        self.assertNotIn("source", payload)

    def test_missing_dependencies_is_structured_and_does_not_run_indicator(self):
        with mock.patch("core.python_indicators.resolve_python_indicator_executable", return_value=sys.executable), \
             mock.patch("core.python_indicators.python_indicator_dependencies_available", return_value=False), \
             mock.patch("core.python_indicators.subprocess.run") as run:
            with self.assertRaises(PythonIndicatorRuntimeUnavailable) as context:
                run_python_indicator("CHANLUN", self.bars, "日线")

        self.assertEqual(context.exception.code, "chanlun_runtime_unavailable")
        run.assert_not_called()

    def test_timeout_is_structured(self):
        with mock.patch("core.python_indicators.resolve_python_indicator_executable", return_value=sys.executable), \
             mock.patch("core.python_indicators.python_indicator_dependencies_available", return_value=True), \
             mock.patch("core.python_indicators.subprocess.run", side_effect=subprocess.TimeoutExpired("python", 12)):
            with self.assertRaises(PythonIndicatorTimeout) as context:
                run_python_indicator("CHANLUN", self.bars, "日线")

        self.assertEqual(context.exception.code, "chanlun_calculation_timeout")

    @override_settings(HUNTALPHA_INDICATOR_PYTHON="missing-python-runtime")
    def test_invalid_configured_runtime_keeps_chanlun_error_code(self):
        with mock.patch("core.python_indicators.shutil.which", return_value=None):
            with self.assertRaises(PythonIndicatorRuntimeUnavailable) as context:
                run_python_indicator("CHANLUN", self.bars, "日线")

        self.assertEqual(context.exception.code, "chanlun_runtime_unavailable")

    def test_invalid_or_oversized_output_is_structured(self):
        oversized = SimpleNamespace(returncode=0, stdout="x" * (4 * 1024 * 1024 + 1), stderr="")
        with mock.patch("core.python_indicators.resolve_python_indicator_executable", return_value=sys.executable), \
             mock.patch("core.python_indicators.python_indicator_dependencies_available", return_value=True), \
             mock.patch("core.python_indicators.subprocess.run", return_value=oversized):
            with self.assertRaises(PythonIndicatorExecutionError) as context:
                run_python_indicator("CHANLUN", self.bars, "日线")

        self.assertEqual(context.exception.code, "python_indicator_output_too_large")

    def test_real_builtin_chanlun_runner_returns_the_unified_contract(self):
        bars = []
        for index in range(120):
            close = 20 + index * 0.05 + ((index % 9) - 4) * 0.1
            open_price = close + (0.12 if index % 2 else -0.08)
            bars.append({
                "time": 1_700_000_000 + index * 86_400,
                "open": open_price,
                "high": max(open_price, close) + 0.35,
                "low": min(open_price, close) - 0.35,
                "close": close,
                "volume": 100_000 + index,
                "amount": (100_000 + index) * close,
            })

        result = run_python_indicator("CHANLUN", bars, "日线")

        self.assertIsInstance(result["lines"], list)
        self.assertIsInstance(result["sticks"], list)
        self.assertIsInstance(result["markers"], list)
        self.assertEqual(result["engine"], "chan.py")
