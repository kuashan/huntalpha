"""Shared account-center defaults, validation, and private avatar handling."""

from io import BytesIO
import warnings

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.contrib.auth import get_user_model
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import AccountProfile, account_avatar_upload_to

AVATAR_MAX_BYTES = 5 * 1024 * 1024
AVATAR_MAX_DIMENSION = 4096
AVATAR_OUTPUT_SIZE = 512
AVATAR_FORMATS = {"JPEG", "PNG", "WEBP"}
DEFAULT_ACCOUNT_PREFERENCES = {
    "price_color_mode": AccountProfile.PriceColorMode.CN,
    "default_market": AccountProfile.DefaultMarket.CN,
    "default_period": "日线",
}


class AvatarValidationError(ValueError):
    """A safe, user-facing avatar validation failure."""


def account_display_name(user):
    return user.get_full_name() or user.first_name or user.email.split("@", 1)[0]


def account_preferences(user, profile=None):
    profile = profile if profile is not None else AccountProfile.objects.filter(user=user).first()
    if profile is None:
        return dict(DEFAULT_ACCOUNT_PREFERENCES)
    return {
        "price_color_mode": profile.price_color_mode,
        "default_market": profile.default_market,
        "default_period": profile.default_period,
    }


def account_avatar_url(request, profile=None):
    if profile is None:
        return None
    if not profile.avatar:
        return None
    try:
        path = profile.avatar.url
    except ValueError:
        return None
    return request.build_absolute_uri(path) if request is not None else path


def normalize_avatar(uploaded_file):
    if uploaded_file is None:
        raise AvatarValidationError("请选择头像文件")
    if uploaded_file.size and uploaded_file.size > AVATAR_MAX_BYTES:
        raise AvatarValidationError("头像文件不能超过 5 MB")
    raw = uploaded_file.read()
    if len(raw) > AVATAR_MAX_BYTES:
        raise AvatarValidationError("头像文件不能超过 5 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                if image.format not in AVATAR_FORMATS:
                    raise AvatarValidationError("头像仅支持 JPEG、PNG 或 WebP")
                if getattr(image, "is_animated", False):
                    raise AvatarValidationError("头像必须是静态图片")
                width, height = image.size
                if width < 1 or height < 1 or width > AVATAR_MAX_DIMENSION or height > AVATAR_MAX_DIMENSION:
                    raise AvatarValidationError("头像尺寸不能超过 4096 × 4096")
                image = ImageOps.exif_transpose(image).convert("RGBA")
                side = min(image.width, image.height)
                left = (image.width - side) // 2
                top = (image.height - side) // 2
                image = image.crop((left, top, left + side, top + side))
                image = image.resize((AVATAR_OUTPUT_SIZE, AVATAR_OUTPUT_SIZE), Image.Resampling.LANCZOS)
                output = BytesIO()
                image.save(output, format="WEBP", quality=88, method=6)
                return output.getvalue()
    except AvatarValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError) as exc:
        raise AvatarValidationError("头像不是受支持的有效图片") from exc


def save_avatar(user, uploaded_file):
    content = normalize_avatar(uploaded_file)
    saved_name = None
    old_name = None
    old_name_to_delete = None
    try:
        with transaction.atomic():
            locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
            profile, _ = AccountProfile.objects.get_or_create(user=locked_user)
            old_name = profile.avatar.name if profile.avatar else None
            saved_name = default_storage.save(account_avatar_upload_to(profile, "avatar.webp"), ContentFile(content))
            profile.avatar.name = saved_name
            profile.save(update_fields=["avatar", "updated_at"])
            if old_name and old_name != saved_name:
                old_name_to_delete = old_name
        # The new object is durable before the old object is removed.  A
        # cleanup failure can leave an orphan, but never loses the new avatar.
        if old_name_to_delete:
            try:
                default_storage.delete(old_name_to_delete)
            except OSError:
                pass
        return profile
    except Exception:
        if saved_name:
            default_storage.delete(saved_name)
        raise


def delete_avatar(user):
    old_name_to_delete = None
    with transaction.atomic():
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        profile = AccountProfile.objects.filter(user=locked_user).first()
        if profile is None or not profile.avatar:
            return profile
        old_name = profile.avatar.name
        profile.avatar = None
        profile.save(update_fields=["avatar", "updated_at"])
        old_name_to_delete = old_name
    if old_name_to_delete:
        try:
            default_storage.delete(old_name_to_delete)
        except OSError:
            pass
    return profile
