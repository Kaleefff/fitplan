"""Every constant of docs/instructions/algorithms.md in one place (section 0 and the tables).

Change a value here and in algorithms.md together; nothing else may hard-code them.
"""

from decimal import Decimal
from enum import StrEnum


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class Goal(StrEnum):
    WEIGHT_LOSS = "weight_loss"
    MUSCLE_GAIN = "muscle_gain"
    STRENGTH = "strength"
    MAINTENANCE = "maintenance"
    GENERAL_FITNESS = "general_fitness"
    ENDURANCE = "endurance"


class BodyRegion(StrEnum):
    UPPER = "upper"
    LOWER = "lower"
    CORE = "core"


# --- Section 0: ranges (FR-U7 and others) ----------------------------------
AGE_MIN, AGE_MAX = 16, 100
HEIGHT_CM_MIN, HEIGHT_CM_MAX = 120, 250
WEIGHT_KG_MIN, WEIGHT_KG_MAX = Decimal("30"), Decimal("300")
PAL_VALUES = (Decimal("1.2"), Decimal("1.375"), Decimal("1.55"), Decimal("1.725"), Decimal("1.9"))
RPE_MIN, RPE_MAX = 1, 10
HUNGER_MIN, HUNGER_MAX = 1, 10
PASSWORD_MIN_BYTES, PASSWORD_MAX_BYTES = 8, 72
TRAINING_DAYS_MIN, TRAINING_DAYS_MAX = 1, 7
MEALS_PER_DAY_MIN, MEALS_PER_DAY_MAX = 3, 5
PHOTO_MAX_BYTES = 8 * 1024 * 1024
RECOGNITION_EXPIRY_HOURS = 6
PLAN_DURATION_DAYS = 56
WEIGHT_STEP_KG = Decimal("2.5")

# --- Section 1: BMR sex constant (Mifflin-St Jeor) -------------------------
BMR_SEX_CONSTANT = {
    Sex.MALE: Decimal("5"),
    Sex.FEMALE: Decimal("-161"),
    Sex.OTHER: Decimal("-78"),
}

# --- Section 2: targets by goal --------------------------------------------
KCAL_FLOOR = {
    Sex.MALE: 1500,
    Sex.FEMALE: 1200,
    Sex.OTHER: 1200,
}
PROTEIN_MAX_KCAL_SHARE = Decimal("0.35")
KCAL_PER_G_PROTEIN = Decimal("4")
KCAL_PER_G_CARBS = Decimal("4")
KCAL_PER_G_FAT = Decimal("9")

# goal: (kcal factor, protein g/kg, fat share of kcal)
GOAL_TARGETS = {
    Goal.WEIGHT_LOSS: (Decimal("0.80"), Decimal("2.0"), Decimal("0.30")),
    Goal.MUSCLE_GAIN: (Decimal("1.10"), Decimal("1.8"), Decimal("0.25")),
    Goal.STRENGTH: (Decimal("1.05"), Decimal("1.8"), Decimal("0.25")),
    Goal.MAINTENANCE: (Decimal("1.00"), Decimal("1.6"), Decimal("0.30")),
    Goal.GENERAL_FITNESS: (Decimal("1.00"), Decimal("1.6"), Decimal("0.30")),
    Goal.ENDURANCE: (Decimal("1.05"), Decimal("1.4"), Decimal("0.20")),
}

# --- Section 6: adaptation and progression ---------------------------------
REDUCE_RPE_THRESHOLD = 9
RESERVE_RPE_MAX = 7
REDUCTION_FACTOR = Decimal("0.9")
BASELINE_REDUCE_FACTOR = Decimal("0.9")
MIN_SETS = 2
BODYWEIGHT_MAX_REPS = 20
PROGRESSION_STEP_KG = {
    BodyRegion.UPPER: Decimal("2.5"),
    BodyRegion.CORE: Decimal("2.5"),
    BodyRegion.LOWER: Decimal("5"),
}
PR_MAX_REPS = 12

# --- Section 7: compliance -------------------------------------------------
DIET_COMPLIANCE_TOLERANCE = Decimal("0.10")

# --- Section 9: goal prediction --------------------------------------------
PREDICTION_WINDOW_DAYS = 28
PREDICTION_MIN_WEIGH_INS = 3
PREDICTION_MIN_SPAN_DAYS = 7
GOAL_REACHED_TOLERANCE_KG = 0.5
MIN_SLOPE_KG_PER_DAY = 0.01
MAX_DAYS_TO_GOAL = 730
LOW_FIT_R2 = 0.5
MAX_GAP_DAYS = 10
LOW_TRAINING_COMPLIANCE_PCT = 60.0
