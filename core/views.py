from datetime import datetime, timedelta
import json as json_module
import math
import os
import re
import socket
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from futu import AuType, KLType, OpenQuoteContext, RET_OK
from formula_editor.models import Formula

PERIODS = {"1分": KLType.K_1M, "5分": KLType.K_5M, "15分": KLType.K_15M, "30分": KLType.K_30M, "60分": KLType.K_60M, "2小时": KLType.K_120M, "4小时": KLType.K_240M, "日线": KLType.K_DAY, "周线": KLType.K_WEEK, "月线": KLType.K_MON}
KLINE_PAGE_SIZE = 1000
# Calendar windows chosen to contain at least one page of trading bars for
# every supported period without making a single OpenD request unbounded.
KLINE_LOOKBACK_DAYS = {"1分": 14, "5分": 45, "15分": 90, "30分": 180, "60分": 365, "2小时": 730, "4小时": 1460, "日线": 1825, "周线": 7300, "月线": 14600}

def json(data, status=200):
    result = JsonResponse(data, status=status)
    result["Access-Control-Allow-Origin"] = "http://127.0.0.1:5173"
    result["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    result["Access-Control-Allow-Headers"] = "Content-Type"
    result["Access-Control-Allow-Credentials"] = "true"
    return result


def admin_review_mode_enabled():
    return bool(getattr(settings, "DEV_ADMIN_REVIEW_MODE", False))


def review_allowed(user):
    return bool(user.is_staff or user.is_superuser)


def user_payload(user):
    return {
        "email": user.email,
        "name": user.get_full_name() or user.first_name or user.email.split("@", 1)[0],
        "review_allowed": review_allowed(user),
    }


COMMON_INDICATORS = [
    {"id": "builtin-ma", "name": "MA 均线", "code": "MA", "placement": "main"},
    {"id": "builtin-boll", "name": "BOLL 布林线", "code": "BOLL", "placement": "main"},
    {"id": "builtin-vol", "name": "VOL 成交量", "code": "VOL", "placement": "sub"},
    {"id": "builtin-macd", "name": "MACD", "code": "MACD", "placement": "sub"},
    {"id": "builtin-kdj", "name": "KDJ", "code": "KDJ", "placement": "sub"},
    {"id": "builtin-rsi", "name": "RSI", "code": "RSI", "placement": "sub"},
]


def is_visitor(request):
    return bool(request.session.get("quantscope_visitor"))


def api_terminal_required(view):
    """Require a normal member, or a staff reviewer when review mode is on."""
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            if admin_review_mode_enabled() and is_visitor(request):
                return json({"error": "当前为管理员审查模式，仅允许 Django staff/superuser 进入", "authenticated": False, "admin_review_mode": True}, 403)
            if not is_visitor(request):
                return json({"error": "请先登录后访问量化终端", "authenticated": False}, 401)
        if admin_review_mode_enabled() and not review_allowed(request.user):
            return json({"error": "当前为管理员审查模式，仅允许 Django staff/superuser 进入", "authenticated": False, "admin_review_mode": True}, 403)
        return view(request, *args, **kwargs)
    return wrapped


def api_member_required(view):
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return json({"error": "AI 分析仅向已登录账户开放"}, 403)
        return view(request, *args, **kwargs)
    return wrapped


def dsa_code(code):
    upper = code.upper()
    if upper.startswith(("SH.", "SZ.")):
        return upper.split(".", 1)[1]
    if upper.startswith("HK."):
        return "hk" + upper.split(".", 1)[1]
    if upper.startswith("US."):
        return upper.split(".", 1)[1]
    return None


def dsa_request(path, payload=None):
    body = json_module.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(f"{settings.DSA_API_BASE_URL}{path}", data=body, headers={"Content-Type": "application/json"}, method="POST" if body else "GET")
    try:
        with urlopen(request, timeout=15) as response:
            return json_module.loads(response.read().decode("utf-8")), None
    except HTTPError as exc:
        return None, f"分析服务返回 {exc.code}：{exc.read().decode('utf-8', 'replace')[:240]}"
    except (URLError, TimeoutError) as exc:
        return None, f"分析服务不可用：{exc}"


@csrf_exempt
@require_POST
@api_member_required
def ai_analysis(request):
    payload = auth_body(request) or {}
    code = dsa_code(str(payload.get("code", "")))
    market = str(payload.get("market", ""))
    if not code:
        return json({"error": "当前标的暂不支持 AI 分析；加密资产分析将在数据源接入后开放"}, 422)
    region = "cn" if market == "沪深 A 股" else "hk" if market == "港股" else "us"
    stock_task, error = dsa_request("/api/v1/analysis/analyze", {"stock_code": code, "stock_name": payload.get("name"), "original_query": code, "selection_source": "manual", "report_type": "detailed", "async_mode": True, "notify": False})
    if error:
        return json({"error": error}, 502)
    market_task, market_error = dsa_request("/api/v1/analysis/market-review", {"send_notification": False, "region": region})
    return json({"stock_task": stock_task, "market_task": market_task, "market_error": market_error, "credits": {"cost": 1, "enforced": settings.AI_CREDITS_ENFORCED}})


@require_GET
@api_member_required
def ai_analysis_status(request, task_id):
    data, error = dsa_request(f"/api/v1/analysis/status/{task_id}")
    return json(data, 200) if not error else json({"error": error}, 502)


@require_GET
def auth_session(request):
    review_mode = admin_review_mode_enabled()
    if request.user.is_authenticated:
        if review_mode and not review_allowed(request.user):
            return json({"error": "当前为管理员审查模式，仅允许 Django staff/superuser 进入", "authenticated": False, "admin_review_mode": True}, 403)
        return json({"authenticated": True, "visitor": False, "admin_review_mode": review_mode, "user": user_payload(request.user)})
    if is_visitor(request):
        if review_mode:
            return json({"error": "当前为管理员审查模式，仅允许 Django staff/superuser 进入", "authenticated": False, "admin_review_mode": True}, 403)
        return json({"authenticated": True, "visitor": True, "user": {"email": "", "name": "访客模式"}})
    return json({"authenticated": False, "admin_review_mode": review_mode}, 401)


def auth_body(request):
    try:
        return json_module.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json_module.JSONDecodeError):
        return None


