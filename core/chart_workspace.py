"""Account-owned chart preferences; never store market bars or formula sources.

The catalog is authoritative: clients may only persist codes they are currently
entitled to use. Read-time pruning also covers membership changes made with
QuerySet.update(), which bypasses Django save signals.
"""
from django.contrib.auth import get_user_model
from django.db import transaction

from formula_editor.fixed_indicators import installed_fixed_indicators
from formula_editor.models import Formula

from .models import ChartWorkspace
from .watchlist import resolve_account_tier

MAX_INDICATORS = 64
MAX_SUB_PANES = 3
MIN_PANE_HEIGHT = 60
MAX_PANE_HEIGHT = 2000


class InvalidWorkspace(ValueError):
    pass


class WorkspacePermissionDenied(InvalidWorkspace):
    pass


def allowed_catalog(user):
    # Import only when called to avoid a module import cycle with API views.
    from .views import COMMON_INDICATORS

    tier = resolve_account_tier(user)
    allowed = {item["code"]: item["placement"] for item in COMMON_INDICATORS}
    for definition, enabled in installed_fixed_indicators():
        if enabled and (tier == "pro" or definition.code == "CHANLUN"):
            info = definition.metadata()
            allowed[info["code"]] = info["placement"]
    if tier == "pro":
        for item in Formula.objects.filter(enabled=True).only("code", "placement"):
            allowed[item.code] = item.placement
    return allowed


def normalize_saved(workspace, catalog):
    """Strip revoked/removed indicators without exposing private content."""
    def keep(codes, placement, limit):
        valid = []
        for code in codes if isinstance(codes, list) else []:
            if isinstance(code, str) and catalog.get(code) == placement and code not in valid:
                valid.append(code)
            if len(valid) == limit:
                break
        return valid

    main = keep(workspace.main, "main", MAX_INDICATORS)
    sub = keep(workspace.sub, "sub", MAX_SUB_PANES)
    saved_heights = workspace.pane_heights if isinstance(workspace.pane_heights, dict) else {}
    heights = {
        code: value for code, value in saved_heights.items()
        if code in sub and type(value) is int and MIN_PANE_HEIGHT <= value <= MAX_PANE_HEIGHT
    }
    return {"main": main, "sub": sub, "pane_heights": heights}


def _update_if_changed(workspace, state):
    changes = []
    for field, value in state.items():
        if getattr(workspace, field) != value:
            setattr(workspace, field, value)
            changes.append(field)
    if changes:
        workspace.save(update_fields=[*changes, "updated_at"])
    return state


def get_workspace(user):
    with transaction.atomic():
        workspace = ChartWorkspace.objects.select_for_update().filter(user=user).first()
        if workspace is None:
            return {"main": [], "sub": [], "pane_heights": {}}
        return _update_if_changed(workspace, normalize_saved(workspace, allowed_catalog(user)))


def prune_workspace_for_user(user_id):
    """Eager cleanup for admin membership saves; lazy GET handles bulk updates."""
    with transaction.atomic():
        workspace = ChartWorkspace.objects.select_for_update().filter(user_id=user_id).first()
        if workspace is not None:
            user = get_user_model().objects.get(pk=user_id)
            _update_if_changed(workspace, normalize_saved(workspace, allowed_catalog(user)))


def validate_workspace(payload, catalog):
    if not isinstance(payload, dict) or set(payload) != {"main", "sub", "pane_heights"}:
        raise InvalidWorkspace("图表配置格式无效")
    main, sub, heights = (payload[key] for key in ("main", "sub", "pane_heights"))
    if not isinstance(main, list) or not isinstance(sub, list) or not isinstance(heights, dict):
        raise InvalidWorkspace("指标和副图数据格式无效")
    if len(main) > MAX_INDICATORS or len(sub) > MAX_SUB_PANES:
        raise InvalidWorkspace("指标或副图数量超出支持范围")
    seen = set()
    for code, placement in [(code, "main") for code in main] + [(code, "sub") for code in sub]:
        if not isinstance(code, str) or not code or len(code) > 100 or code in seen:
            raise InvalidWorkspace("指标代码无效或重复")
        seen.add(code)
        if catalog.get(code) != placement:
            raise WorkspacePermissionDenied("指标已停用、无权限或位置无效，请刷新后重试")
    if set(heights) - set(sub):
        raise InvalidWorkspace("只允许保存当前副图的高度")
    for value in heights.values():
        if type(value) is not int or not MIN_PANE_HEIGHT <= value <= MAX_PANE_HEIGHT:
            raise InvalidWorkspace("副图高度无效")
    return {"main": main, "sub": sub, "pane_heights": heights}


def put_workspace(user, payload):
    # Lock account first to serialize writes for the same user.
    with transaction.atomic():
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        state = validate_workspace(payload, allowed_catalog(locked_user))
        ChartWorkspace.objects.update_or_create(user=locked_user, defaults=state)
        return state
