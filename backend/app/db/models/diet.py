"""Module 2: diet plan, food library and nutrition logs."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    FetchedValue,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import NOW, TIMESTAMPTZ, Base
from app.db.enums import (
    DIET_ROLE,
    DIET_TYPE,
    GOAL_TYPE,
    MEAL_TYPE,
    PLAN_STATUS,
    DietRole,
    DietType,
    GoalType,
    MealType,
    PlanStatus,
)


class FoodCategory(Base):
    __tablename__ = "food_category"

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    category_name: Mapped[str] = mapped_column(String(45), unique=True)
    description: Mapped[str] = mapped_column(String(250))


class FoodItem(Base):
    __tablename__ = "food_item"
    __table_args__ = (
        CheckConstraint("cals_per_100g >= 0"),
        CheckConstraint("protein_per_100g BETWEEN 0 AND 100"),
        CheckConstraint("fat_per_100g BETWEEN 0 AND 100"),
        CheckConstraint("carbs_per_100g BETWEEN 0 AND 100"),
        CheckConstraint("cardinality(suitable_meal_types) > 0"),
        CheckConstraint("min_portion_g > 0"),
        CheckConstraint("portion_step_g > 0"),
        CheckConstraint("NOT is_vegan OR is_vegetarian", name="food_item_check"),
        CheckConstraint(
            "default_portion_g BETWEEN min_portion_g AND max_portion_g",
            name="food_item_check1",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    cals_per_100g: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    protein_per_100g: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    fat_per_100g: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    carbs_per_100g: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    diet_role: Mapped[DietRole] = mapped_column(DIET_ROLE)
    suitable_meal_types: Mapped[list[MealType]] = mapped_column(ARRAY(MEAL_TYPE))
    is_vegetarian: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_vegan: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    default_portion_g: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    min_portion_g: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    max_portion_g: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    portion_step_g: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    recognition_label: Mapped[str | None] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class FoodItemCategory(Base):
    __tablename__ = "food_item_category"
    __table_args__ = (Index("ix_food_item_category_category_id", "food_category_id"),)

    food_item_id: Mapped[int] = mapped_column(
        ForeignKey("food_item.id", ondelete="CASCADE"), primary_key=True
    )
    food_category_id: Mapped[int] = mapped_column(
        ForeignKey("food_category.id", ondelete="CASCADE"), primary_key=True
    )


class FoodItemAllergen(Base):
    __tablename__ = "food_item_allergen"
    __table_args__ = (Index("ix_food_item_allergen_allergen_id", "allergen_id"),)

    food_item_id: Mapped[int] = mapped_column(
        ForeignKey("food_item.id", ondelete="CASCADE"), primary_key=True
    )
    allergen_id: Mapped[int] = mapped_column(
        ForeignKey("allergen.id", ondelete="CASCADE"), primary_key=True
    )


class UserExcludedFood(Base):
    __tablename__ = "user_excluded_food"
    __table_args__ = (Index("ix_user_excluded_food_food_item_id", "food_item_id"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    food_item_id: Mapped[int] = mapped_column(
        ForeignKey("food_item.id", ondelete="CASCADE"), primary_key=True
    )


class DietPlan(Base):
    __tablename__ = "diet_plan"
    __table_args__ = (
        CheckConstraint("meals_per_day BETWEEN 3 AND 5"),
        CheckConstraint("daily_cal_goal > 0"),
        CheckConstraint("protein_goal >= 0"),
        CheckConstraint("fat_goal >= 0"),
        CheckConstraint("carbs_goal >= 0"),
        CheckConstraint("end_date >= start_date", name="diet_plan_check"),
        CheckConstraint(
            "status = 'draft' OR (start_date IS NOT NULL AND end_date IS NOT NULL)",
            name="diet_plan_check1",
        ),
        Index("ix_diet_plan_user_id", "user_id"),
        Index(
            "ux_diet_plan_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ux_diet_plan_one_draft",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(45))
    goal: Mapped[GoalType] = mapped_column(GOAL_TYPE)
    diet_type: Mapped[DietType] = mapped_column(DIET_TYPE, server_default=text("'omnivore'"))
    meals_per_day: Mapped[int] = mapped_column(SmallInteger)
    generated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    daily_cal_goal: Mapped[int] = mapped_column(Integer)
    protein_goal: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    fat_goal: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    carbs_goal: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    status: Mapped[PlanStatus] = mapped_column(PLAN_STATUS, server_default=text("'draft'"))
    dietary_restrictions: Mapped[str | None] = mapped_column(String(500))


class Meal(Base):
    __tablename__ = "meal"
    __table_args__ = (
        CheckConstraint("day_index BETWEEN 1 AND 7"),
        CheckConstraint("meal_order > 0"),
        CheckConstraint("planned_cals >= 0"),
        CheckConstraint("planned_protein >= 0"),
        CheckConstraint("planned_fat >= 0"),
        CheckConstraint("planned_carbs >= 0"),
        UniqueConstraint("diet_plan_id", "day_index", "meal_order"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    diet_plan_id: Mapped[int] = mapped_column(ForeignKey("diet_plan.id", ondelete="CASCADE"))
    day_index: Mapped[int] = mapped_column(SmallInteger)
    meal_type: Mapped[MealType] = mapped_column(MEAL_TYPE)
    meal_order: Mapped[int] = mapped_column(SmallInteger)
    planned_time: Mapped[time] = mapped_column(Time)
    planned_cals: Mapped[int] = mapped_column(Integer)
    planned_protein: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    planned_fat: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    planned_carbs: Mapped[Decimal] = mapped_column(Numeric(6, 2))


class MealFoodItem(Base):
    __tablename__ = "meal_food_item"
    __table_args__ = (
        CheckConstraint("grams > 0"),
        Index("ix_meal_food_item_food_item_id", "food_item_id"),
    )

    meal_id: Mapped[int] = mapped_column(
        ForeignKey("meal.id", ondelete="CASCADE"), primary_key=True
    )
    food_item_id: Mapped[int] = mapped_column(ForeignKey("food_item.id"), primary_key=True)
    grams: Mapped[Decimal] = mapped_column(Numeric(6, 1))


class NutritionLog(Base):
    __tablename__ = "nutrition_log"
    __table_args__ = (
        CheckConstraint("ai_confidence BETWEEN 0 AND 1"),
        CheckConstraint("actual_cals >= 0"),
        CheckConstraint("actual_protein >= 0"),
        CheckConstraint("actual_fat >= 0"),
        CheckConstraint("actual_carbs >= 0"),
        CheckConstraint("hunger_level_before BETWEEN 1 AND 10"),
        CheckConstraint("hunger_level_after BETWEEN 1 AND 10"),
        CheckConstraint(
            "(ai_confidence IS NULL) = (ai_was_edited IS NULL)",
            name="nutrition_log_check",
        ),
        Index("ix_nutrition_log_user_date", "user_id", "log_date"),
        Index("ix_nutrition_log_planned_meal_id", "planned_meal_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    client_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, server_default=text("gen_random_uuid()")
    )
    log_date: Mapped[date] = mapped_column(Date)
    meal_type: Mapped[MealType] = mapped_column(MEAL_TYPE)
    planned_meal_id: Mapped[int | None] = mapped_column(ForeignKey("meal.id", ondelete="SET NULL"))
    meal_photo_url: Mapped[str | None] = mapped_column(String(250))
    ai_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    ai_was_edited: Mapped[bool | None] = mapped_column(Boolean)
    actual_cals: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    actual_protein: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    actual_fat: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    actual_carbs: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    hunger_level_before: Mapped[int | None] = mapped_column(SmallInteger)
    hunger_level_after: Mapped[int | None] = mapped_column(SmallInteger)
    logged_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=NOW, server_onupdate=FetchedValue()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class NutritionLogFoodItem(Base):
    __tablename__ = "nutrition_log_food_item"
    __table_args__ = (
        CheckConstraint("grams > 0"),
        Index("ix_nutrition_log_food_item_food_item_id", "food_item_id"),
    )

    nutrition_log_id: Mapped[int] = mapped_column(
        ForeignKey("nutrition_log.id", ondelete="CASCADE"), primary_key=True
    )
    food_item_id: Mapped[int] = mapped_column(ForeignKey("food_item.id"), primary_key=True)
    grams: Mapped[Decimal] = mapped_column(Numeric(6, 1))
