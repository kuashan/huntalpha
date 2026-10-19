"""Small, account-global indicator-layout state. No market data or private formula source."""

from django.contrib.auth import get_user_model
from django.db import transaction

from formula_editor.fixed_indicators import installed_fixed_indicators
from formula_editor.models import Formula

from .models import ChartWorkspace
from .watchlist import resolve_account_tier

COMMON_INDICATORS = [
    {"id": "builtin-ma", "name": "MA 均线", "code": "MA", "placement": "main"},
    {"id": "builtin-boll", "name": "BOLL 布林线", "code": "BOLL", "placement": "main"},
    {"id": "builtin-vol", "name": "VOL 成交量", "code": "VOL", "placement": "sub"},
    {"id": "builtin-macd", "name": "MACD", "code": "MACD", "placement": "sub"},
    {"id": "builtin-kdj", "name": "KDJ", "code": "KDJ", "placement": "sub"},
    {"id": "builtin-rsi", "name": "RSI", "code": "RSI", "placement": "sub"},
]

EMPTY_WORKSPACE = {"main": [], "sub": [], "heights": {}}


class WorkspaceValidationError(ValueError):
    pass


def allowed_placements(user):
    """Use current database entitlement; neither client names nor cached tier are trusted."""
    catalog = {item["code"]: item["placement"] for item in COMMON_INDICATORS}
    tier = resolve_account_tier(user)
    for definition, enabled in installed_fixed_indicators():
        if enabled and (definition.code == "CHANLUN" or tier == "pro"):
            catalog[definition.code] = definition.metadata()["placement"]
    if tier == "pro":
        catalog.update(Formula.objects.filter(enabled=True).values_list("code", "placement"))
    return catalog


def validate_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {"main", "sub", "heights"}:
        raise WorkspaceValidationError()
    main, sub, heights = payload["main"], payload["sub"], payload["heights"]
    if not isinstance(main, list) or not isinstance(sub, list) or not isinstance(heights, dict):
        raise WorkspaceValidationError()
    if len(main) > 32 or len(sub) > 3 or len(heights) > 32:
        raise WorkspaceValidationError()
    codes = main + sub
    if any(not isinstance(code, str) or len(code) > 64 or not code for code in codes):
        raise WorkspaceValidationError()
    if len(set(codes)) != len(codes):
        raise WorkspaceValidationError()
    if any(not isinstance(code, str) or len(code) > 64 or type(height) is not int
           or not 80 <= height <= 800 for code, height in heights.items()):
        raise WorkspaceValidationError()


def normalize_state(raw, catalog):
    """Drop revoked, missing or wrongly-placed codes without ever exposing their source."""
    if not isinstance(raw, dict):
        return {"main": [], "sub": [], "heights": {}}
    result = {"main": [], "sub": [], "heights": {}}
    seen = set()
    for placement, limit in (("main", 32), ("sub", 3)):
        codes = raw.get(placement)
        if not isinstance(codes, list):
            continue
        for code in codes:
            if (isinstance(code, str) and code not in seen and catalog.get(code) == placement):
                result[placement].append(code)
                seen.add(code)
                if len(result[placement]) >= limit:
                    break
    heights = raw.get("heights")
    if isinstance(heights, dict):
        for code in result["sub"]:
            height = heights.get(code)
            if type(height) is int and 80 <= height <= 800:
                result["heights"][code] = height
    return result


def read_workspace(user):
    """Read and persist permission revocations, including changes made outside admin."""
    with transaction.atomic():
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        record = ChartWorkspace.objects.filter(user=locked_user).first()
        if record is None:
            return {"main": [], "sub": [], "heights": {}}
        state = normalize_state(record.state, allowed_placements(locked_user))
        if state != record.state:
            record.state = state
            record.save(update_fields=["state", "updated_at"])
        return state


def write_workspace(user, payload):
    validate_payload(payload)
    with transaction.atomic():
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        state = normalize_state(payload, allowed_placements(locked_user))
        ChartWorkspace.objects.update_or_create(user=locked_user, defaults={"state": state})
        return state
