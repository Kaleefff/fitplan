"""Food seed validation and coverage report (DB-04).

Checks database/seed/food_item.csv against the seed kcal rule of algorithms.md 0 and the
portion rule (minimum, maximum and default are multiples of the step), and writes
database/seed/food_coverage.md: totals, the foods closest to the kcal limit, and the
eligible foods per meal slot of algorithms.md 5.3 and diet type (5.2, no allergies).
A test also runs the diet generator over the seed for every goal, diet type and meals
per day; that is too slow for the report.

Run from backend/ after changing food_item.csv:
    uv run python -m app.db.food_check
Exits 1 when a food breaks a rule or a required meal slot is empty for a diet type.
"""

import csv
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

from app.db.seed import SEED_DIR, split_names
from app.domain.constants import MEAL_ROLES, SNACK_OPTIONAL_ROLE, DietRole, DietType, MealType
from app.domain.diet import FoodInfo

REPORT_NAME = "food_coverage.md"
KCAL_SHARE = Decimal("0.12")
KCAL_MIN = Decimal(15)
NEAR_LIMIT = 10
PORTIONS = ("min_portion_g", "max_portion_g", "default_portion_g")
SOURCES = {"FDC": "USDA FoodData Central", "SLV": "Swedish Food Agency (Livsmedelsverket)"}


def read_foods(seed_dir: Path = SEED_DIR) -> list[dict[str, str]]:
    with (seed_dir / "food_item.csv").open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def kcal_gap(row: dict[str, str]) -> tuple[Decimal, Decimal, Decimal]:
    """(4P + 4C + 9F, |kcal - that|, allowed difference) per algorithms.md 0."""
    kcal = Decimal(row["cals_per_100g"])
    protein, fat, carbs = (Decimal(row[f"{m}_per_100g"]) for m in ("protein", "fat", "carbs"))
    calc = 4 * protein + 4 * carbs + 9 * fat
    return calc, abs(kcal - calc), max(kcal * KCAL_SHARE, KCAL_MIN)


def kcal_errors(rows: list[dict[str, str]]) -> list[str]:
    errors = []
    for row in rows:
        calc, diff, allowed = kcal_gap(row)
        if diff > allowed:
            errors.append(
                f"{row['name']}: {row['cals_per_100g']} kcal but 4P + 4C + 9F = {calc}"
                f" (allowed difference {allowed:.1f})"
            )
    return errors


def portion_errors(rows: list[dict[str, str]]) -> list[str]:
    errors = []
    for row in rows:
        step = Decimal(row["portion_step_g"])
        off = [col for col in PORTIONS if Decimal(row[col]) % step]
        if off:
            errors.append(f"{row['name']}: {off} not a multiple of the step {step} g")
    return errors


def diet_types(row: dict[str, str]) -> set[DietType]:
    found = {DietType.OMNIVORE}
    if row["is_vegetarian"] == "true":
        found.add(DietType.VEGETARIAN)
    if row["is_vegan"] == "true":
        found.add(DietType.VEGAN)
    return found


def slots() -> list[tuple[MealType, tuple[DietRole, ...], bool]]:
    """(meal type, roles that fill the slot, required) per algorithms.md 5.3."""
    found = [(meal, roles, True) for meal, slot_roles in MEAL_ROLES.items() for roles in slot_roles]
    found += [(meal, (DietRole.DISH,), False) for meal in (MealType.LUNCH, MealType.DINNER)]
    found.append((MealType.SNACK, (SNACK_OPTIONAL_ROLE,), False))
    return found


def eligible(rows, meal: MealType, roles: tuple[DietRole, ...], diet: DietType) -> int:
    return sum(
        1
        for row in rows
        if row["diet_role"] in roles
        and meal in split_names(row["suitable_meal_types"])
        and diet in diet_types(row)
    )


def coverage_gaps(rows: list[dict[str, str]]) -> list[str]:
    return [
        f"{meal.value} {' or '.join(roles)} ({diet.value})"
        for meal, roles, required in slots()
        if required
        for diet in DietType
        if not eligible(rows, meal, roles, diet)
    ]


