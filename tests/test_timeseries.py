import csv
import io
import json

from ecos_mcp.timeseries import (
    apply_transform,
    drop_unchanged,
    format_timeseries,
    to_number,
)


def _row(time, value, code="0", name="총지수", unit="2020=100", **extra):
    return {
        "STAT_CODE": "901Y009",
        "STAT_NAME": "소비자물가지수",
        "ITEM_CODE1": code,
        "ITEM_NAME1": name,
        "UNIT_NAME": unit,
        "TIME": time,
        "DATA_VALUE": value,
        **extra,
    }


def test_to_number():
    assert to_number("3") == 3
    assert to_number("3.50") == 3.5
    assert to_number("1,234.5") == 1234.5
    assert to_number("") is None
    assert to_number(None) is None
    assert to_number("-") == "-"


def test_compact_groups_series_with_their_own_units():
    rows = [
        _row("202401", "100"),
        _row("202401", "5.5", code="A", name="식료품", unit="%"),
        _row("202402", "101"),
        _row("202402", "5.6", code="A", name="식료품", unit="%"),
    ]
    text = format_timeseries({"rows": rows, "total_count": 4})
    assert "\n" not in text and ": " not in text  # no pretty-printing whitespace
    out = json.loads(text)
    assert out["columns"] == ["time", "value"]
    assert [(s["item"], s["unit"]) for s in out["series"]] == [("총지수", "2020=100"), ("식료품", "%")]
    assert out["series"][0]["data"] == [["202401", 100], ["202402", 101]]


def test_csv_escapes_commas_and_quotes():
    rows = [_row("202401", "1", name='국내총생산(실질, "계절조정")')]
    text = format_timeseries({"rows": rows, "total_count": 1, "note": "참고"}, "csv")
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    parsed = list(csv.reader(io.StringIO("\n".join(lines))))
    assert parsed[0] == ["TIME", "ITEM_CODE", "ITEM", "VALUE", "UNIT"]
    assert parsed[1][2] == '국내총생산(실질, "계절조정")'
    assert "# note: 참고" in text


def test_json_format_keeps_raw_rows():
    rows = [_row("202401", "1")]
    out = json.loads(format_timeseries({"rows": rows, "total_count": 1}, "json"))
    assert out["data"] == rows


def test_yoy_transform_matches_by_period():
    rows = [_row(f"2023{m:02d}", "100") for m in range(1, 13)] + [_row("202401", "103")]
    apply_transform(rows, "M", "yoy")
    assert rows[-1]["yoy_pct"] == 3.0
    assert rows[0]["yoy_pct"] is None


def test_pop_transform_uses_previous_observation():
    rows = [_row("20240101", "100"), _row("20240103", "110")]
    apply_transform(rows, "D", "pop")
    assert [r["pop_pct"] for r in rows] == [None, 10.0]


def test_drop_unchanged_keeps_changes_and_endpoints():
    values = ["3.5", "3.5", "3.25", "3.25", "3.25"]
    rows = [_row(f"2024010{i + 1}", v) for i, v in enumerate(values)]
    kept = drop_unchanged(rows)
    assert [r["TIME"] for r in kept] == ["20240101", "20240103", "20240105"]
