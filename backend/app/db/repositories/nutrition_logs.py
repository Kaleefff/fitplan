"""Nutrition logs and the daily summary (DB-09; FR-A3, FR-R2 data; api-rules.md "Logs").

Macros come from the food database: grams to 0.1, each item's kcal and macros half up
to 2 places, the log's totals the sum of the rounded items. One `SqlNutritionLogStore`
lives in one transaction (`SqlNutritionLogUnitOfWork`). Every query filters by the
user; deleted logs are never returned.
"""

import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import MealType as DbMealType
from app.db.enums import PlanStatus
from app.db.models import DietPlan, FoodItem, Meal, NutritionLog, NutritionLogFoodItem
from app.domain.constants import MealType
from app.domain.rounding import round_half_up

CLIENT_UUID_CONSTRAINT = "nutrition_log_user_id_client_uuid_key"
MAX_LOG_TOTAL = Decimal("9999.99")  # nutrition_log.actual_* are NUMERIC(6, 2)
PATCH_FIELDS = frozenset(
    {"log_date", "meal_type", "planned_meal_id", "hunger_level_before", "hunger_level_after"}
)


# ---------------------------------------------------------------- errors


class ClientUuidDeletedError(Exception):
    """The client_uuid belongs to a deleted log of this user (409)."""


class ItemError(Exception):
    """An item of the request is invalid; `index` is its position in `items`."""

    def __init__(self, index: int) -> None:
        super().__init__(index)
        self.index = index


class DuplicateFoodError(ItemError):
    """The food of items[index] is already in the log (422 `duplicate`)."""


class UnknownFoodError(ItemError):
    """items[index] names a food that does not exist or is inactive."""


class ZeroGramsError(ItemError):
    """items[index] has grams that round to 0.0."""


class LogTooLargeError(Exception):
    """The log is above 9999.99 kcal, or a macro total above 9999.99 g (422 `too_large`)."""


class UnknownPlannedMealError(Exception):
    """planned_meal_id is not a meal of one of the user's diet plans."""


# ---------------------------------------------------------------- data


@dataclass(frozen=True)
class ItemIn:
    food_item_id: int
    grams: Decimal


@dataclass(frozen=True)
class NutritionLogIn:
    client_uuid: uuid.UUID | None
    log_date: date
    meal_type: MealType
    planned_meal_id: int | None
    hunger_level_before: int | None
    hunger_level_after: int | None
    items: tuple[ItemIn, ...]


@dataclass(frozen=True)
class Macros:
    kcal: Decimal
    protein: Decimal
    fat: Decimal
    carbs: Decimal

    def __add__(self, other: "Macros") -> "Macros":
        return Macros(
            self.kcal + other.kcal,
            self.protein + other.protein,
            self.fat + other.fat,
            self.carbs + other.carbs,
        )

    def __sub__(self, other: "Macros") -> "Macros":
        return Macros(
            self.kcal - other.kcal,
            self.protein - other.protein,
            self.fat - other.fat,
            self.carbs - other.carbs,
        )


ZERO = Macros(Decimal(0), Decimal(0), Decimal(0), Decimal(0))


@dataclass(frozen=True)
class LogItemView:
    food_item_id: int
    name: str
    grams: Decimal


@dataclass(frozen=True)
class NutritionLogView:
    id: int
    user_id: int
    client_uuid: uuid.UUID
    log_date: date
    meal_type: MealType
    planned_meal_id: int | None
    meal_photo_url: str | None
    ai_confidence: Decimal | None
    ai_was_edited: bool | None
    actual_cals: Decimal
    actual_protein: Decimal
    actual_fat: Decimal
    actual_carbs: Decimal
    hunger_level_before: int | None
    hunger_level_after: int | None
    logged_at: datetime
    items: tuple[LogItemView, ...]

    @property
    def totals(self) -> Macros:
        return Macros(self.actual_cals, self.actual_protein, self.actual_fat, self.actual_carbs)


@dataclass(frozen=True)
class DailySummaryView:
    date: date
    targets: Macros | None  # of the active diet plan
    totals: Macros
    remaining: Macros | None  # targets - totals, may be negative
    avg_hunger_before: Decimal | None  # empty values ignored, not rounded
    avg_hunger_after: Decimal | None
    logs: tuple[NutritionLogView, ...]


def item_macros(food: FoodItem, grams: Decimal) -> Macros:
    """`grams` already at 0.1 g; each value half up to 2 places."""

    def part(per_100g: Decimal) -> Decimal:
        return round_half_up(grams * per_100g / 100, 2)

    return Macros(
        part(food.cals_per_100g),
        part(food.protein_per_100g),
        part(food.fat_per_100g),
        part(food.carbs_per_100g),
    )


