"""Report export to CSV and PDF (S-04; FR-R6; api-rules.md "Reports and notifications").

Both files are built from the report exactly as `GET /reports/{id}` returns it (the JSON
values), so they hold the figures shown on screen. CSV: `section,key,value`, UTF-8 with a
BOM so that spreadsheet apps read Polish letters. PDF: DejaVu Sans is embedded, so every
Polish letter of an exercise name prints.
"""

import csv
import io
from pathlib import Path

from fpdf import FPDF

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
CSV_HEADER = ("section", "key", "value")

REPORT_KEYS = ("id", "report_type", "report_period_start", "report_period_end", "generated_at")
METRIC_KEYS = (
    "weight_difference",
    "training_volume",
    "training_sessions_completed",
    "training_sessions_planned",
    "workout_compliance_pct",
    "diet_compliance_pct",
    "avg_cals_daily",
)
GOAL_KEYS = ("estimated_goal_completion_date", "irregular_data")

# PDF labels and units of the metrics
METRIC_LABELS = {
    "weight_difference": ("Weight change", "kg"),
    "training_volume": ("Training volume", "kg"),
    "training_sessions_completed": ("Workouts done", ""),
    "training_sessions_planned": ("Workouts planned", ""),
    "workout_compliance_pct": ("Workout compliance", "%"),
    "diet_compliance_pct": ("Diet compliance", "%"),
    "avg_cals_daily": ("Average calories per day", "kcal"),
}


def _text(value: object) -> str:
    """JSON value as text: null is empty, booleans lower case, numbers as in JSON."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def report_rows(report: dict) -> list[tuple[str, str, str]]:
    """`report` is the JSON of `GET /reports/{id}` (`ReportOut.model_dump(mode="json")`)."""
    rows = [("report", key, _text(report[key])) for key in REPORT_KEYS]
    rows += [("metrics", key, _text(report[key])) for key in METRIC_KEYS]
    for lift in report["key_lifts"]:
        name = lift["exercise_name"]
        rows.append(("key_lifts", f"{name}.first_e1rm", _text(lift["first_e1rm"])))
        rows.append(("key_lifts", f"{name}.best_e1rm", _text(lift["best_e1rm"])))
    rows += [("goal", key, _text(report[key])) for key in GOAL_KEYS]
    return rows


def to_csv(report: dict) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    writer.writerows(report_rows(report))
    return out.getvalue().encode("utf-8-sig")


def _shown(value: object, unit: str = "") -> str:
    if value is None:
        return "no data"
    return f"{_text(value)} {unit}".strip()


def to_pdf(report: dict) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_title(f"FitPlan Pro report {report['id']}")
    pdf.add_font("DejaVu", "", FONT_DIR / "DejaVuSans.ttf")
    pdf.add_font("DejaVu", "B", FONT_DIR / "DejaVuSans-Bold.ttf")
    pdf.add_page()
    width = pdf.epw

    pdf.set_font("DejaVu", "B", 18)
    pdf.cell(width, 10, "FitPlan Pro: progress report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 11)
    period = f"{report['report_period_start']} to {report['report_period_end']}"
    pdf.cell(
        width,
        7,
        f"{report['report_type'].capitalize()} report, {period}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.cell(width, 7, f"Generated {report['generated_at']}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    def section(title: str, rows: list[tuple[str, str]]) -> None:
        pdf.set_font("DejaVu", "B", 13)
        pdf.cell(width, 9, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("DejaVu", "", 11)
        with pdf.table(col_widths=(60, 40), text_align=("LEFT", "RIGHT")) as table:
            for label, value in rows:
                table.row((label, value))
        pdf.ln(3)

    section(
        "Metrics",
        [(label, _shown(report[key], unit)) for key, (label, unit) in METRIC_LABELS.items()],
    )
    lifts = [("Exercise", "First / best e1RM")] + [
        (lift["exercise_name"], f"{_text(lift['first_e1rm'])} / {_text(lift['best_e1rm'])} kg")
        for lift in report["key_lifts"]
    ]
    section("Key lifts", lifts if report["key_lifts"] else [("No key lifts", "")])
    section(
        "Goal",
        [
            ("Estimated goal date", _shown(report["estimated_goal_completion_date"])),
            ("Irregular data", "yes" if report["irregular_data"] else "no"),
        ],
    )
    return bytes(pdf.output())
