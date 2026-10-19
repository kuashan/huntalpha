"""Task 005.2: single account-global chart selection, with server-authoritative entitlements.

Only indicator codes and user-controlled pane heights are stored here. Never
store formula source, calculated chart data, market data, or per-symbol copies.
"""
from django.db import transaction

from formula_editor.fixed_indicators import installed_fixed_indicators
from formula_editor.models import Formula

from .models import AccountWorkspace
from .watchlist import resolve_account_tier


MAX_MAIN = 32
MAX_SUB = 3
MIN_HEIGHT = 90
MAX_HEIGHT = 800


class WorkspaceValidationError(ValueError):
    pass


def allowed_indicators(user, common_indicators):
    """Use the same membership, enabled-formula and fixed-registry rules as /api/indicators/."""
    items = {item["code"]: item["placement"] for item in common_indicators}
    tier = resolve_account_tier(user)
    for definition, enabled in installed_fixed_indicators():
        if enabled and (definition.code == "CHANLUN" or tier == "pro"):
            items.setdefault(definition.code, definition.placement)
    if tier == "pro":
        for code, placement in Formula.objects.filter(enabled=True).values_list("code", "placement"):
            items.setdefault(code, placement)
    return items


def _normalize(raw, allowed):
    if not isinstance(raw, dict) or set(raw) != {"main", "sub", "pane_heights"}:
        raise WorkspaceValidationError("Invalid workspace keys")
    main, sub, heights = raw["main"], raw["sub"], raw["pane_heights"]
    if not isinstance(main, list) or not isinstance(sub, list) or not isinstance(heights, dict):
        raise WorkspaceValidationError("Invalid workspace values")
    if len(main) > 64 or len(sub) > 64 or len(heights) > 64:
        raise WorkspaceValidationError("Workspace too large")
    seen = set()

    def filtered(codes, placement, maximum):
        result = []
        for code in codes:
            if not isinstance(code, str) or len(code) > 64 or not code or code != code.strip():
                raise WorkspaceValidationError("Invalid indicator code")
            normalized = code.upper()
            if normalized in seen:
                continue
            seen.add(normalized)
            if allowed.get(normalized) == placement and len(result) < maximum:
                result.append(normalized)
        return result

    saved_main = filtered(main, "main", MAX_MAIN)
    saved_sub = filtered(sub, "sub", MAX_SUB)
    saved_heights = {}
    for code, height in heights.items():
        if not isinstance(code, str) or len(code) > 64:
            raise WorkspaceValidationError("Invalid pane code")
        if not isinstance(height, int) or isinstance(height, bool) or not MIN_HEIGHT <= height <= MAX_HEIGHT:
            raise WorkspaceValidationError("Invalid pane height")
        normalized = code.upper()
        if normalized in saved_sub:
            saved_heights[normalized] = height
    return {"main": saved_main, "sub": saved_sub, "pane_heights": saved_heights}


def _stored(row):
    return {
        "main": row.main_indicators,
        "sub": row.sub_indicators,
        "pane_heights": row.sub_pane_heights,
    }


def _persist(row, normalized):
    if _stored(row) != normalized:
        row.main_indicators = normalized["main"]
        row.sub_indicators = normalized["sub"]
        row.sub_pane_heights = normalized["pane_heights"]
        row.save(update_fields=["main_indicators", "sub_indicators", "sub_pane_heights", "updated_at"])


def _safe_normalize_existing(row, allowed):
    """Corrupt/legacy JSON must never leak restricted indicators or block recovery."""
    try:
        return _normalize(_stored(row), allowed)
    except WorkspaceValidationError:
        return {"main": [], "sub": [], "pane_heights": {}}


@transaction.atomic
def read_workspace(user, common_indicators):
    allowed = allowed_indicators(user, common_indicators)
    row = AccountWorkspace.objects.select_for_update().filter(user=user).first()
    if row is None:
        return {"main": [], "sub": [], "pane_heights": {}}
    normalized = _safe_normalize_existing(row, allowed)
    # Actual account downgrade or disabled formula irrevocably prunes saved codes.
    # Temporary network/API failure does not invoke this branch.
    _persist(row, normalized)
    return normalized


@transaction.atomic
def write_workspace(user, payload, common_indicators):
    # Validate *before* modifying any stored row.
    allowed = allowed_indicators(user, common_indicators)
    normalized = _normalize(payload, allowed)
    # Lock the real account as well to serialize competing first writes.
    from django.contrib.auth import get_user_model
    get_user_model().objects.select_for_update().get(pk=user.pk)
    row, _ = AccountWorkspace.objects.select_for_update().get_or_create(user=user)
    _persist(row, normalized)
    return normalized
