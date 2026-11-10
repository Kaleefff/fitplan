"""Food library on PostgreSQL with the reference seed (B-09).

Uses the fixtures of the diet plan tests, which load the whole seed (DB-02, DB-04);
skipped without PostgreSQL.
"""

from contextlib import contextmanager

from sqlalchemy import text

from tests.db import test_diet_plans as diet
from tests.db.test_diet_plans import _rows, _sync_engine

# the fixtures of the diet plan tests: the seeded database and the app on it
api = diet.api
seeded = diet.seeded
migrated_db = diet.migrated_db
_close_sync_engine = diet._close_sync_engine


def _headers(api) -> dict[str, str]:
    return diet._login(api, profile=None)


def _id(name: str) -> int:
    return _rows("SELECT id FROM food_item WHERE name = :name", name=name)[0].id


@contextmanager
def _inactive(food_id: int):
    """The seed is loaded once per module, so the food is switched back afterwards."""
    with _sync_engine().begin() as db:
        db.execute(text("UPDATE food_item SET is_active = false WHERE id = :id"), {"id": food_id})
    try:
        yield
    finally:
        with _sync_engine().begin() as db:
            db.execute(
                text("UPDATE food_item SET is_active = true WHERE id = :id"), {"id": food_id}
            )


def test_list_is_paginated_by_name(api):
    headers = _headers(api)
    active = _rows("SELECT count(*) AS n FROM food_item WHERE is_active")[0].n
    expected = [
        r.name
        for r in _rows(
            'SELECT name FROM food_item WHERE is_active ORDER BY lower(name) COLLATE "C",'
            ' name COLLATE "C", id LIMIT 10'
        )
    ]

    first = api.get("/api/v1/foods?limit=5", headers=headers).json()
    second = api.get("/api/v1/foods?limit=5&offset=5", headers=headers).json()

    assert (first["total"], first["limit"], first["offset"]) == (active, 5, 0)
    assert (second["total"], second["offset"]) == (active, 5)
    assert [f["name"] for f in first["items"] + second["items"]] == expected


def test_detail_has_values_per_100_g_portions_and_links(api):
    headers = _headers(api)
    beef = _id("Lean ground beef, cooked")
    meat = _rows("SELECT id FROM food_category WHERE category_name = 'Meat'")[0].id

    food = api.get(f"/api/v1/foods/{beef}", headers=headers).json()

    assert food == {
        "id": beef,
        "name": "Lean ground beef, cooked",
        "cals_per_100g": 230.0,
        "protein_per_100g": 28.4,
        "fat_per_100g": 12.0,
        "carbs_per_100g": 0.0,
        "diet_role": "protein",
        "suitable_meal_types": ["lunch", "dinner"],
        "is_vegetarian": False,
        "is_vegan": False,
        "default_portion_g": 150.0,
        "min_portion_g": 50.0,
        "max_portion_g": 300.0,
        "portion_step_g": 10.0,
        "category_ids": [meat],
        "allergen_ids": [],
    }


def test_allergens_are_listed_by_id(api):
    headers = _headers(api)
    rows = _rows(
        "SELECT food_item_id, array_agg(allergen_id ORDER BY allergen_id) AS ids"
        " FROM food_item_allergen GROUP BY food_item_id ORDER BY count(*) DESC, food_item_id"
        " LIMIT 1"
    )
    food_id, allergen_ids = rows[0].food_item_id, list(rows[0].ids)

    food = api.get(f"/api/v1/foods/{food_id}", headers=headers).json()

    assert food["allergen_ids"] == allergen_ids
    assert set(allergen_ids) <= {
        a["id"] for a in api.get("/api/v1/allergens", headers=headers).json()
    }


def test_list_filters_by_name_and_category(api):
    headers = _headers(api)
    meat = _rows("SELECT id FROM food_category WHERE category_name = 'Meat'")[0].id

    found = api.get("/api/v1/foods?q=BEEF&limit=100", headers=headers).json()
    assert found["total"] == len(found["items"]) > 0
    assert all("beef" in f["name"].lower() for f in found["items"])

    page = api.get(f"/api/v1/foods?category_id={meat}&limit=100", headers=headers).json()
    assert page["total"] == len(page["items"]) > 0
    assert all(meat in f["category_ids"] for f in page["items"])


def test_inactive_foods_are_hidden(api):
    headers = _headers(api)
    beef = _id("Lean ground beef, cooked")
    before = api.get("/api/v1/foods?limit=1", headers=headers).json()["total"]

    with _inactive(beef):
        assert api.get(f"/api/v1/foods/{beef}", headers=headers).status_code == 404
        assert api.get("/api/v1/foods?limit=1", headers=headers).json()["total"] == before - 1
        found = api.get("/api/v1/foods?q=Lean ground beef", headers=headers).json()
        assert beef not in {f["id"] for f in found["items"]}


def test_categories_come_from_the_seed_ordered_by_name(api):
    headers = _headers(api)
    expected = [
        (r.id, r.category_name)
        for r in _rows(
            "SELECT id, category_name FROM food_category"
            ' ORDER BY lower(category_name) COLLATE "C", category_name COLLATE "C", id'
        )
    ]

    categories = api.get("/api/v1/food-categories", headers=headers).json()

    assert [(c["id"], c["category_name"]) for c in categories] == expected
    assert all(c["description"] for c in categories)


def test_excluded_foods_have_the_library_shape(api):
    headers = _headers(api)
    beef = _id("Lean ground beef, cooked")

    saved = api.put(
        "/api/v1/users/me/excluded-foods", json={"food_item_ids": [beef]}, headers=headers
    )

    assert saved.json() == [api.get(f"/api/v1/foods/{beef}", headers=headers).json()]


def test_unknown_food_is_404_and_a_token_is_required(api):
    headers = _headers(api)

    assert api.get("/api/v1/foods/999999", headers=headers).status_code == 404
    assert api.get("/api/v1/foods/0", headers=headers).status_code == 422
    assert api.get("/api/v1/foods").status_code == 401
    assert api.get("/api/v1/food-categories").status_code == 401
