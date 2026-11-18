"""Meta CSV captions and file-wide date conventions."""

import csv
from datetime import UTC, datetime

import pytest

from creatorvault.insights.meta import infer_month_first, load_table, parse_insights


def test_quoted_multiline_captions_preserve_rows_and_metrics(tmp_path):
    path = tmp_path / "insights.csv"
    caption = 'An astronaut says "hello".\nA second line, with a comma.'
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Publish time", "Description", "Permalink", "Reach", "Likes"])
        writer.writerow(["08/25/2026 09:30", caption, "https://example.com/1", 100, 12])
        writer.writerow(["01/02/2026 09:30", "Another post", "https://example.com/2", 200, 25])
    _, rows = load_table(path)
    assert len(rows) == 2 and rows[0][1] == caption
    parsed = parse_insights([path], UTC)
    assert parsed[0]["description"] == caption
    assert parsed[0]["metrics"]["reach"] == 100
    assert parsed[1]["metrics"]["likes"] == 25
    assert parsed[1]["publish_time"] == datetime(2026, 1, 2, 9, 30, tzinfo=UTC)


def test_day_first_dates_remain_consistent(tmp_path):
    path = tmp_path / "insights.csv"
    path.write_text("Publish time,Reach\n25/08/2026 09:30,100\n01/02/2026 09:30,200\n")
    parsed = parse_insights([path], UTC)
    assert parsed[1]["publish_time"] == datetime(2026, 2, 1, 9, 30, tzinfo=UTC)


def test_conflicting_date_conventions_fail_clearly():
    with pytest.raises(SystemExit, match="mixed"):
        infer_month_first(["08/25/2026", "25/08/2026"])
    assert infer_month_first(["2026-08-25", "01/02/2026"]) is False
