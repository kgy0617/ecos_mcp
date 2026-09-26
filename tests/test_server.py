import json

import pytest
from mcp import Client

import ecos_mcp.client as client_module
from conftest import TEST_KEY, monthly
from ecos_mcp.server import mcp

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setattr(client_module, "ECOS_API_KEY", TEST_KEY)


async def call(name, args):
    async with Client(mcp) as c:
        result = await c.call_tool(name, args)
    return result.is_error, result.content[0].text


async def test_tools_are_read_only_without_duplicated_output():
    async with Client(mcp) as c:
        tools = (await c.list_tools()).tools
        prompts = (await c.list_prompts()).prompts
    assert len(tools) == 7
    for tool in tools:
        assert tool.annotations.read_only_hint is True
        assert tool.output_schema is None
    local = next(t for t in tools if t.name == "search_statistic_tables")
    assert local.annotations.open_world_hint is False
    assert {p.name for p in prompts} == {"macro-economic-briefing", "analyze-economic-trend"}


async def test_base_rate_returns_only_changes(fake_ecos):
    values = {f"202401{d:02d}": 3.5 for d in range(1, 11)}
    values.update({f"202401{d:02d}": 3.25 for d in range(11, 21)})
    fake_ecos.add_series("722Y001", "D", values, item_code1="0101000", item_name1="기준금리", unit="연%")
    is_error, text = await call(
        "get_popular_statistic",
        {"indicator": "기준금리", "start_date": "20240101", "end_date": "20240120"},
    )
    assert not is_error
    out = json.loads(text)
    assert out["changes_only"] is True
    assert out["series"][0]["data"] == [["20240101", 3.5], ["20240111", 3.25], ["20240120", 3.25]]


async def test_inflation_preset_computes_yoy(fake_ecos):
    fake_ecos.add_series("901Y009", "M", monthly(2023, [100] * 12 + [102] * 12))
    is_error, text = await call(
        "get_popular_statistic",
        {"indicator": "물가상승률", "start_date": "202401", "end_date": "202403"},
    )
    assert not is_error
    out = json.loads(text)
    assert out["columns"] == ["time", "value", "yoy_pct"]
    assert out["series"][0]["data"] == [["202401", 102, 2.0], ["202402", 102, 2.0], ["202403", 102, 2.0]]
    assert out["count"] == 3


async def test_truncated_yoy_fetches_base_year(fake_ecos, monkeypatch):
    monkeypatch.setattr(client_module, "ECOS_API_KEY", "sample")
    fake_ecos.add_series("901Y009", "M", monthly(2022, [100] * 24 + [110] * 12))
    is_error, text = await call(
        "search_statistics",
        {
            "stat_code": "901Y009",
            "cycle": "M",
            "start_date": "202301",
            "end_date": "202412",
            "item_code1": "0",
            "transform": "yoy",
        },
    )
    assert not is_error
    out = json.loads(text)
    assert out["truncated"] is True
    data = out["series"][0]["data"]
    assert data[-1] == ["202412", 110, 10.0]
    assert all(point[2] is not None for point in data)


async def test_csv_output(fake_ecos):
    fake_ecos.add_series("200Y102", "Q", {"2024Q1": 1.3, "2024Q2": -0.2}, item_code1="10111",
                         item_name1="국내총생산(GDP)(실질, 계절조정, 전기비)", unit="%")
    is_error, text = await call(
        "get_popular_statistic",
        {"indicator": "성장률", "start_date": "2024Q1", "end_date": "2024Q2", "output_format": "csv"},
    )
    assert not is_error
    assert '2024Q2,10111,"국내총생산(GDP)(실질, 계절조정, 전기비)",-0.2,%' in text


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"cycle": "X"}, "유효하지 않은 주기"),
        ({"cycle": "M", "start_date": "2024Q1", "end_date": "202403"}, "형식"),
        ({"cycle": "M", "start_date": "202405", "end_date": "202401"}, "늦습니다"),
        ({"cycle": "D", "transform": "yoy"}, "yoy"),
        ({"cycle": "M", "transform": "cagr"}, "transform"),
        ({"cycle": "M", "output_format": "xml"}, "output_format"),
    ],
)
async def test_invalid_arguments_are_tool_errors(fake_ecos, args, message):
    is_error, text = await call("search_statistics", {"stat_code": "901Y009", **args})
    assert is_error and message in text
    assert fake_ecos.calls == []


async def test_api_errors_are_tool_errors_without_key(fake_ecos):
    import httpx

    fake_ecos.forced.append(httpx.Response(401))
    is_error, text = await call("get_key_statistics", {})
    assert is_error and "HTTP_401" in text and TEST_KEY not in text


async def test_ambiguous_indicator_lists_candidates():
    is_error, text = await call("get_popular_statistic", {"indicator": "통화"})
    assert is_error and "reserve_money" in text and "m2" in text


async def test_table_search_tool():
    is_error, text = await call("search_statistic_tables", {"keyword": "소비자 물가", "limit": 2})
    out = json.loads(text)
    assert not is_error and out["data"][0]["STAT_CODE"] == "901Y009"
    assert all("ORG_NAME" not in r or r["ORG_NAME"] for r in out["data"])

    is_error, text = await call("search_statistic_tables", {"parent_code": "NOPE"})
    assert is_error
