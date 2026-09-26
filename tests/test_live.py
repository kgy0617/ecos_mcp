"""Tests against the real ECOS API. Skipped by default; run with: uv run pytest -m live"""

import json

import pytest
from mcp import Client

from ecos_mcp.client import EcosClient
from ecos_mcp.config import POPULAR_INDICATORS
from ecos_mcp.server import mcp

pytestmark = [pytest.mark.live, pytest.mark.anyio]


@pytest.mark.parametrize("preset", POPULAR_INDICATORS, ids=lambda p: p["id"])
async def test_every_preset_returns_data(preset):
    async with Client(mcp) as c:
        result = await c.call_tool(
            "get_popular_statistic", {"indicator": preset["id"], "recent_years": 1}
        )
    assert not result.is_error, result.content[0].text
    out = json.loads(result.content[0].text)
    assert out["count"] > 0
    series = out["series"][0]
    assert series["unit"] == preset["unit"].split(" ")[0]


async def test_key_statistics_and_metadata_services():
    client = EcosClient()
    try:
        assert (await client.get_key_statistics(end_count=3))["count"] > 0
        assert (await client.search_statistic_word("기준금리", end_count=3))["count"] > 0
        assert (await client.list_statistic_items("102Y004", end_count=3))["count"] > 0
        assert (await client.get_statistic_meta("경제심리지수", end_count=3))["count"] > 0
    finally:
        await client.close()
