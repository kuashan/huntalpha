from datetime import datetime, timedelta, timezone
import json as json_module
import math
import os
import re
import socket
import subprocess
import queue
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.http import JsonResponse, StreamingHttpResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from futu import AuType, KLType, OpenQuoteContext, RET_OK
from formula_editor.models import Formula
from .models import AccountProfile, MarketSymbol, WatchlistEntry
from .account import (
    AvatarValidationError, account_avatar_url, account_display_name, account_preferences as account_preferences_data,
    delete_avatar, save_avatar,
)
from .market_indices import FutuOpenDIndexAdapter, grouped_snapshot_response, unavailable_index_items
from .realtime import (
    NormalizedBar,
    RealtimeProviderError,
    get_realtime_registry,
    market_for_symbol,
    optional_numeric,
    provider_time_to_timestamp,
    timestamp_to_market_datetime,
)
from .realtime.formula_scheduler import FormulaRunRegistry
from .realtime.provider import REALTIME_PERIOD_SUBTYPES
from .symbol_catalog import FUTU_PROVIDER, MARKET_DEFINITIONS, SUPPORTED_MARKETS
from .watchlist import account_tier_payload, watchlist_limit_for_user

PERIODS = {"1分": KLType.K_1M, "5分": KLType.K_5M, "15分": KLType.K_15M, "30分": KLType.K_30M, "60分": KLType.K_60M, "2小时": KLType.K_120M, "4小时": KLType.K_240M, "日线": KLType.K_DAY, "周线": KLType.K_WEEK, "月线": KLType.K_MON}
KLINE_PAGE_SIZE = 1000
# Calendar windows chosen to contain at least one page of trading bars for
# every supported period without making a single OpenD request unbounded.
KLINE_LOOKBACK_DAYS = {"1分": 14, "5分": 45, "15分": 90, "30分": 180, "60分": 365, "2小时": 730, "4小时": 1460, "日线": 1825, "周线": 7300, "月线": 14600}
formula_run_registry = FormulaRunRegistry()

