"""Report export (S-04, FR-R6): CSV section,key,value with a BOM and a PDF that embeds a
Unicode font, both with the figures of the report JSON."""

import csv
import io

from pypdf import PdfReader

from app.services.report_export import report_rows, to_csv, to_pdf

REPORT = {
    "id": 12,
    "report_type": "weekly",
    "report_period_start": "2026-11-09",
    "report_period_end": "2026-11-15",
    "weight_difference": -0.6,
    "training_volume": 1430.0,
    "training_sessions_completed": 2,
    "training_sessions_planned": 3,
    "workout_compliance_pct": 77.8,
    "diet_compliance_pct": None,
    "avg_cals_daily": 2000,
    "key_lifts": [
        {
            "exercise_id": 7,
            "exercise_name": "Wyciskanie leżąc",
            "first_e1rm": 80.0,
            "best_e1rm": 81.67,
        }
    ],
    "estimated_goal_completion_date": "2027-01-01",
    "irregular_data": True,
    "is_auto": False,
    "generated_at": "2026-11-22T10:00:00Z",
}


def test_csv_has_a_bom_the_header_and_every_figure():
    data = to_csv(REPORT)

    assert data.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert rows[0] == ["section", "key", "value"]
    values = {(section, key): value for section, key, value in rows[1:]}
    assert values[("report", "report_type")] == "weekly"
    assert values[("metrics", "weight_difference")] == "-0.6"
    assert values[("metrics", "workout_compliance_pct")] == "77.8"
    assert values[("metrics", "diet_compliance_pct")] == ""  # null
    assert values[("key_lifts", "Wyciskanie leżąc.best_e1rm")] == "81.67"
    assert values[("goal", "irregular_data")] == "true"
    assert len(rows) - 1 == len(report_rows(REPORT))


def test_pdf_embeds_the_font_and_prints_polish_letters():
    data = to_pdf(REPORT)

    reader = PdfReader(io.BytesIO(data))
    text = "".join(page.extract_text() for page in reader.pages)
    assert "Wyciskanie leżąc" in text
    for figure in ("-0.6 kg", "1430.0 kg", "77.8 %", "2000 kcal", "80.0 / 81.67 kg", "2027-01-01"):
        assert figure in text, figure
    assert "no data" in text  # diet compliance is null
    fonts = [
        font.get_object() for page in reader.pages for font in page["/Resources"]["/Font"].values()
    ]
    descriptors = [f["/DescendantFonts"][0].get_object()["/FontDescriptor"] for f in fonts]
    assert descriptors and all("/FontFile2" in d for d in descriptors)  # embedded TrueType


def test_a_report_without_key_lifts_still_exports():
    empty = REPORT | {"key_lifts": [], "weight_difference": None}

    assert ("key_lifts", "Wyciskanie leżąc.first_e1rm", "80.0") not in report_rows(empty)
    assert "No key lifts" in PdfReader(io.BytesIO(to_pdf(empty))).pages[0].extract_text()
