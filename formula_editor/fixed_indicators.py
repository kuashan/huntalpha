"""Registry-backed fixed indicator state. Database records never register code."""

from core.python_indicators import get_python_indicator, list_python_indicators
from .models import FixedIndicatorState


def is_fixed_indicator_enabled(definition):
    """Keep CHANLUN enabled by default; new reviewed registrations opt in."""
    if definition is None or get_python_indicator(definition.code) is None:
        return False
    stored = FixedIndicatorState.objects.filter(code=definition.code).values_list(
        "enabled", flat=True
    ).first()
    if stored is not None:
        return stored
    return definition.code == "CHANLUN"


def installed_fixed_indicators():
    """Only definitions explicitly registered in the deployed server source."""
    return [(definition, is_fixed_indicator_enabled(definition)) for definition in list_python_indicators()]