def json(data, status=200):
    result = JsonResponse(data, status=status)
    result["Access-Control-Allow-Origin"] = "http://127.0.0.1:5173"
    result["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    result["Access-Control-Allow-Headers"] = "Content-Type, X-CSRFToken"
    result["Access-Control-Allow-Credentials"] = "true"
    return result


def user_payload(user, request=None):
    profile = AccountProfile.objects.filter(user=user).first()
    return {
        "email": user.email,
        "name": account_display_name(user),
        "avatar_url": account_avatar_url(request, profile),
        "preferences": account_preferences_data(user, profile),
        **account_tier_payload(user),
    }


def visitor_payload():
    return {"email": "", "name": "访客模式", **account_tier_payload(None)}


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
    """Members and the limited visitor mode may access the terminal APIs."""
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated and not is_visitor(request):
            return json({"error": "请先登录后访问量化终端", "authenticated": False}, 401)
        return view(request, *args, **kwargs)
    return wrapped


def api_member_required(view):
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return json({"error": "AI 分析仅向已登录账户开放"}, 403)
        return view(request, *args, **kwargs)
    return wrapped


def api_account_required(view):
    """Require a real authenticated account for account-center APIs."""
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return json({"error": "请先登录后访问账户中心", "code": "login_required"}, 403)
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
    if request.user.is_authenticated:
        return json({"authenticated": True, "visitor": False, **account_tier_payload(request.user), "user": user_payload(request.user, request)})
    if is_visitor(request):
        return json({"authenticated": True, "visitor": True, **account_tier_payload(None), "user": visitor_payload()})
    return json({"authenticated": False, **account_tier_payload(None)}, 401)


@require_GET
@api_account_required
def account_summary(request):
    tier = account_tier_payload(request.user)
    total = WatchlistEntry.objects.filter(user=request.user).count()
    limit = watchlist_limit_for_user(request.user)
    profile = AccountProfile.objects.filter(user=request.user).first()
    return json({
        "user": {
            "name": account_display_name(request.user),
            "email": request.user.email,
            "avatar_url": account_avatar_url(request, profile),
        },
        "membership": {
            "tier": tier["tier"],
            "tier_label": tier["tier_label"],
            "expires_at": None,
        },
        "ai_beans": {
            "status": "not_enabled",
            "balance": None,
            "permanent": True,
        },
        "watchlist": {
            "total": total,
            "limit": limit,
            "remaining": max(limit - total, 0),
        },
        "preferences": account_preferences_data(request.user, profile),
    })


@require_http_methods(["PATCH"])
@api_account_required
def account_profile(request):
    payload = auth_body(request)
    if not isinstance(payload, dict) or set(payload) != {"display_name"}:
        return json({"error": "仅支持修改显示名称", "code": "invalid_profile_fields"}, 400)
    display_name_value = payload.get("display_name")
    if not isinstance(display_name_value, str):
        return json({"error": "显示名称无效", "code": "display_name_invalid"}, 400)
    display_name = display_name_value.strip()
    if not display_name:
        return json({"error": "显示名称不能为空", "code": "display_name_invalid"}, 400)
    if len(display_name) > 50:
        return json({"error": "显示名称不能超过 50 个字符", "code": "display_name_invalid"}, 400)
    request.user.first_name = display_name
    request.user.save(update_fields=["first_name"])
    return json({"status": "ok", "user": user_payload(request.user, request)})


@require_http_methods(["PATCH"])
@api_account_required
def account_preferences(request):
    payload = auth_body(request)
    allowed = {"price_color_mode", "default_market", "default_period"}
    if not isinstance(payload, dict) or not set(payload).issubset(allowed):
        return json({"error": "存在不支持的偏好字段", "code": "invalid_preference_fields"}, 400)
    choices = {
        "price_color_mode": {choice.value for choice in AccountProfile.PriceColorMode},
        "default_market": {choice.value for choice in AccountProfile.DefaultMarket},
        "default_period": {choice[0] for choice in AccountProfile.PERIOD_CHOICES},
    }
    for field, value in payload.items():
        if not isinstance(value, str) or value not in choices[field]:
            return json({"error": f"{field} 的值无效", "code": "invalid_preference_value", "field": field}, 400)
    with transaction.atomic():
        profile, _ = AccountProfile.objects.select_for_update().get_or_create(user=request.user)
        for field, value in payload.items():
            setattr(profile, field, value)
        profile.save(update_fields=[*payload.keys(), "updated_at"])
    preferences = account_preferences_data(request.user, profile)
    return json({"status": "ok", "preferences": preferences, "user": user_payload(request.user, request)})


@require_http_methods(["POST", "DELETE"])
@api_account_required
def account_avatar(request):
    if request.method == "DELETE":
        profile = delete_avatar(request.user)
        return json({"status": "ok", "avatar_url": account_avatar_url(request, profile)})
    try:
        profile = save_avatar(request.user, request.FILES.get("avatar"))
    except AvatarValidationError as exc:
        return json({"error": str(exc), "code": "avatar_invalid"}, 400)
    return json({"status": "ok", "avatar_url": account_avatar_url(request, profile)})


@require_POST
@api_account_required
def change_password(request):
    payload = auth_body(request)
    if not isinstance(payload, dict):
        return json({"error": "请求格式无效", "code": "invalid_request"}, 400)
    current_password = str(payload.get("current_password", ""))
    new_password = str(payload.get("new_password", ""))
    confirm_password = str(payload.get("confirm_password", ""))
    if not request.user.check_password(current_password):
        return json({"error": "当前密码不正确", "code": "current_password_invalid"}, 400)
    if new_password != confirm_password:
        return json({"error": "两次输入的新密码不一致", "code": "password_mismatch"}, 400)
    if not new_password:
        return json({"error": "请输入新密码", "code": "password_invalid"}, 400)
    try:
        validate_password(new_password, request.user)
    except ValidationError as exc:
        return json({"error": " ".join(exc.messages), "code": "password_invalid"}, 400)
    request.user.set_password(new_password)
    request.user.save(update_fields=["password"])
    update_session_auth_hash(request, request.user)
    return json({"status": "ok", "message": "密码已更新"})


def auth_body(request):
    try:
        return json_module.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json_module.JSONDecodeError):
        return None


