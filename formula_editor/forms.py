import json
from pathlib import Path
import subprocess

from django import forms
from django.conf import settings

from .models import Formula


class FormulaAdminForm(forms.ModelForm):
    """Validate private formula source on the server before it is saved."""

    class Meta:
        model = Formula
        fields = "__all__"

    def clean_source(self):
        source = self.cleaned_data["source"]
        bars = []
        for index in range(320):
            close = 20 + index * 0.03 + ((index % 17) - 8) * 0.04
            open_price = close + (0.12 if index % 2 else -0.1)
            bars.append({
                "time": 1_700_000_000 + index * 86_400,
                "open": open_price,
                "high": max(open_price, close) + 0.35,
                "low": min(open_price, close) - 0.35,
                "close": close,
                "volume": 100_000 + index * 100,
                "amount": (100_000 + index * 100) * close,
            })
        try:
            completed = subprocess.run(
                ["node", str(Path(settings.BASE_DIR) / "core" / "formula_runner.mjs")],
                input=json.dumps({"source": source, "bars": bars, "period": "日线", "symbol": "SH.TEST", "name": "后台校验"}, ensure_ascii=False),
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=8,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise forms.ValidationError(f"公式校验服务不可用：{exc}") from exc
        if completed.returncode:
            detail = (completed.stderr or "未知公式错误").strip()
            raise forms.ValidationError(f"公式校验失败：{detail[:500]}")
        return source
