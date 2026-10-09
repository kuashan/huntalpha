"""Controlled server-side execution for repository-owned Python indicators.

This module is intentionally a registry, not a plugin loader.  A Python
indicator can run only when it is explicitly registered in this file and its
runner is part of the repository.  User-provided Python source is never
accepted as input.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from django.conf import settings


MAX_OUTPUT_BYTES = 4 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 12
DEFAULT_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024


class PythonIndicatorExecutionError(RuntimeError):
    def __init__(self, message, code="python_indicator_execution_failed", status=422):
        super().__init__(message)
        self.code = code
        self.status = status


class PythonIndicatorRuntimeUnavailable(PythonIndicatorExecutionError):
    def __init__(self, message="Python 指标运行环境不可用", code="python_indicator_runtime_unavailable"):
        super().__init__(message, code=code, status=503)


class PythonIndicatorTimeout(PythonIndicatorExecutionError):
    def __init__(self, message="Python 指标计算耗时过长", code="python_indicator_calculation_timeout"):
        super().__init__(message, code=code, status=422)


@dataclass(frozen=True)
class PythonIndicatorDefinition:
    code: str
    identifier: str
    name: str
    placement: str
    version: int
    runner: str
    dependency_probe: str
    unavailable_code: str
    calculation_failed_code: str
    invalid_response_code: str
    timeout_code: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_bars: int = 1000

    def metadata(self):
        return {
            "id": self.identifier,
            "name": self.name,
            "code": self.code,
            "placement": self.placement,
            "version": self.version,
            "enabled": True,
            "updated_at": "",
            "visitor_available": False,
            "common": False,
            "engine": "python",
        }


_PYTHON_INDICATORS = {
    "CHANLUN": PythonIndicatorDefinition(
        code="CHANLUN",
        identifier="builtin-chanlun",
        name="缠论结构",
        placement="main",
        version=1,
        runner="core/chan_runner.py",
        dependency_probe="chanlun",
        unavailable_code="chanlun_runtime_unavailable",
        calculation_failed_code="chanlun_calculation_failed",
        invalid_response_code="chanlun_invalid_response",
        timeout_code="chanlun_calculation_timeout",
    ),
}


def list_python_indicators():
    return tuple(_PYTHON_INDICATORS.values())


def get_python_indicator(code):
    if not isinstance(code, str):
        return None
    return _PYTHON_INDICATORS.get(code.upper())


def _configured_executable():
    configured = str(
        getattr(settings, "HUNTALPHA_INDICATOR_PYTHON", "")
        or os.environ.get("HUNTALPHA_INDICATOR_PYTHON", "")
        or getattr(settings, "HUNTALPHA_CHANLUN_PYTHON", "")
        or os.environ.get("HUNTALPHA_CHANLUN_PYTHON", "")
    ).strip()
    return configured


def resolve_python_indicator_executable():
    configured = _configured_executable()
    if not configured:
        return sys.executable

    configured_path = Path(configured).expanduser()
    if configured_path.is_file():
        return str(configured_path)
    resolved = shutil.which(configured)
    if resolved:
        return resolved
    raise PythonIndicatorRuntimeUnavailable("Python 指标运行环境未配置", code="python_indicator_runtime_unavailable")


def _dependency_probe(definition):
    vendor_root = str(Path(settings.BASE_DIR) / "vendor" / "chan.py-main")
    if definition.dependency_probe == "chanlun":
        return (
            "import sys; sys.path.insert(0, %r); "
            "from Chan import CChan; "
            "from ChanConfig import CChanConfig; "
            "from Common.CEnum import DATA_FIELD, KL_TYPE; "
            "from Common.CTime import CTime; "
            "from KLine.KLine_Unit import CKLine_Unit"
        ) % vendor_root
    raise PythonIndicatorRuntimeUnavailable("Python 指标依赖未注册", code="python_indicator_not_registered")


def python_indicator_dependencies_available(executable, definition=None):
    definition = definition or get_python_indicator("CHANLUN")
    try:
        subprocess.run(
            [executable, "-c", _dependency_probe(definition)],
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=5,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    return True


def _posix_resource_limiter(timeout_seconds):
    if os.name == "nt":
        return None
    try:
        import resource
    except ImportError:
        return None

    cpu_seconds = max(1, int(timeout_seconds) + 1)

    def limit_resources():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        if hasattr(resource, "RLIMIT_AS"):
            resource.setrlimit(resource.RLIMIT_AS, (DEFAULT_MEMORY_LIMIT_BYTES, DEFAULT_MEMORY_LIMIT_BYTES))

    return limit_resources


def _validate_result(definition, completed):
    stdout = completed.stdout or ""
    if len(stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise PythonIndicatorExecutionError(
            "Python 指标返回结果过大",
            code="python_indicator_output_too_large",
            status=422,
        )
    try:
        result = json.loads(stdout)
    except (TypeError, ValueError) as exc:
        raise PythonIndicatorExecutionError(
            "Python 指标返回了无效结果",
            code=definition.invalid_response_code,
            status=422,
        ) from exc
    if not isinstance(result, dict) or any(not isinstance(result.get(key), list) for key in ("lines", "sticks", "markers")):
        raise PythonIndicatorExecutionError(
            "Python 指标返回了无效绘图结果",
            code=definition.invalid_response_code,
            status=422,
        )
    # The server-side view consumes this stable shape; source text is not a
    # permitted result field even if a future runner accidentally emits it.
    result.pop("source", None)
    result.setdefault("fixedTexts", [])
    result.setdefault("engine", "python")
    return result


def run_python_indicator(code, bars, period):
    definition = code if isinstance(code, PythonIndicatorDefinition) else get_python_indicator(code)
    if definition is None:
        raise PythonIndicatorExecutionError(
            "Python 指标未注册",
            code="python_indicator_not_registered",
            status=404,
        )
    if not isinstance(bars, list) or len(bars) > definition.max_bars:
        raise PythonIndicatorExecutionError(
            "Python 指标输入行情超出安全范围",
            code="python_indicator_input_too_large",
            status=422,
        )

    try:
        executable = resolve_python_indicator_executable()
    except PythonIndicatorRuntimeUnavailable as exc:
        if exc.code == "python_indicator_runtime_unavailable":
            raise PythonIndicatorRuntimeUnavailable(str(exc), code=definition.unavailable_code) from exc
        raise
    if not python_indicator_dependencies_available(executable, definition):
        raise PythonIndicatorRuntimeUnavailable(
            "缠论计算环境缺少必要依赖",
            code=definition.unavailable_code,
        )

    runner = Path(settings.BASE_DIR) / definition.runner
    if not runner.is_file():
        raise PythonIndicatorRuntimeUnavailable(
            "Python 指标运行文件不可用",
            code=definition.unavailable_code,
        )
    timeout_seconds = max(1, int(getattr(settings, "HUNTALPHA_PYTHON_INDICATOR_TIMEOUT_SECONDS", definition.timeout_seconds)))
    payload = {"bars": bars, "period": period}
    command = [executable, str(runner)]
    kwargs = {
        "input": json.dumps(payload, ensure_ascii=False),
        "text": True,
        "encoding": "utf-8",
        "capture_output": True,
        "timeout": timeout_seconds,
        "check": True,
        "env": {**os.environ, "PYTHONIOENCODING": "utf-8", "TZ": "UTC"},
    }
    limiter = _posix_resource_limiter(timeout_seconds)
    if limiter is not None:
        kwargs["preexec_fn"] = limiter
    try:
        completed = subprocess.run(command, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise PythonIndicatorTimeout("缠论计算耗时过长", code=definition.timeout_code) from exc
    except FileNotFoundError as exc:
        raise PythonIndicatorRuntimeUnavailable("Python 指标运行环境未配置", code=definition.unavailable_code) from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr or ""
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="ignore")
        if definition.code == "CHANLUN" and "CChanException" in detail and "price" in detail:
            raise PythonIndicatorExecutionError(
                "缠论计算失败：行情 OHLC 数据不一致",
                code="chanlun_invalid_market_data",
                status=422,
            ) from exc
        raise PythonIndicatorExecutionError(
            "缠论计算失败",
            code=definition.calculation_failed_code,
            status=422,
        ) from exc
    return _validate_result(definition, completed)