@csrf_exempt
@require_POST
def auth_register(request):
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
    return json({"authenticated": True, **account_tier_payload(candidate), "user": user_payload(candidate, request)}, 201)


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
    request.session.pop("quantscope_visitor", None)
    login(request, user)
    return json({"authenticated": True, **account_tier_payload(user), "user": user_payload(user, request)})


@csrf_exempt
@require_POST
def auth_logout(request):
    logout(request)
    request.session.pop("quantscope_visitor", None)
    return json({"authenticated": False})


@csrf_exempt
@require_POST
def auth_guest(request):
    request.session["quantscope_visitor"] = True
    return json({"authenticated": True, "visitor": True, **account_tier_payload(None), "user": visitor_payload()})


@require_GET
@ensure_csrf_cookie
def csrf_token(request):
    return json({"csrfToken": get_token(request)})


def _watchlist_error(message, code, request, status):
    return json({"error": message, "code": code, **_watchlist_totals(request)}, status)


def _watchlist_get(request):
    market = request.GET.get("market", "").strip().lower() or None
    if market not in {None, "cn", "hk", "us", "crypto"}:
        return json({"error": "不支持的市场"}, 400)
    totals = _watchlist_totals(request)
    if not request.user.is_authenticated:
        return json({
            "items": [],
            "market": market,
            "mode": "watchlist",
            "status": "login_required",
            "error": "登录或注册后使用自选功能",
            **totals,
        })
    if market == "crypto":
        return json({
            "items": [],
            "market": market,
            "mode": "watchlist",
            "status": "unavailable",
            "error": "真实数据源尚未接入",
            **totals,
        })
    entries = WatchlistEntry.objects.select_related("symbol").filter(user=request.user)
    if market:
        entries = entries.filter(symbol__market=market)
    return json({
        "items": [watchlist_item_data(entry) for entry in entries],
        "market": market,
        "mode": "watchlist",
        "status": "ok",
        **totals,
    })


def _watchlist_create(request):
    if is_visitor(request):
        return _watchlist_error("登录或注册后使用自选功能", "login_required", request, 403)
    payload = auth_body(request)
    code = str(payload.get("code", "")).strip().upper() if isinstance(payload, dict) else ""
    if not code or len(code) > 32:
        return _watchlist_error("证券代码无效", "invalid_symbol_code", request, 400)
    symbol = MarketSymbol.objects.filter(code__iexact=code).first()
    if symbol is None:
        return _watchlist_error("未找到真实证券", "symbol_not_found", request, 404)
    if not symbol.active:
        return _watchlist_error("该证券当前不可用", "symbol_inactive", request, 409)
    if symbol.security_type != "STOCK":
        return _watchlist_error("仅支持普通股票", "symbol_unavailable", request, 409)
    try:
        with transaction.atomic():
            locked_user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            entry = WatchlistEntry.objects.select_related("symbol").filter(
                user=locked_user, symbol=symbol
            ).first()
            if entry is not None:
                return json({
                    "status": "already_exists",
                    "item": watchlist_item_data(entry),
                    **_watchlist_totals_for_user(locked_user),
                })
            totals = _watchlist_totals_for_user(locked_user)
            if totals["total"] >= totals["limit"]:
                return json({
                    "error": "自选已满",
                    "code": "watchlist_limit_reached",
                    **totals,
                }, 409)
            entry = WatchlistEntry.objects.create(user=locked_user, symbol=symbol)
            return json({
                "status": "created",
                "item": watchlist_item_data(entry),
                **_watchlist_totals_for_user(locked_user),
            }, 201)
    except IntegrityError:
        # The unique constraint makes a concurrent duplicate idempotent even
        # when two browser requests arrive before either response returns.
        entry = WatchlistEntry.objects.select_related("symbol").filter(
            user=request.user, symbol=symbol
        ).first()
        if entry is not None:
            return json({
                "status": "already_exists",
                "item": watchlist_item_data(entry),
                **_watchlist_totals(request),
            })
        return _watchlist_error("无法创建自选", "watchlist_write_conflict", request, 409)
    except OperationalError:
        return _watchlist_error("自选正在被其他请求更新，请稍后重试", "watchlist_busy", request, 503)