# ---------------------------------------------------------------- store


class SqlNutritionLogStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: int, log: NutritionLogIn) -> NutritionLogView:
        """A repeated client_uuid returns the first log; nothing is stored twice."""
        if log.client_uuid is not None:
            existing = await self._by_client_uuid(user_id, log.client_uuid)
            if existing is not None:
                return await self._replay(existing)
        grams, totals = await self._priced(log.items)
        await self._check_planned_meal(user_id, log.planned_meal_id)
        row = NutritionLog(
            user_id=user_id,
            log_date=log.log_date,
            meal_type=DbMealType(log.meal_type.value),
            planned_meal_id=log.planned_meal_id,
            hunger_level_before=log.hunger_level_before,
            hunger_level_after=log.hunger_level_after,
        )
        _set_totals(row, totals)
        if log.client_uuid is not None:
            row.client_uuid = log.client_uuid
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig.diag, "constraint_name", None) != CLIENT_UUID_CONSTRAINT:
                raise
            # a concurrent create with the same client_uuid committed first
            return await self._replay(await self._by_client_uuid(user_id, log.client_uuid))
        await self._insert_items(row.id, grams)
        return await self.get(user_id, row.id)

    async def get(self, user_id: int, log_id: int) -> NutritionLogView | None:
        row = await self._session.scalar(
            select(NutritionLog)
            .where(
                NutritionLog.id == log_id,
                NutritionLog.user_id == user_id,
                NutritionLog.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        return None if row is None else (await self._views([row]))[0]

    async def list_logs(
        self, user_id: int, date_from: date | None, date_to: date | None, limit: int, offset: int
    ) -> tuple[int, list[NutritionLogView]]:
        conditions = [NutritionLog.user_id == user_id, NutritionLog.deleted_at.is_(None)]
        if date_from is not None:
            conditions.append(NutritionLog.log_date >= date_from)
        if date_to is not None:
            conditions.append(NutritionLog.log_date <= date_to)
        total = await self._session.scalar(select(func.count()).where(*conditions))
        rows = await self._session.scalars(
            select(NutritionLog)
            .where(*conditions)
            .order_by(NutritionLog.log_date.desc(), NutritionLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return total, await self._views(list(rows))

    async def update(
        self,
        user_id: int,
        log_id: int,
        changes: Mapping[str, object],
        items: Sequence[ItemIn] | None,
    ) -> NutritionLogView | None:
        """PATCH: the fields in `changes`; `items` (when given) replace all items."""
        unknown = set(changes) - PATCH_FIELDS
        if unknown:
            raise ValueError(f"not a nutrition log field: {sorted(unknown)}")
        row = await self._session.scalar(
            select(NutritionLog)
            .where(
                NutritionLog.id == log_id,
                NutritionLog.user_id == user_id,
                NutritionLog.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if row is None:
            return None
        if changes.get("planned_meal_id") is not None:
            await self._check_planned_meal(user_id, changes["planned_meal_id"])
        if items is not None:
            grams, totals = await self._priced(items)
            await self._session.execute(
                delete(NutritionLogFoodItem).where(NutritionLogFoodItem.nutrition_log_id == log_id)
            )
            await self._insert_items(log_id, grams)
            _set_totals(row, totals)
        for field, value in changes.items():
            setattr(row, field, DbMealType(value.value) if field == "meal_type" else value)
        await self._session.flush()
        return await self.get(user_id, log_id)

    async def soft_delete(self, user_id: int, log_id: int) -> bool:
        result = await self._session.execute(
            update(NutritionLog)
            .where(
                NutritionLog.id == log_id,
                NutritionLog.user_id == user_id,
                NutritionLog.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        return result.rowcount == 1

    async def daily_summary(self, user_id: int, day: date) -> DailySummaryView:
        rows = await self._session.scalars(
            select(NutritionLog)
            .where(
                NutritionLog.user_id == user_id,
                NutritionLog.log_date == day,
                NutritionLog.deleted_at.is_(None),
            )
            .order_by(NutritionLog.id)
        )
        logs = await self._views(list(rows))
        totals = sum((log.totals for log in logs), ZERO)
        plan = (
            await self._session.execute(
                select(
                    DietPlan.daily_cal_goal,
                    DietPlan.protein_goal,
                    DietPlan.fat_goal,
                    DietPlan.carbs_goal,
                ).where(DietPlan.user_id == user_id, DietPlan.status == PlanStatus.ACTIVE)
            )
        ).first()
        targets = None if plan is None else Macros(Decimal(plan[0]), plan[1], plan[2], plan[3])
        return DailySummaryView(
            date=day,
            targets=targets,
            totals=totals,
            remaining=None if targets is None else targets - totals,
            avg_hunger_before=_average(log.hunger_level_before for log in logs),
            avg_hunger_after=_average(log.hunger_level_after for log in logs),
            logs=tuple(logs),
        )

    # ------------------------------------------------------------ helpers

    async def _by_client_uuid(self, user_id: int, client_uuid: uuid.UUID) -> NutritionLog | None:
        return await self._session.scalar(
            select(NutritionLog)
            .where(NutritionLog.user_id == user_id, NutritionLog.client_uuid == client_uuid)
            .execution_options(populate_existing=True)
        )

    async def _replay(self, existing: NutritionLog) -> NutritionLogView:
        if existing.deleted_at is not None:
            raise ClientUuidDeletedError
        return (await self._views([existing]))[0]

    async def _priced(self, items: Sequence[ItemIn]) -> tuple[list[tuple[int, Decimal]], Macros]:
        """Grams at 0.1 g per food and the log's totals; raises the first invalid item."""
        seen: set[int] = set()
        for i, item in enumerate(items):
            if item.food_item_id in seen:
                raise DuplicateFoodError(i)
            seen.add(item.food_item_id)
        foods = {
            food.id: food
            for food in await self._session.scalars(
                select(FoodItem).where(FoodItem.id.in_(seen), FoodItem.is_active)
            )
        }
        grams: list[tuple[int, Decimal]] = []
        totals = ZERO
        for i, item in enumerate(items):
            food = foods.get(item.food_item_id)
            if food is None:
                raise UnknownFoodError(i)
            quantised = round_half_up(item.grams, 1)
            if quantised <= 0:
                raise ZeroGramsError(i)
            grams.append((food.id, quantised))
            totals += item_macros(food, quantised)
        if max(totals.kcal, totals.protein, totals.fat, totals.carbs) > MAX_LOG_TOTAL:
            raise LogTooLargeError
        return grams, totals

    async def _check_planned_meal(self, user_id: int, meal_id: int | None) -> None:
        if meal_id is None:
            return
        found = await self._session.scalar(
            select(Meal.id)
            .join(DietPlan, DietPlan.id == Meal.diet_plan_id)
            .where(Meal.id == meal_id, DietPlan.user_id == user_id)
        )
        if found is None:
            raise UnknownPlannedMealError

    async def _insert_items(self, log_id: int, grams: list[tuple[int, Decimal]]) -> None:
        self._session.add_all(
            NutritionLogFoodItem(nutrition_log_id=log_id, food_item_id=food_id, grams=g)
            for food_id, g in grams
        )
        await self._session.flush()

    async def _views(self, rows: list[NutritionLog]) -> list[NutritionLogView]:
        """One query for the items of all `rows`."""
        items: dict[int, list[LogItemView]] = {row.id: [] for row in rows}
        if rows:
            for log_id, food_id, name, grams in await self._session.execute(
                select(
                    NutritionLogFoodItem.nutrition_log_id,
                    NutritionLogFoodItem.food_item_id,
                    FoodItem.name,
                    NutritionLogFoodItem.grams,
                )
                .join(FoodItem, FoodItem.id == NutritionLogFoodItem.food_item_id)
                .where(NutritionLogFoodItem.nutrition_log_id.in_(items))
                .order_by(NutritionLogFoodItem.nutrition_log_id, NutritionLogFoodItem.food_item_id)
            ):
                items[log_id].append(LogItemView(food_id, name, grams))
        return [
            NutritionLogView(
                id=row.id,
                user_id=row.user_id,
                client_uuid=row.client_uuid,
                log_date=row.log_date,
                meal_type=MealType(row.meal_type.value),
                planned_meal_id=row.planned_meal_id,
                meal_photo_url=row.meal_photo_url,
                ai_confidence=row.ai_confidence,
                ai_was_edited=row.ai_was_edited,
                actual_cals=row.actual_cals,
                actual_protein=row.actual_protein,
                actual_fat=row.actual_fat,
                actual_carbs=row.actual_carbs,
                hunger_level_before=row.hunger_level_before,
                hunger_level_after=row.hunger_level_after,
                logged_at=row.logged_at,
                items=tuple(items[row.id]),
            )
            for row in rows
        ]


def _set_totals(row: NutritionLog, totals: Macros) -> None:
    row.actual_cals = totals.kcal
    row.actual_protein = totals.protein
    row.actual_fat = totals.fat
    row.actual_carbs = totals.carbs


def _average(values) -> Decimal | None:
    given = [v for v in values if v is not None]
    return None if not given else Decimal(sum(given)) / len(given)


class SqlNutritionLogUnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SqlNutritionLogStore]:
        async with self._sessions.begin() as session:
            yield SqlNutritionLogStore(session)
