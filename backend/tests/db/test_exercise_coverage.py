"""DB-03: the committed coverage report is current and every goal's main groups have an
eligible exercise for every level and equipment. Needs no database."""

from app.db.exercise_coverage import REPORT_NAME, gaps, read_items, report
from app.db.seed import SEED_DIR


def test_committed_report_is_current():
    committed = (SEED_DIR / REPORT_NAME).read_text(encoding="utf-8")

    assert committed == report(), "run: uv run python -m app.db.exercise_coverage"


def test_no_goal_has_a_gap():
    found = {goal: cells for goal, cells in gaps(read_items(SEED_DIR)).items() if cells}

    assert found == {}