@require_http_methods(["GET", "POST"])
@api_terminal_required
def watchlist(request):
    return _watchlist_get(request) if request.method == "GET" else _watchlist_create(request)


@require_http_methods(["DELETE"])
@api_terminal_required
def watchlist_delete(request, code):
    if is_visitor(request):
        return _watchlist_error("登录或注册后使用自选功能", "login_required", request, 403)
    normalized = str(code).strip().upper()
    entry = WatchlistEntry.objects.filter(
        user=request.user, symbol__code__iexact=normalized
    ).first()
    if entry is None:
        return _watchlist_error("该证券不在自选中", "not_watchlisted", request, 404)
    entry.delete()
    return json({
        "status": "removed",
        "symbol_code": normalized,
        **_watchlist_totals(request),
    })

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
    rows = []
    for row in frame.itertuples():
        symbol = str(getattr(row, "code", ""))
        event_time = provider_time_to_timestamp(getattr(row, "time_key", None), market_for_symbol(symbol))
        if event_time is None:
            continue
        rows.append({
            "time": event_time,
            "open": optional_numeric(getattr(row, "open", None)),
            "high": optional_numeric(getattr(row, "high", None)),
            "low": optional_numeric(getattr(row, "low", None)),
            "close": optional_numeric(getattr(row, "close", None)),
            "volume": optional_numeric(getattr(row, "volume", None)),
            "amount": optional_numeric(getattr(row, "turnover", None)),
            "turnover_rate": optional_numeric(getattr(row, "turnover_rate", None)),
            "last_close": optional_numeric(getattr(row, "last_close", None)),
        })
    return rows


def request_history_rows(client, code, period, before=None):
    """Load one bounded, explicitly forward-adjusted OpenD history window.

    This is the one runtime market-data path for both chart pages and formula
    calculation.  Imported Tongdaxin files are deliberately *not* a fallback:
    they remain offline regression fixtures only, so the browser cannot show
    one price series while the formula calculates another.
    """
    market = market_for_symbol(code)
    end = timestamp_to_market_datetime(before, market) if before else datetime.now(timezone.utc).astimezone(
        timestamp_to_market_datetime(0, market).tzinfo
    )
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
    if before is None:
        registry = get_realtime_registry()
        rows = merge_realtime_rows(rows, code, period, registry.state_store.capture(registry.key_for(code, period)))
    rows = rows[-count:]
    # A non-empty page can have older provider history.  The client will make
    # at most one extra request to determine the true beginning of history.
    return rows, bool(rows), None


def merge_realtime_rows(rows, code, period, calculation_snapshot=None):
    """Overlay the shared authoritative current bar on a historical response."""
    if calculation_snapshot is None:
        registry = get_realtime_registry()
        calculation_snapshot = registry.state_store.capture(registry.key_for(code, period))
    if calculation_snapshot.current_bar is None:
        return rows
    current = calculation_snapshot.current_bar.to_dict()
    bar = {field: current.get(field) for field in (
        "time", "open", "high", "low", "close", "volume", "amount", "turnover_rate"
    )}
    if not rows or bar["time"] > rows[-1]["time"]:
        return [*rows, bar]
    if bar["time"] == rows[-1]["time"]:
        return [*rows[:-1], {**rows[-1], **bar}]
    return rows


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
            market = market_for_symbol(code)
            market_tz = timestamp_to_market_datetime(0, market).tzinfo
            market_date = datetime.now(timezone.utc).astimezone(market_tz).date()
            bars = [{
                "time": provider_time_to_timestamp(f"{market_date} {row.time}", market),
                "open": optional_numeric(row.cur_price),
                "high": optional_numeric(row.cur_price),
                "low": optional_numeric(row.cur_price),
                "close": optional_numeric(row.cur_price),
                "volume": optional_numeric(row.volume),
            } for row in frame.itertuples() if not row.is_blank]
            return json({"code": code.upper(), "period": period, "bars": bars, "source": "futu-opend", "adjustment": "实时分时", "has_more": False})
        bars, has_more, error = request_page(client, code, period, count, before)
        if error: return json({"error": error}, 502)
        return json({"code": code.upper(), "period": period, "bars": bars, "source": "futu-opend", "adjustment": "前复权", "has_more": has_more})
    except Exception as exc:
        return json({"error": f"富途 OpenD 不可用：{exc}", "source": "futu-opend"}, 503)
    finally:
        if client is not None:
            client.close()


