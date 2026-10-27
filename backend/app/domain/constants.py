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


class DifficultyLevel(StrEnum):
    """Also the user's experience level; ordered beginner < intermediate < advanced."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class Equipment(StrEnum):
    """Ordered none < home < gym (section 4.2)."""

    NONE = "none"
    HOME = "home"
    GYM = "gym"


class InjurySeverity(StrEnum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


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

# --- Section 3: muscle groups ---------------------------------------------
UPPER_GROUPS = ("chest", "back", "shoulders", "biceps", "triceps")
LOWER_GROUPS = ("quadriceps", "hamstrings", "glutes", "calves")
CORE_GROUPS = ("core",)
ALL_GROUPS = UPPER_GROUPS + LOWER_GROUPS + CORE_GROUPS
GROUP_REGION = {
    **dict.fromkeys(UPPER_GROUPS, BodyRegion.UPPER),
    **dict.fromkeys(LOWER_GROUPS, BodyRegion.LOWER),
    **dict.fromkeys(CORE_GROUPS, BodyRegion.CORE),
}
_BASIC_MAIN_GROUPS = ("chest", "back", "shoulders", "quadriceps", "hamstrings", "glutes", "core")
MAIN_GROUPS = {
    goal: ALL_GROUPS if goal == Goal.MUSCLE_GAIN else _BASIC_MAIN_GROUPS for goal in Goal
}

# --- Section 4: training plan ----------------------------------------------
LEVEL_ORDER = (DifficultyLevel.BEGINNER, DifficultyLevel.INTERMEDIATE, DifficultyLevel.ADVANCED)
EQUIPMENT_ORDER = (Equipment.NONE, Equipment.HOME, Equipment.GYM)
SEVERE_INJURY = frozenset({InjurySeverity.MODERATE, InjurySeverity.SEVERE})

# 4.5 split templates: (session name, weekday 1 = Monday, groups); "full" = all required
SESSION_GROUPS = {
    "Full Body": "full",
    "Upper": UPPER_GROUPS,
    "Lower": LOWER_GROUPS + CORE_GROUPS,
    "Push": ("chest", "shoulders", "triceps"),
    "Pull": ("back", "biceps", "core"),
    "Legs": LOWER_GROUPS + CORE_GROUPS,
}
SPLITS = {
    1: (("Full Body", 3),),
    2: (("Full Body A", 1), ("Full Body B", 4)),
    3: (("Full Body A", 1), ("Full Body B", 3), ("Full Body C", 5)),
    4: (("Upper A", 1), ("Lower A", 2), ("Upper B", 4), ("Lower B", 5)),
    5: (("Upper", 1), ("Lower", 2), ("Push", 4), ("Pull", 5), ("Legs", 6)),
    6: (("Push A", 1), ("Pull A", 2), ("Legs A", 3), ("Push B", 4), ("Pull B", 5), ("Legs B", 6)),
    7: (
        ("Push A", 1),
        ("Pull A", 2),
        ("Legs A", 3),
        ("Push B", 4),
        ("Pull B", 5),
        ("Legs B", 6),
        ("Full Body", 7),
    ),
}

# 4.6 exercises per session, second-exercise priority (also "larger groups first")
EXERCISES_PER_SESSION = {
    DifficultyLevel.BEGINNER: 5,
    DifficultyLevel.INTERMEDIATE: 6,
    DifficultyLevel.ADVANCED: 7,
}
GROUP_PRIORITY = (
    "quadriceps",
    "back",
    "chest",
    "hamstrings",
    "glutes",
    "shoulders",
    "biceps",
    "triceps",
    "core",
    "calves",
)
FULL_SETS_MAX_EXERCISES = 8

# 4.7 goal: ((compound sets, reps, rest s), (isolation sets, reps, rest s))
SETS_REPS_REST = {
    Goal.STRENGTH: ((5, 5, 180), (3, 8, 90)),
    Goal.MUSCLE_GAIN: ((4, 8, 120), (3, 12, 75)),
    Goal.WEIGHT_LOSS: ((3, 12, 60), (3, 15, 45)),
    Goal.MAINTENANCE: ((3, 10, 90), (2, 12, 60)),
    Goal.GENERAL_FITNESS: ((3, 10, 75), (2, 12, 60)),
    Goal.ENDURANCE: ((3, 15, 45), (2, 20, 30)),
}
SESSION_BASE_SECONDS = 600
SECONDS_PER_SET = 45
DURATION_STEP_MINUTES = 5

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
