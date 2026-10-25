"""PostgreSQL enum types of the schema, one StrEnum per CREATE TYPE.

Values are the database labels. Members compare equal to plain strings, so they
interoperate with the StrEnums in app/domain/.
"""

from enum import StrEnum

from sqlalchemy import Enum


class SexType(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class GoalType(StrEnum):
    WEIGHT_LOSS = "weight_loss"
    MUSCLE_GAIN = "muscle_gain"
    STRENGTH = "strength"
    MAINTENANCE = "maintenance"
    GENERAL_FITNESS = "general_fitness"
    ENDURANCE = "endurance"


class NotificationType(StrEnum):
    MEAL_REMINDER = "meal_reminder"
    TRAINING_REMINDER = "training_reminder"
    PROGRESS_UPDATE = "progress_update"
    ACHIEVEMENT = "achievement"
    MOTIVATIONAL = "motivational"


class InjurySeverity(StrEnum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class DifficultyLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class EquipmentType(StrEnum):
    NONE = "none"
    HOME = "home"
    GYM = "gym"


class BodyRegion(StrEnum):
    UPPER = "upper"
    LOWER = "lower"
    CORE = "core"


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class DietRole(StrEnum):
    PROTEIN = "protein"
    CARB = "carb"
    VEGETABLE = "vegetable"
    FRUIT = "fruit"
    DAIRY = "dairy"
    FAT = "fat"
    DISH = "dish"


class DietType(StrEnum):
    OMNIVORE = "omnivore"
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"


class AdjustmentReason(StrEnum):
    BASELINE = "baseline"
    PROGRESSION = "progression"
    REDUCE_HIGH_RPE = "reduce_high_rpe"
    REDUCE_INCOMPLETE_SET = "reduce_incomplete_set"


class ReportType(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


def pg_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Column type for a PostgreSQL enum: stores member values, not member names."""
    return Enum(enum_cls, name=name, values_callable=lambda cls: [m.value for m in cls])


SEX_TYPE = pg_enum(SexType, "sex_type")
GOAL_TYPE = pg_enum(GoalType, "goal_type")
NOTIFICATION_TYPE = pg_enum(NotificationType, "notification_type")
INJURY_SEVERITY = pg_enum(InjurySeverity, "injury_severity")
PLAN_STATUS = pg_enum(PlanStatus, "plan_status")
DIFFICULTY_LEVEL = pg_enum(DifficultyLevel, "difficulty_level")
EQUIPMENT_TYPE = pg_enum(EquipmentType, "equipment_type")
BODY_REGION = pg_enum(BodyRegion, "body_region")
MEAL_TYPE = pg_enum(MealType, "meal_type")
DIET_ROLE = pg_enum(DietRole, "diet_role")
DIET_TYPE = pg_enum(DietType, "diet_type")
ADJUSTMENT_REASON = pg_enum(AdjustmentReason, "adjustment_reason")
REPORT_TYPE = pg_enum(ReportType, "report_type")