def _sse_event(payload):
    event_type = payload.get("type", "message")
    return f"event: {event_type}\ndata: {json_module.dumps(payload, ensure_ascii=False)}\n\n"


@require_GET
@api_terminal_required
def realtime_market_stream(request, code):
    period = request.GET.get("period", "日线")
    if period not in REALTIME_PERIOD_SUBTYPES:
        return json({"error": "该周期暂不支持实时 K 线推送", "code": "realtime_unavailable", "mode": "unavailable"}, 422)
    registry = get_realtime_registry()
    try:
        consumer = registry.subscribe(code.upper(), period)
    except RealtimeProviderError as exc:
        return json({
            "error": str(exc), "code": "realtime_unavailable", "source": registry.provider_name, "mode": "unavailable",
        }, 503)

    def events():
        try:
            while not consumer.closed:
                try:
                    payload = consumer.get(timeout=15)
                except queue.Empty:
                    registry.health_check()
                    yield ": keep-alive\n\n"
                    continue
                yield _sse_event(payload)
        finally:
            registry.unsubscribe(consumer)

    response = StreamingHttpResponse(events(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["Connection"] = "keep-alive"
    response["X-Accel-Buffering"] = "no"
    response["Access-Control-Allow-Origin"] = "http://127.0.0.1:5173"
    response["Access-Control-Allow-Credentials"] = "true"
    return response


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


def history_bars(code, period, calculation_snapshot=None):
    """Load the complete bounded OpenD window used for one formula run."""
    client = context()
    try:
        if period == "分时":
            return None, None, "自定义公式暂不支持分时；请选择 K 线周期"
        bars, error = request_history_rows(client, code, period)
        if not error:
            bars = merge_realtime_rows(bars, code, period, calculation_snapshot)
        return bars, live_float_shares(client, code) if not error else None, error
    finally:
        client.close()


def indicator_data(item, include_source=False):
    data = {"id": item.id, "name": item.name, "code": item.code, "placement": item.placement, "version": item.version, "enabled": item.enabled, "updated_at": item.updated_at.isoformat()}
    if include_source:
        data["source"] = item.source
    return data


def symbol_data(item):
    return {
        "code": item.code,
        "name": item.name,
        "market": item.market,
        "exchange": item.exchange,
        "security_type": item.security_type,
        "active": item.active,
        "provider": item.provider,
        "source": item.provider,
        "provider_symbol": item.provider_symbol,
        "market_cap": float(item.market_cap) if item.market_cap is not None else None,
        "market_cap_currency": item.market_cap_currency,
        "market_cap_updated_at": item.market_cap_updated_at.isoformat() if item.market_cap_updated_at else None,
        "catalog_updated_at": item.catalog_updated_at.isoformat(),
    }


def _watchlist_totals_for_user(user):
    if not user.is_authenticated:
        return {"total": 0, "limit": 0, "remaining": 0}
    limit = watchlist_limit_for_user(user)
    total = WatchlistEntry.objects.filter(user=user).count()
    return {"total": total, "limit": limit, "remaining": max(limit - total, 0)}


def _watchlist_totals(request):
    if not request.user.is_authenticated:
        return {"total": 0, "limit": 0, "remaining": 0}
    return _watchlist_totals_for_user(request.user)


def _watchlisted_codes(request, items):
    if not request.user.is_authenticated or not items:
        return set()
    codes = [item.code for item in items]
    return set(
        WatchlistEntry.objects.filter(
            user=request.user, symbol__code__in=codes
        ).values_list("symbol__code", flat=True)
    )


def _catalog_item_data(request, item, watchlisted_codes=None):
    if watchlisted_codes is None:
        watchlisted_codes = _watchlisted_codes(request, [item])
    return {
        **symbol_data(item),
        "watchlisted": item.code in watchlisted_codes,
    }


def watchlist_item_data(entry):
    item = entry.symbol
    return {
        "code": item.code,
        "name": item.name,
        "market": item.market,
        "watchlisted": True,
    }


def _market_catalog_queryset(market):
    return MarketSymbol.objects.filter(market=market, active=True, security_type="STOCK")


def _catalog_status(market, leaders_available=None):
    definition = MARKET_DEFINITIONS.get(market)
    if definition is None:
        return {
            "market": market,
            "name": "加密资产" if market == "crypto" else market,
            "provider": None,
            "catalog_available": False,
            "leaders_available": False,
            "status": "unavailable",
            "error": "真实数据源未接入" if market == "crypto" else "不支持的市场",
        }
    catalog_available = _market_catalog_queryset(market).exists()
    if leaders_available is None:
        leaders_available = _market_catalog_queryset(market).filter(market_cap__gt=0).exists()
    latest = _market_catalog_queryset(market).order_by("-catalog_updated_at").first()
    status_error = None
    if not catalog_available:
        status_error = "真实证券目录尚未同步"
    elif not leaders_available:
        status_error = "真实总市值榜单暂不可用"
    return {
        "market": market,
        "name": definition.name,
        "provider": FUTU_PROVIDER,
        "catalog_available": catalog_available,
        "leaders_available": leaders_available,
        "status": "ok" if catalog_available else "unavailable",
        "error": status_error,
        "updated_at": latest.catalog_updated_at.isoformat() if latest else None,
    }


@require_GET
@api_terminal_required
def markets(request):
    return json({"markets": [_catalog_status(market) for market in SUPPORTED_MARKETS] + [_catalog_status("crypto")]})


@require_GET
@api_terminal_required
def market_index_snapshots(request):
    """Return only real, lightweight OpenD index snapshots for the header."""
    adapter = FutuOpenDIndexAdapter(context)
    try:
        items = adapter.fetch()
    except Exception:
        items = unavailable_index_items()
    return json(grouped_snapshot_response(items))


def _parse_catalog_paging(request):
    try:
        limit = int(request.GET.get("limit", 20))
        page = int(request.GET.get("page", 1))
    except ValueError:
        return None, None, "limit 和 page 必须是整数"
    if limit < 1 or limit > 50:
        return None, None, "limit 必须在 1 到 50 之间"
    if page < 1:
        return None, None, "page 必须是正整数"
    return limit, page, None


def _catalog_response(request, market, items, query="", page=1, limit=5, total=None, mode="leaders", error=None):
    status = _catalog_status(market, leaders_available=bool(items) if mode == "leaders" else None)
    watchlist_totals = _watchlist_totals(request)
    watchlisted_codes = _watchlisted_codes(request, items)
    return json({
        **status,
        "query": query,
        "page": page,
        "limit": limit,
        "total": len(items) if total is None else total,
        "mode": mode,
        "leader_metric": "market_cap" if mode == "leaders" else None,
        "items": [_catalog_item_data(request, item, watchlisted_codes) for item in items],
        "watchlist_total": watchlist_totals["total"],
        "watchlist_limit": watchlist_totals["limit"],
        "watchlist_remaining": watchlist_totals["remaining"],
        **({"error": error} if error else {}),
    })


@require_GET
@api_terminal_required
def market_leaders(request, market):
    if market not in MARKET_DEFINITIONS:
        return _catalog_response(request, market, [], mode="leaders", error="真实数据源未接入") if market == "crypto" else json({"error": "不支持的市场"}, 400)
    metric = request.GET.get("metric", "market_cap").strip() or "market_cap"
    leader_metrics = {"market_cap": "-market_cap"}
    if metric not in leader_metrics:
        return json({"error": "不支持的榜单指标"}, 400)
    items = list(_market_catalog_queryset(market).filter(**{f"{metric}__gt": 0}).order_by(leader_metrics[metric], "code")[:5])
    return _catalog_response(request, market, items, limit=5, mode="leaders")


@require_GET
@api_terminal_required
def symbols(request, market):
    if market not in MARKET_DEFINITIONS:
        return _catalog_response(request, market, [], mode="unavailable", error="真实数据源未接入") if market == "crypto" else json({"error": "不支持的市场"}, 400)
    query = request.GET.get("q", "").strip()
    if len(query) > 80:
        return json({"error": "搜索内容过长"}, 400)
    if not query:
        return market_leaders(request, market)
    limit, page, error = _parse_catalog_paging(request)
    if error:
        return json({"error": error}, 400)
    queryset = _market_catalog_queryset(market).filter(
        Q(code__icontains=query) | Q(name__icontains=query)
    ).order_by("name", "code")
    total = queryset.count()
    start = (page - 1) * limit
    items = list(queryset[start:start + limit])
    return _catalog_response(request, market, items, query=query, page=page, limit=limit, total=total, mode="search")


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
    try:
        requested_revision = max(0, int(request.GET.get("revision", 0)))
    except (TypeError, ValueError):
        return json({"error": "revision 必须是整数", "code": "invalid_revision"}, 400)
    # Future functions such as BACKSET and formulas using BARSCOUNT(C)=1
    # need the beginning of the same real OpenD history shown to the chart.
    # Calculate the complete bounded window, then return its visible tail.
    registry = get_realtime_registry()
    calculation_snapshot = registry.state_store.capture(registry.key_for(symbol, period))
    if requested_revision > calculation_snapshot.revision:
        return json({
            "error": "实时版本已更新，请重试",
            "code": "revision_not_available",
            "revision": calculation_snapshot.revision,
        }, 409)
    calculation_bars, float_shares, error = history_bars(symbol, period, calculation_snapshot)
    if error:
        return json({"error": error}, 400 if period == "分时" else 502)
    visible_start = max(0, len(calculation_bars) - count)
    bars = calculation_bars[visible_start:]
    try:
        formula_id = "builtin-chanlun" if builtin_chanlun else item.code
        formula_version = 1 if builtin_chanlun else item.version
        formula_key = (
            registry.provider_name, symbol.upper(), period, formula_id, formula_version, calculation_snapshot.revision,
        )

        def run_formula():
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
            return json_module.loads(completed.stdout)

        formula = formula_run_registry.run(formula_key, calculation_snapshot.revision, run_formula)
    except subprocess.CalledProcessError as exc:
        # Formula source is private. Only a function name is safe and useful
        # to return to the browser; parser excerpts and source fragments stay
        # in the admin/server boundary.
        detail = (exc.stderr or "").strip()
        unsupported = re.search(r"暂不支持通达信函数：[A-Za-z][A-Za-z0-9_]*", detail)
        message = unsupported.group(0) if unsupported else "公式语法或参数不受支持，请在后台检查公式"
        return json({"error": f"指标计算失败：{message}"}, 422)
    except subprocess.TimeoutExpired:
        return json({"error": "指标计算耗时过长，请稍后重试或降低同时运行的指标数量"}, 422)
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
    return json({"code": "CHANLUN" if builtin_chanlun else item.code, "name": "缠论结构" if builtin_chanlun else item.name, "placement": "main" if builtin_chanlun else item.placement, "period": period, "drawing": drawing, "calculation": "server", "calculation_bars": len(calculation_bars), "revision": calculation_snapshot.revision, "engine": formula.get("engine", "tongdaxin"), "source": registry.provider_name, "adjustment": "前复权"})