@csrf_exempt
@require_POST
def auth_register(request):
    if admin_review_mode_enabled():
        return json({"error": "当前为管理员审查模式，注册入口已关闭", "admin_review_mode": True}, 403)
    payload = auth_body(request)
    if not isinstance(payload, dict):
        return json({"error": "请求格式无效"}, 400)
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    name = str(payload.get("name", "")).strip()
    if not email or "@" not in email:
        return json({"error": "请输入有效的邮箱地址"}, 400)
    if len(email) > 150:
        return json({"error": "邮箱地址过长"}, 400)
    User = get_user_model()
    if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
        return json({"error": "该邮箱已经注册，请直接登录"}, 409)
    candidate = User(username=email, email=email, first_name=name[:150])
    try:
        validate_password(password, candidate)
    except ValidationError as exc:
        return json({"error": " ".join(exc.messages)}, 400)
    candidate.set_password(password)
    candidate.save()
    request.session.pop("quantscope_visitor", None)
    login(request, candidate)
    return json({"authenticated": True, "user": user_payload(candidate)}, 201)


@csrf_exempt
@require_POST
def auth_login(request):
    payload = auth_body(request)
    if not isinstance(payload, dict):
        return json({"error": "请求格式无效"}, 400)
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    User = get_user_model()
    user = User.objects.filter(email__iexact=email).first() or User.objects.filter(username__iexact=email).first()
    if not user or not user.is_active or not user.check_password(password):
        return json({"error": "邮箱或密码不正确"}, 401)
    if admin_review_mode_enabled() and not review_allowed(user):
        return json({"error": "当前为管理员审查模式，仅允许 Django staff/superuser 登录", "admin_review_mode": True}, 403)
    request.session.pop("quantscope_visitor", None)
    login(request, user)
    return json({"authenticated": True, "admin_review_mode": admin_review_mode_enabled(), "user": user_payload(user)})


@csrf_exempt
@require_POST
def auth_logout(request):
    logout(request)
    request.session.pop("quantscope_visitor", None)
    return json({"authenticated": False})


@csrf_exempt
@require_POST
def auth_guest(request):
    if admin_review_mode_enabled():
        return json({"error": "当前为管理员审查模式，访客入口已关闭", "admin_review_mode": True}, 403)
    request.session["quantscope_visitor"] = True
    return json({"authenticated": True, "visitor": True, "user": {"email": "", "name": "访客模式"}})

