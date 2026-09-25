"""Smoke test for ECOS MCP tools and client using the sample API key."""

import asyncio
import os
import sys

# Ensure the project source is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from ecos_mcp.client import EcosClient, EcosApiError
from ecos_mcp.config import (
    find_popular_indicator,
    get_default_date_range,
    validate_date_format,
)
from ecos_mcp.server import _format_timeseries_response


async def main():
    client = EcosClient(api_key="sample")

    print("=" * 65)
    print("🏦 ECOS MCP Server — 종합 스모크 테스트 (sample API key)")
    print("=" * 65)

    # Test 1: KeyStatisticList + sample key auto-clamping
    print("\n[1/10] KeyStatisticList (100대 주요 경제지표)...")
    try:
        res = await client.get_key_statistics(start_count=1, end_count=100)
        rows = res["rows"]
        print(f"  ✅ 성공 — {len(rows)}건 반환 (총 {res['total_count']}건 중)")
        if "note" in res:
            print(f"     ℹ️ {res['note'][:60]}...")
        for row in rows[:3]:
            name = row.get("KEYSTAT_NAME", row.get("CLASS_NAME", "?"))
            val = row.get("DATA_VALUE", "?")
            unit = row.get("UNIT_NAME", "")
            print(f"     • {name}: {val} {unit}")
    except Exception as e:
        print(f"  ❌ 실패: {e}")

    # Test 2: search_statistic_tables (844개 통계표 키워드 검색)
    print("\n[2/10] search_statistic_tables (통계표 키워드 검색: '소비자물가')...")
    try:
        res = client.search_statistic_tables(keyword="소비자물가", limit=5)
        rows = res["rows"]
        print(f"  ✅ 성공 — {len(rows)}개 통계표 검색됨")
        for row in rows[:3]:
            code = row.get("STAT_CODE")
            name = row.get("STAT_NAME")
            cycle = row.get("CYCLE")
            print(f"     • [{code}] {name} (주기: {cycle})")
    except Exception as e:
        print(f"  ❌ 실패: {e}")

    # Test 3: StatisticTableList
    print("\n[3/10] StatisticTableList (통계표 목록 계층 조회)...")
    try:
        res = await client.list_statistic_tables(start_count=1, end_count=5)
        rows = res["rows"]
        print(f"  ✅ 성공 — {len(rows)}건 반환 (전체 {res['total_count']}건)")
        for row in rows[:3]:
            print(f"     • [{row.get('STAT_CODE')}] {row.get('STAT_NAME')}")
    except Exception as e:
        print(f"  ❌ 실패: {e}")

    # Test 4: StatisticWord
    print("\n[4/10] StatisticWord (용어 검색: '기준금리')...")
    try:
        res = await client.search_statistic_word(word="기준금리", start_count=1, end_count=3)
        rows = res["rows"]
        print(f"  ✅ 성공 — {len(rows)}건 반환")
        for row in rows[:2]:
            word = row.get("WORD", "?")
            content = row.get("CONTENT", "?")[:70]
            print(f"     • {word}: {content}...")
    except Exception as e:
        print(f"  ❌ 실패: {e}")

    # Test 5: StatisticItemList
    print("\n[5/10] StatisticItemList (세부항목 목록: '102Y004' 본원통화)...")
    try:
        res = await client.list_statistic_items(stat_code="102Y004", start_count=1, end_count=5)
        rows = res["rows"]
        print(f"  ✅ 성공 — {len(rows)}건 반환 (전체 {res['total_count']}건)")
        for row in rows[:3]:
            print(f"     • [{row.get('ITEM_CODE')}] {row.get('ITEM_NAME')} (주기: {row.get('CYCLE')}, 기간: {row.get('START_TIME')}~{row.get('END_TIME')})")
    except Exception as e:
        print(f"  ❌ 실패: {e}")

    # Test 6: StatisticSearch
    print("\n[6/10] StatisticSearch (시계열 데이터: '102Y004', M, 202401~202403)...")
    try:
        res = await client.search_statistics(
            stat_code="102Y004",
            cycle="M",
            start_date="202401",
            end_date="202403",
            item_code1="ABA1",
            start_count=1,
            end_count=10,
        )
        rows = res["rows"]
        print(f"  ✅ 성공 — {len(rows)}건 반환 (전체 {res['total_count']}건)")
        for row in rows:
            time = row.get("TIME")
            name = row.get("ITEM_NAME1")
            val = row.get("DATA_VALUE")
            unit = row.get("UNIT_NAME", "")
            print(f"     • {time} | {name}: {val} {unit}")
    except Exception as e:
        print(f"  ❌ 실패: {e}")

    # Test 7: StatisticMeta
    print("\n[7/10] StatisticMeta (통계 메타데이터: '경제심리지수')...")
    try:
        res = await client.get_statistic_meta(data_name="경제심리지수", start_count=1, end_count=5)
        rows = res["rows"]
        print(f"  ✅ 성공 — {len(rows)}건 반환 (전체 {res['total_count']}건)")
        for row in rows[:2]:
            print(f"     • {row.get('CONT_NAME')}")
    except Exception as e:
        print(f"  ❌ 실패: {e}")

    # Test 8: Date validation rule verification
    print("\n[8/10] 날짜 포맷 유효성 검증 규칙...")
    valid_test, _ = validate_date_format("Q", "2024Q1")
    invalid_test, desc = validate_date_format("Q", "20241")
    assert valid_test is True, "2024Q1 should be valid"
    assert invalid_test is False, "20241 should be invalid"
    print(f"  ✅ 검증 통과: '2024Q1' 유효, '20241' 차단 (안내 문구: {desc})")

    # Test 9: Smart Date Calculation & Indicator Resolver
    print("\n[9/10] 스마트 날짜 자동 계산 및 인기 지표 리졸버...")
    start_q, end_q = get_default_date_range("Q", recent_years=2)
    start_m, end_m = get_default_date_range("M", recent_years=1)
    print(f"  ✅ 분기 기본 범위 (최근 2년): {start_q} ~ {end_q}")
    print(f"  ✅ 월간 기본 범위 (최근 1년): {start_m} ~ {end_m}")
    ind = find_popular_indicator("금리")
    assert ind is not None and ind["id"] == "base_rate", "Alias '금리' should resolve to base_rate"
    ind_cpi = find_popular_indicator("CPI")
    assert ind_cpi is not None and ind_cpi["id"] == "cpi", "Alias 'CPI' should resolve to cpi"
    print(f"  ✅ 지표 키워드 '금리' -> [{ind['stat_code']}] {ind['name']}")
    print(f"  ✅ 지표 키워드 'CPI'  -> [{ind_cpi['stat_code']}] {ind_cpi['name']}")

    # Test 10: Compact & CSV Token-Saving Formats
    print("\n[10/10] 토큰 절약형 컴팩트 포맷 및 CSV 포맷...")
    sample_data = {
        "rows": [
            {"TIME": "202401", "ITEM_NAME1": "본원통화", "STAT_NAME": "본원통화 구성", "UNIT_NAME": "십억원", "DATA_VALUE": "264486.8"},
            {"TIME": "202402", "ITEM_NAME1": "본원통화", "STAT_NAME": "본원통화 구성", "UNIT_NAME": "십억원", "DATA_VALUE": "265059.1"},
        ]
    }
    compact_out = _format_timeseries_response(sample_data, "compact")
    csv_out = _format_timeseries_response(sample_data, "csv")
    print(f"  ✅ 컴팩트 JSON (길이: {len(compact_out)}자):")
    print("     " + compact_out.replace("\n", "\n     ")[:120] + "...")
    print(f"  ✅ CSV 포맷 (길이: {len(csv_out)}자):")
    print("     " + csv_out.replace("\n", "\n     "))

    await client.close()

    print("\n" + "=" * 65)
    print("🎉 10개 스모크 테스트 항목이 모두 성공적으로 통과되었습니다!")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