def food_infos(rows: list[dict[str, str]]) -> list[FoodInfo]:
    """The seed as the diet generator sees it; ids follow the file order, as on a fresh load."""
    return [
        FoodInfo(
            id=i,
            diet_role=DietRole(row["diet_role"]),
            suitable_meal_types=frozenset(
                MealType(m) for m in split_names(row["suitable_meal_types"])
            ),
            per_100g=tuple(
                float(row[f"{m}_per_100g"]) for m in ("cals", "protein", "fat", "carbs")
            ),
            min_portion_g=int(Decimal(row["min_portion_g"])),
            max_portion_g=int(Decimal(row["max_portion_g"])),
            portion_step_g=int(Decimal(row["portion_step_g"])),
            is_vegetarian=row["is_vegetarian"] == "true",
            is_vegan=row["is_vegan"] == "true",
        )
        for i, row in enumerate(rows, start=1)
    ]


def counts(rows, column: str) -> list[str]:
    found = Counter(split_names(row[column])[0] for row in rows)
    return [f"| {key} | {n} |" for key, n in sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))]


def report(seed_dir: Path = SEED_DIR) -> str:
    rows = read_foods(seed_dir)
    sources = Counter(row["source"].split(":")[0] for row in rows)
    near = sorted(rows, key=lambda r: kcal_gap(r)[1] / kcal_gap(r)[2], reverse=True)[:NEAR_LIMIT]
    errors = kcal_errors(rows) + portion_errors(rows)
    gaps = coverage_gaps(rows)

    lines = [
        "# Food coverage",
        "",
        "Generated by `uv run python -m app.db.food_check` (run from `backend/`) from",
        "`food_item.csv`; do not edit by hand.",
        f"{len(rows)} foods: "
        + ", ".join(f"{n} from {SOURCES[s]}" for s, n in sorted(sources.items()))
        + ".",
        "",
        "## Checks",
        "",
        f"- Seed kcal rule (algorithms.md 0): {len(rows) - len(kcal_errors(rows))} of"
        f" {len(rows)} foods pass.",
        f"- Portions (minimum, maximum and default are multiples of the step):"
        f" {len(rows) - len(portion_errors(rows))} of {len(rows)} foods pass.",
        f"- Required meal slots with no food for a diet type: {', '.join(gaps) or 'none'}.",
        *[f"- Error: {e}" for e in errors],
        "",
        "Closest to the kcal limit (difference / allowed difference), mostly dried fruit: FDC",
        "carbohydrate by difference includes fibre, which 4 kcal/g overcounts.",
        "",
        "| Food | kcal | 4P + 4C + 9F | Share of the allowed difference |",
        "| --- | ---: | ---: | ---: |",
        *[
            f"| {r['name']} | {r['cals_per_100g']} | {kcal_gap(r)[0]:.1f} |"
            f" {kcal_gap(r)[1] / kcal_gap(r)[2]:.0%} |"
            for r in near
        ],
        "",
        "## Eligible foods per meal slot (algorithms.md 5.2, 5.3)",
        "",
        "Active foods of the slot's roles whose meal types include the meal, for a user without"
        " allergies or excluded foods. Optional slots: a dish may replace protein and carb at"
        " lunch and dinner; fat is optional at a snack.",
        "",
        "| Meal | Slot | " + " | ".join(d.value for d in DietType) + " |",
        "| --- | --- |" + " ---: |" * len(DietType),
    ]
    for meal, roles, required in slots():
        slot = " or ".join(roles) + ("" if required else " (optional)")
        cells = " | ".join(str(eligible(rows, meal, roles, d)) for d in DietType)
        lines.append(f"| {meal.value} | {slot} | {cells} |")

    lines += [
        "",
        "## Foods per role",
        "",
        "`other` foods (sweets, drinks, sauces, soups, fast food, dry weights) are in the"
        " library and logs but never planned.",
        "",
        "| Role | Foods |",
        "| --- | ---: |",
        *counts(rows, "diet_role"),
        "",
        "## Foods per category",
        "",
        "| Category | Foods |",
        "| --- | ---: |",
        *counts(rows, "categories"),
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    path = SEED_DIR / REPORT_NAME
    path.write_text(report(), encoding="utf-8", newline="\n")
    print(f"wrote {path}")
    rows = read_foods()
    problems = kcal_errors(rows) + portion_errors(rows) + coverage_gaps(rows)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
