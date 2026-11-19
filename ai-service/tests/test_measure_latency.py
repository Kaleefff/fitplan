"""A-01: scripts/measure_latency.py without a network (httpx.MockTransport)."""

import json

import httpx
import pytest

from scripts.measure_latency import (
    DEFAULT_CSV,
    Result,
    find_photos,
    load_labels,
    main,
    measure,
    p95,
    summarise,
)


def test_labels_are_lower_names_without_duplicates_in_file_order(tmp_path):
    path = tmp_path / "food_item.csv"
    path.write_text(
        'name,cals_per_100g\n"Basmati Rice, cooked",130\nŻurek,50\nBASMATI RICE, COOKED,1\n',
        encoding="utf-8",
    )
    # the last line has an unquoted comma: its name is "BASMATI RICE"
    assert load_labels(path) == ["basmati rice, cooked", "żurek", "basmati rice"]


def test_seed_csv_gives_one_label_per_food():
    labels = load_labels(DEFAULT_CSV)
    assert len(labels) == 504
    assert all(label == label.lower() and 0 < len(label) <= 100 for label in labels)


def test_photos_are_the_accepted_files_in_name_order(tmp_path):
    for name in ["b.JPG", "a.webp", "c.png", "d.jpeg", "notes.txt", "e.gif"]:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "f.jpg").mkdir()

    assert [p.name for p in find_photos(tmp_path)] == ["a.webp", "b.JPG", "c.png", "d.jpeg"]


@pytest.mark.parametrize(
    ("values", "expected"),
    [([3.0], 3.0), ([1.0, 2.0, 3.0], 3.0), ([float(i) for i in range(1, 21)], 19.0)],
)
def test_p95_is_nearest_rank(values, expected):
    assert p95(values) == expected


def test_summary_uses_answers_only_but_counts_every_slow_request():
    results = [
        Result("a", 200, 2.0),
        Result("b", 200, 4.0),
        Result("c", 200, 9.0),
        Result("d", 504, 10.5),
        Result("e", 400, 0.1),
    ]
    summary = summarise(results)

    assert (summary.answered, summary.total) == (3, 5)
    assert summary.median == 4.0
    assert summary.mean == 5.0
    assert summary.p95 == 9.0
    assert summary.max == 9.0
    assert summary.over_nfr == 1


def test_summary_without_answers_has_no_times():
    summary = summarise([Result("a", 504, 7.1)])
    assert (summary.median, summary.mean, summary.p95, summary.max) == (None,) * 4


ANSWER = {
    "model": {"name": "gemini-test", "version": "gemini-test-001"},
    "items": [{"label": "żurek", "confidence": 0.9, "grams": 300, "alternatives": []}],
}


def test_measure_sends_each_photo_with_the_labels(tmp_path, capsys):
    (tmp_path / "soup.jpg").write_bytes(b"jpeg-bytes")
    (tmp_path / "rice.png").write_bytes(b"png-bytes")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        seen.append(body)
        if b"rice.png" in body:
            return httpx.Response(504, json={"code": "ai_unavailable", "message": "slow"})
        return httpx.Response(200, json=ANSWER)

    client = httpx.Client(base_url="http://ai", transport=httpx.MockTransport(handler))
    results = measure(client, find_photos(tmp_path), ["żurek", "rice"])

    assert [(r.photo, r.status) for r in results] == [("rice.png", 504), ("soup.jpg", 200)]
    assert b"Content-Type: image/png" in seen[0] and b"png-bytes" in seen[0]
    assert b"Content-Type: image/jpeg" in seen[1] and b"jpeg-bytes" in seen[1]
    assert json.dumps(["żurek", "rice"], ensure_ascii=False).encode() in seen[1]
    out = capsys.readouterr().out
    assert "ai_unavailable: slow" in out
    assert "żurek 0.90 300 g" in out


def test_main_refuses_more_photos_than_the_limit_before_any_request(tmp_path, capsys):
    for i in range(3):
        (tmp_path / f"{i}.jpg").write_bytes(b"x")

    with pytest.raises(SystemExit) as raised:
        main([str(tmp_path), "--limit", "2", "--url", "http://127.0.0.1:9"])
    assert raised.value.code == 2
    assert "more than --limit 2" in capsys.readouterr().err
