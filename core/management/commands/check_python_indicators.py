from django.core.management.base import BaseCommand, CommandError

from core.python_indicators import (
    PythonIndicatorRuntimeUnavailable,
    list_python_indicators,
    python_indicator_dependencies_available,
    resolve_python_indicator_executable,
)


class Command(BaseCommand):
    help = "检查受控 Python 指标的解释器和依赖，不读取数据库或公式源码。"

    def handle(self, *args, **options):
        try:
            executable = resolve_python_indicator_executable()
        except PythonIndicatorRuntimeUnavailable as exc:
            raise CommandError(str(exc)) from exc

        failed = []
        for definition in list_python_indicators():
            available = python_indicator_dependencies_available(executable, definition)
            if available:
                self.stdout.write(f"{definition.code}: ok")
            else:
                failed.append(definition)
                self.stdout.write(self.style.ERROR(f"{definition.code}: unavailable"))
        if failed:
            raise CommandError("一个或多个 Python 指标运行环境不可用")
