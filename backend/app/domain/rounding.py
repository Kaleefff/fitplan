"""Rounding rule of algorithms.md section 0: round half up."""

from decimal import ROUND_HALF_UP, Decimal

from app.domain.constants import WEIGHT_STEP_KG


def round_half_up(value: Decimal, places: int = 0) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def round_int(value: Decimal) -> int:
    return int(round_half_up(value))


def round_to_step(value: Decimal, step: Decimal = WEIGHT_STEP_KG) -> Decimal:
    """Round to the nearest multiple of `step` (2.5 kg by default), half up."""
    return round_half_up(value / step) * step