def context():
    try:
        with socket.create_connection(("127.0.0.1", 11111), timeout=1):
            pass
    except OSError as exc:
        raise RuntimeError("无法连接富途 OpenD（127.0.0.1:11111）") from exc
    return OpenQuoteContext(host="127.0.0.1", port=11111, ai_type=1)


def numeric_value(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def bar_rows(frame):
    return [{
        "time": int(datetime.strptime(row.time_key, "%Y-%m-%d %H:%M:%S").timestamp()),
        "open": float(row.open), "high": float(row.high), "low": float(row.low),
        "close": float(row.close), "volume": float(row.volume),
        "amount": float(getattr(row, "turnover", 0) or 0),
        "turnover_rate": float(getattr(row, "turnover_rate", 0) or 0),
        "last_close": float(getattr(row, "last_close", 0) or 0),
    } for row in frame.itertuples()]


def request_history_rows(client, code, period, before=None):
    """Load one bounded, explicitly forward-adjusted OpenD history window.

    This is the one runtime market-data path for both chart pages and formula
    calculation.  Imported Tongdaxin files are deliberately *not* a fallback:
    they remain offline regression fixtures only, so the browser cannot show
    one price series while the formula calculates another.
    """
    end = datetime.fromtimestamp(before) if before else datetime.now()
    start = end - timedelta(days=KLINE_LOOKBACK_DAYS.get(period, 1825))
    ret, frame, _ = client.request_history_kline(
        code.upper(), start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"),
        ktype=PERIODS.get(period, KLType.K_DAY), autype=AuType.QFQ, max_count=None,
    )
    if ret != RET_OK or frame.empty:
        return None, str(frame)
    rows = bar_rows(frame)
    if before:
        rows = [bar for bar in rows if bar["time"] < before]
    return rows, None


def request_page(client, code, period, count, before=None):
    """Load one chart page from the shared runtime OpenD data stream."""
    rows, error = request_history_rows(client, code, period, before)
    if error:
        return None, False, error
    rows = rows[-count:]
    # A non-empty page can have older provider history.  The client will make
    # at most one extra request to determine the true beginning of history.
    return rows, bool(rows), None


@require_GET
@api_terminal_required
def quote(request, code):
    client = None
    try:
        client = context()
        ret, frame = client.get_market_snapshot([code.upper()])
        if ret != RET_OK or frame.empty:
            return json({"error": f"富途 OpenD 未返回 {code.upper()} 的真实报价", "source": "futu-opend"}, 502)
        row = frame.iloc[0]
        price = numeric_value(row.get("last_price"))
        if price is None:
            return json({"error": f"富途 OpenD 未返回 {code.upper()} 的有效最新价", "source": "futu-opend"}, 502)
        previous = numeric_value(row.get("prev_close_price"))
        return json({
            "code": row["code"], "name": row["name"], "price": price,
            "change": round((price - previous) / previous * 100, 3) if previous else None,
            "open": numeric_value(row.get("open_price")),
            "high": numeric_value(row.get("high_price")),
            "low": numeric_value(row.get("low_price")),
            "updated_at": row.get("update_time"), "source": "futu-opend",
        })
    except Exception as exc:
        return json({"error": f"富途 OpenD 不可用：{exc}", "source": "futu-opend"}, 503)
    finally:
        if client is not None:
            client.close()

@require_GET
@api_terminal_required
def kline(request, code):
    period = request.GET.get("period", "日线")
    try:
        count = min(max(int(request.GET.get("count", KLINE_PAGE_SIZE)), 50), KLINE_PAGE_SIZE)
    except ValueError:
        return json({"error": "count 必须是整数"}, 400)
    try:
        before = int(request.GET["before"]) if request.GET.get("before") else None
    except ValueError:
        return json({"error": "before 必须是 Unix 时间戳"}, 400)
    client = None
    try:
        client = context()
        if period == "分时":
            if before:
                return json({"code": code.upper(), "period": period, "bars": [], "source": "futu-opend", "has_more": False})
            ret, frame = client.get_rt_data(code.upper())
            if ret != RET_OK or frame.empty:
                return json({"error": f"富途 OpenD 未返回 {code.upper()} 的真实分时数据", "source": "futu-opend"}, 502)
            bars = [{"time": int(datetime.strptime(f"{datetime.now().date()} {row.time}", "%Y-%m-%d %H:%M:%S").timestamp()), "open": float(row.cur_price), "high": float(row.cur_price), "low": float(row.cur_price), "close": float(row.cur_price), "volume": float(row.volume)} for row in frame.itertuples() if not row.is_blank]
            return json({"code": code.upper(), "period": period, "bars": bars, "source": "futu-opend", "adjustment": "实时分时", "has_more": False})
        bars, has_more, error = request_page(client, code, period, count, before)
        if error: return json({"error": error}, 502)
        return json({"code": code.upper(), "period": period, "bars": bars, "source": "futu-opend", "adjustment": "前复权", "has_more": has_more})
    except Exception as exc:
        return json({"error": f"富途 OpenD 不可用：{exc}", "source": "futu-opend"}, 503)
    finally:
        if client is not None:
            client.close()


def live_float_shares(client, code):
    """Return OpenD's current circulating share count when it is available."""
    ret, frame = client.get_market_snapshot([code.upper()])
    if ret != RET_OK or frame.empty:
        return None
    value = frame.iloc[0].get("outstanding_shares")
    try:
        return float(value) if value and float(value) > 0 else None
    except (TypeError, ValueError):
        return None


def history_bars(code, period):
    """Load the complete bounded OpenD window used for one formula run."""
    client = context()
    try:
        if period == "分时":
            return None, None, "自定义公式暂不支持分时；请选择 K 线周期"
        bars, error = request_history_rows(client, code, period)
        return bars, live_float_shares(client, code) if not error else None, error
    finally:
        client.close()


def indicator_data(item, include_source=False):
    data = {"id": item.id, "name": item.name, "code": item.code, "placement": item.placement, "version": item.version, "enabled": item.enabled, "updated_at": item.updated_at.isoformat()}
    if include_source:
        data["source"] = item.source
    return data


@require_GET
@api_terminal_required
def indicators(request):
    # Formula editing is deliberately confined to Django Admin, where staff
    # authentication, audit trail and the private source field are available.
    common = [{**item, "version": 1, "enabled": True, "updated_at": "", "visitor_available": True, "common": True} for item in COMMON_INDICATORS]
    installed = [{**indicator_data(item), "visitor_available": False, "common": False} for item in Formula.objects.filter(enabled=True)]
    chanlun = {"id": "builtin-chanlun", "name": "缠论结构", "code": "CHANLUN", "placement": "main", "version": 1, "enabled": True, "updated_at": "", "visitor_available": False, "common": False}
    return json({"visitor": is_visitor(request), "items": common + [chanlun] + installed})


@require_GET
@api_terminal_required
def indicator_render(request, code, symbol):
    """Return drawing data, never the proprietary formula source itself."""
    if code.upper() in {item["code"] for item in COMMON_INDICATORS}:
        return json({"error": "常用指标由终端本地标准实现绘制"}, 400)
    if is_visitor(request):
        return json({"error": "访客模式不能启用已安装的私有指标"}, 403)
    builtin_chanlun = code.upper() == "CHANLUN"
    if not builtin_chanlun:
        try:
            item = Formula.objects.get(code=code.upper(), enabled=True)
        except Formula.DoesNotExist:
            return json({"error": "未找到已启用的指标"}, 404)
    period = request.GET.get("period", "日线")
    count = min(max(int(request.GET.get("count", 500)), 100), 1000)
    # Future functions such as BACKSET and formulas using BARSCOUNT(C)=1
    # need the beginning of the same real OpenD history shown to the chart.
    # Calculate the complete bounded window, then return its visible tail.
    calculation_bars, float_shares, error = history_bars(symbol, period)
    if error:
        return json({"error": error}, 400 if period == "分时" else 502)
    visible_start = max(0, len(calculation_bars) - count)
    bars = calculation_bars[visible_start:]
    try:
        if builtin_chanlun:
            completed = subprocess.run(
                [str(settings.BASE_DIR / ".chanlun-venv" / "Scripts" / "python.exe"), str(settings.BASE_DIR / "core" / "chan_runner.py")],
                input=json_module.dumps({"bars": calculation_bars, "period": period}, ensure_ascii=False),
                text=True, encoding="utf-8", capture_output=True, timeout=12, check=True,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        else:
            completed = subprocess.run(
                ["node", str(settings.BASE_DIR / "core" / "formula_runner.mjs")],
                input=json_module.dumps({"source": item.source, "bars": calculation_bars, "period": period, "symbol": symbol.upper(), "name": item.name, "chip": {"floatShares": float_shares}}, ensure_ascii=False),
                text=True, encoding="utf-8", capture_output=True, timeout=8, check=True,
            )
        formula = json_module.loads(completed.stdout)
    except subprocess.CalledProcessError as exc:
        # Formula source is private. Only a function name is safe and useful
        # to return to the browser; parser excerpts and source fragments stay
        # in the admin/server boundary.
        detail = (exc.stderr or "").strip()
        unsupported = re.search(r"暂不支持通达信函数：[A-Za-z][A-Za-z0-9_]*", detail)
        message = unsupported.group(0) if unsupported else "公式语法或参数不受支持，请在后台检查公式"
        return json({"error": f"指标计算失败：{message}"}, 422)
    except subprocess.TimeoutExpired:
        return json({"error": "指标计算超时，请检查公式是否包含过大的递归或回看范围"}, 422)
    except json_module.JSONDecodeError:
        return json({"error": "指标计算服务返回了无效结果"}, 422)
    def points(values):
        if isinstance(values, (int, float)):
            return [{"time": bar["time"], "value": float(values)} for bar in bars]
        if not isinstance(values, list):
            return []
        return [
            {"time": bar["time"], "value": float(value)}
            for bar, value in zip(bars, values[visible_start:])
            if isinstance(value, (int, float))
        ]

    def event_point(row):
        index = row.get("barIndex")
        if not isinstance(index, int) or index < visible_start or index >= len(calculation_bars):
            return None
        value = row.get("value")
        if not isinstance(value, (int, float)):
            return None
        return {"time": calculation_bars[index]["time"], "value": float(value)}

    def stick_point(row):
        index = row.get("barIndex")
        start, end = row.get("from"), row.get("to")
        if not isinstance(index, int) or index < visible_start or index >= len(calculation_bars):
            return None
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            return None
        return {
            "time": calculation_bars[index]["time"], "from": float(start), "to": float(end),
            # In Tongdaxin STICKLINE, width 0 is significant: it is the
            # one-pixel line/wick form.  Do not coerce it to 1 here, or a
            # formula's wick becomes a visible narrow rectangle.
            "width": float(row.get("width") if row.get("width") is not None else 1),
            "empty": float(row.get("empty") if isinstance(row.get("empty"), (int, float)) else 0),
        }

    drawing = {
        "lines": [
            {
                "name": row["name"], "color": row["color"],
                "style": row.get("style", "dotted" if row.get("dotted") else "solid")
                if row.get("style", "solid") in {"solid", "dotted", "circle-dot", "point-dot", "cross-dot"}
                else "solid",
                "width": max(1, min(9, int(row.get("width") or 1))), "data": points(row["values"]),
            }
            for row in formula["lines"]
        ],
        "sticks": [
            {"color": row["color"], "layer": row.get("layer", "normal"), "data": points}
            for row in formula["sticks"]
            if (points := [point for item in row.get("points", []) if (point := stick_point(item))])
        ],
        "markers": [{"color": row["color"], "text": row["text"], "data": [point]} for row in formula["markers"] if (point := event_point(row))],
        "fixedTexts": [
            {
                "color": row.get("color", "#f8fafc"), "text": str(row.get("text", "")),
                "x": max(0.0, min(1.0, float(row.get("x", 0)))),
                "y": max(0.0, min(1.0, float(row.get("y", 0)))),
                "align": int(row.get("align", 0)),
            }
            for row in formula.get("fixedTexts", [])
            if isinstance(row, dict)
        ],
    }
    return json({"code": "CHANLUN" if builtin_chanlun else item.code, "name": "缠论结构" if builtin_chanlun else item.name, "placement": "main" if builtin_chanlun else item.placement, "period": period, "drawing": drawing, "calculation": "server", "calculation_bars": len(calculation_bars), "engine": formula.get("engine", "tongdaxin"), "source": "futu-opend", "adjustment": "前复权"})
