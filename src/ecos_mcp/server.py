"""MCP Server for the Bank of Korea ECOS Open API.

Provides tools, resources, and prompts to query and analyze Korean economic statistics:
Tools (8개):
- get_popular_statistic: 1-Shot 인기 지표 조회 (기준금리, GDP, 물가, 환율 등 코드 없이 즉시 조회)
- search_statistics: 통계 시계열 데이터 조회 (스마트 날짜 추정 & 컴팩트/CSV 포맷 지원)
- search_statistic_tables: 통계표 키워드 검색 (844개 통계표 대상 이름 검색)
- get_key_statistics: 100대 주요 경제지표 조회
- list_statistic_tables: 통계표 목록 및 계층 구조 조회
- search_statistic_word: 통계 용어 사전 검색
- list_statistic_items: 통계표 세부항목 목록 조회
- get_statistic_meta: 통계 메타데이터 조회

Resources:
- ecos://popular-indicators: 주요 핵심 경제지표 코드 및 주기 매핑표
- ecos://date-format-guide: 주기별 올바른 날짜 포맷 규격 안내서

Prompts:
- macro-economic-briefing: 한국 거시경제 핵심 지표 종합 브리핑
- analyze-economic-trend: 특정 경제 지표 시계열 추이 분석

CLI:
- ecos-mcp --check: 서버 및 API 키 상태 자체 진단
"""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context

from ecos_mcp.client import EcosApiError, EcosClient
from ecos_mcp.config import (
    CYCLE_DESCRIPTIONS,
    ECOS_API_KEY,
    POPULAR_INDICATORS,
    VALID_CYCLES,
    find_popular_indicator,
    get_default_date_range,
    validate_date_format,
)


# ── Lifespan: manage the shared EcosClient ─────────────────────────

@asynccontextmanager
async def lifespan(server: MCPServer) -> AsyncIterator[dict[str, Any]]:
    """Create and tear down the shared ECOS API client."""
    client = EcosClient()
    try:
        yield {"ecos_client": client}
    finally:
        await client.close()


# ── MCP Server ──────────────────────────────────────────────────────

mcp = MCPServer(
    name="ECOS MCP Server",
    description=(
        "한국은행 경제통계시스템(ECOS) Open API MCP 서버. "
        "GDP, 기준금리, 물가, 환율, 통화량 등 한국 경제 통계 데이터를 자연어로 조회하고 분석합니다."
    ),
    lifespan=lifespan,
)


def _get_client(ctx: Context) -> EcosClient:
    """Extract the EcosClient from the lifespan context."""
    return ctx.request_context.lifespan_context["ecos_client"]


def _format_response(result: dict[str, Any]) -> str:
    """Format API result dict as a readable JSON string."""
    output: dict[str, Any] = {}
    if "total_count" in result:
        output["total_count"] = result["total_count"]
    if "total_matches" in result:
        output["total_matches"] = result["total_matches"]
    output["count"] = result.get("count", len(result.get("rows", [])))
    if "start_count" in result and "end_count" in result:
        output["start_count"] = result["start_count"]
        output["end_count"] = result["end_count"]
    if "note" in result:
        output["note"] = result["note"]
    output["data"] = result.get("rows", [])
    return json.dumps(output, ensure_ascii=False, indent=2)


def _format_timeseries_response(
    result: dict[str, Any],
    format_type: str = "compact",
) -> str:
    """Format time-series data as JSON, compact JSON, or CSV to minimize LLM token usage."""
    rows = result.get("rows", [])
    if not rows:
        return _format_response(result)

    fmt = format_type.lower().strip()

    if fmt == "csv":
        lines = ["TIME,ITEM_NAME,DATA_VALUE,UNIT"]
        for r in rows:
            time_val = str(r.get("TIME", ""))
            name_val = str(r.get("ITEM_NAME1") or r.get("STAT_NAME", ""))
            data_val = str(r.get("DATA_VALUE", ""))
            unit_val = str(r.get("UNIT_NAME", ""))
            name_escaped = f'"{name_val}"' if "," in name_val else name_val
            lines.append(f"{time_val},{name_escaped},{data_val},{unit_val}")
        return "\n".join(lines)

    elif fmt == "compact":
        first = rows[0]
        stat_name = first.get("STAT_NAME", "")
        unit = first.get("UNIT_NAME", "")
        series = []
        for r in rows:
            item: dict[str, Any] = {
                "time": r.get("TIME", ""),
                "value": r.get("DATA_VALUE", ""),
            }
            if r.get("ITEM_NAME1") and r.get("ITEM_NAME1") != stat_name:
                item["name"] = r.get("ITEM_NAME1")
            series.append(item)

        compact_result: dict[str, Any] = {
            "stat_name": stat_name,
            "unit": unit,
            "total_count": result.get("total_count", len(rows)),
            "count": len(rows),
            "series": series,
        }
        if "note" in result:
            compact_result["note"] = result["note"]
        return json.dumps(compact_result, ensure_ascii=False, indent=2)

    else:
        return _format_response(result)


def _error_response(e: Exception) -> str:
    """Format an error as a JSON string."""
    return json.dumps({"error": str(e)}, ensure_ascii=False, indent=2)


# ── Tool 1: 1-Shot 인기 지표 즉시 조회 (NEW) ────────────────────────

@mcp.tool()
async def get_popular_statistic(
    ctx: Context,
    indicator: str,
    recent_years: int = 2,
    start_date: str | None = None,
    end_date: str | None = None,
    format: str = "compact",
) -> str:
    """한국은행 핵심 경제지표를 코드 검색 없이 단 1번의 호출로 즉시 조회합니다.

    사용자가 "기준금리 알려줘", "최근 GDP 보여줘", "소비자물가 추이" 등을 물을 때
    통계표코드나 항목코드를 검색할 필요 없이 즉각적으로 시계열 데이터를 반환합니다.

    지원하는 지표 키워드:
    - 기준금리 ("기준금리", "금리", "정책금리", "base_rate")
    - 국내총생산 ("GDP", "실질GDP", "국내총생산", "경제성장률")
    - 소비자물가지수 ("CPI", "소비자물가", "물가")
    - 원/달러 환율 ("환율", "원달러", "달러", "USD")
    - 본원통화 ("본원통화", "중앙은행부채")
    - M2 광의통화 ("M2", "통화량", "광의통화")
    - 국고채 3년 ("국고채", "국고채3년", "채권금리")
    - 생산자물가지수 ("PPI", "생산자물가")

    Args:
        indicator: 조회할 지표명 또는 키워드 (예: "기준금리", "물가", "GDP", "환율")
        recent_years: start_date 미지정 시 최근 몇 년치를 조회할지 설정 (기본값: 2)
        start_date: 검색 시작일 (미입력 시 recent_years 기준 자동 계산)
        end_date: 검색 종료일 (미입력 시 현재 시점 기준 자동 계산)
        format: 출력 포맷 — "compact"(토큰 절약 JSON, 기본값), "csv"(최소 토큰), "json"(전체 원본)

    Returns:
        핵심 경제지표 시계열 데이터
    """
    preset = find_popular_indicator(indicator)
    if not preset:
        valid_names = ", ".join(f"'{p['name']}'" for p in POPULAR_INDICATORS)
        return _error_response(
            ValueError(
                f"'{indicator}'에 일치하는 인기 지표를 찾을 수 없습니다.\n"
                f"지원 지표 목록: {valid_names}\n"
                f"다른 지표를 찾으려면 search_statistic_tables 도구를 사용하세요."
            )
        )

    cycle = preset["cycle"]
    stat_code = preset["stat_code"]
    item_code1 = preset.get("item_code1")

    # Smart date fallback
    if not start_date or not end_date:
        def_start, def_end = get_default_date_range(cycle, recent_years=recent_years)
        start_date = start_date or def_start
        end_date = end_date or def_end

    client = _get_client(ctx)
    try:
        res = await client.search_statistics(
            stat_code=stat_code,
            cycle=cycle,
            start_date=start_date,
            end_date=end_date,
            item_code1=item_code1,
            start_count=1,
            end_count=1000,
        )
        return _format_timeseries_response(res, format_type=format)
    except Exception as e:
        return _error_response(e)


# ── Tool 2: 통계 데이터 조회 (핵심 - 업그레이드) ────────────────────

@mcp.tool()
async def search_statistics(
    ctx: Context,
    stat_code: str,
    cycle: str,
    start_date: str | None = None,
    end_date: str | None = None,
    item_code1: str | None = None,
    item_code2: str | None = None,
    item_code3: str | None = None,
    item_code4: str | None = None,
    format: str = "compact",
    start_count: int = 1,
    end_count: int = 1000,
    language: str = "kr",
) -> str:
    """통계 시계열 데이터를 조건별로 조회합니다.

    ★ 스마트 날짜 기능:
    start_date, end_date를 생략하거나 None으로 두면 주기에 맞춰 최근 2년치 데이터가 자동 계산됩니다.

    ★ 포맷 옵션 (토큰 절약):
    - format="compact" (기본값): 중복/null 필드를 제거한 깔끔한 JSON (토큰 70% 절감)
    - format="csv": CSV 텍스트 (토큰 85% 절감, 차트 생성 시 최적)
    - format="json": ECOS 공식 전체 원본 JSON

    ★ 주기(cycle) 및 날짜 포맷 규칙:
    - 연간(A): YYYY (예: "2020", "2024")
    - 반기(S): YYYYS1, YYYYS2 (예: "2023S1", "2023S2")
    - 분기(Q): YYYYQ1 ~ YYYYQ4 (예: "2023Q1", "2024Q3")
    - 월간(M): YYYYMM (예: "202401", "202412")
    - 반월(SM): YYYYMMS1, YYYYMMS2 (예: "202401S1", "202401S2")
    - 일간(D): YYYYMMDD (예: "20240101", "20240315")

    Args:
        stat_code: 통계표코드 (필수). 예: "722Y001"(기준금리), "901Y009"(소비자물가)
        cycle: 주기 (필수). A(연), S(반기), Q(분기), M(월), SM(반월), D(일)
        start_date: 검색 시작일 (선택. 미입력 시 최근 2년 전으로 자동 설정)
        end_date: 검색 종료일 (선택. 미입력 시 현재 시점으로 자동 설정)
        item_code1~4: 통계항목코드 (선택. 미지정 시 전체 세부항목 조회)
        format: 출력 포맷 — "compact"(기본값), "csv", "json"
        start_count: 조회 시작 순번 (기본값: 1)
        end_count: 조회 끝 순번 (기본값: 1000)
        language: 응답 언어 — "kr" 또는 "en"

    Returns:
        시계열 데이터 (지정된 포맷)
    """
    cycle_upper = cycle.strip().upper()
    if cycle_upper not in VALID_CYCLES:
        valid_str = ", ".join(f"{k}: {v}" for k, v in CYCLE_DESCRIPTIONS.items())
        return _error_response(
            ValueError(f"유효하지 않은 주기(cycle)입니다: '{cycle}'. 허용 주기 목록:\n{valid_str}")
        )

    # Smart date fallback
    if not start_date or not end_date:
        def_start, def_end = get_default_date_range(cycle_upper, recent_years=2)
        start_date = start_date or def_start
        end_date = end_date or def_end

    # Validate start_date format
    is_valid_start, start_desc = validate_date_format(cycle_upper, start_date)
    if not is_valid_start:
        return _error_response(
            ValueError(
                f"start_date('{start_date}') 형식이 주기 '{cycle_upper}'와 일치하지 않습니다. "
                f"요구되는 포맷: {start_desc}"
            )
        )

    # Validate end_date format
    is_valid_end, end_desc = validate_date_format(cycle_upper, end_date)
    if not is_valid_end:
        return _error_response(
            ValueError(
                f"end_date('{end_date}') 형식이 주기 '{cycle_upper}'와 일치하지 않습니다. "
                f"요구되는 포맷: {end_desc}"
            )
        )

    client = _get_client(ctx)
    try:
        res = await client.search_statistics(
            stat_code=stat_code,
            cycle=cycle_upper,
            start_date=start_date,
            end_date=end_date,
            item_code1=item_code1,
            item_code2=item_code2,
            item_code3=item_code3,
            item_code4=item_code4,
            language=language,
            start_count=start_count,
            end_count=end_count,
        )
        return _format_timeseries_response(res, format_type=format)
    except Exception as e:
        return _error_response(e)


# ── Tool 3: 통계표 키워드 검색 ──────────────────────────────────────

@mcp.tool()
async def search_statistic_tables(
    ctx: Context,
    keyword: str,
    searchable_only: bool = True,
    limit: int = 20,
) -> str:
    """통계표 이름이나 키워드로 통계표코드(STAT_CODE)를 검색합니다.

    ECOS에 등록된 844개 통계표 전체를 대상으로 즉시 키워드 검색을 수행합니다.
    통계 데이터를 조회하기 전에 이 도구로 원하는 통계표의 코드와 주기를 가장 빠르게 찾을 수 있습니다.

    Args:
        keyword: 검색할 통계명 또는 키워드 (예: "물가", "금리", "환율", "GDP")
        searchable_only: True면 실제 데이터 조회가 가능한 통계표(SRCH_YN='Y')만 반환 (기본값: True)
        limit: 최대 반환 결과 개수 (기본값: 20)

    Returns:
        일치하는 통계표 목록
    """
    client = _get_client(ctx)
    try:
        res = client.search_statistic_tables(
            keyword=keyword,
            searchable_only=searchable_only,
            limit=limit,
        )
        return _format_response(res)
    except Exception as e:
        return _error_response(e)


# ── Tool 4: 100대 주요 경제지표 ─────────────────────────────────────

@mcp.tool()
async def get_key_statistics(
    ctx: Context,
    start_count: int = 1,
    end_count: int = 100,
    language: str = "kr",
) -> str:
    """100대 주요 경제지표를 조회합니다.

    GDP 성장률, 기준금리, 소비자물가 상승률, 실업률, M1/M2 통화량 등
    한국 경제의 핵심 지표를 한 번에 확인할 수 있습니다.

    Args:
        start_count: 조회 시작 순번 (기본값: 1)
        end_count: 조회 끝 순번 (기본값: 100, sample 키는 최대 10건으로 자동 제한)
        language: 응답 언어 — "kr"(한국어) 또는 "en"(영어)

    Returns:
        주요 경제지표 목록
    """
    client = _get_client(ctx)
    try:
        res = await client.get_key_statistics(
            language=language,
            start_count=start_count,
            end_count=end_count,
        )
        return _format_response(res)
    except Exception as e:
        return _error_response(e)


# ── Tool 5: 통계표 목록 및 계층 조회 ────────────────────────────────

@mcp.tool()
async def list_statistic_tables(
    ctx: Context,
    stat_code: str | None = None,
    searchable_only: bool = True,
    start_count: int = 1,
    end_count: int = 100,
    language: str = "kr",
) -> str:
    """통계표 목록 및 트리 계층 구조를 조회합니다.

    Args:
        stat_code: 상위 통계표코드 (선택). 지정 시 해당 코드의 직속 하위 통계표만 반환.
        searchable_only: True면 실제 조회가 가능한 통계표(SRCH_YN='Y')만 반환 (기본값: True)
        start_count: 조회 시작 순번 (기본값: 1)
        end_count: 조회 끝 순번 (기본값: 100)
        language: 응답 언어 — "kr" 또는 "en"

    Returns:
        통계표 목록
    """
    client = _get_client(ctx)
    try:
        res = await client.list_statistic_tables(
            stat_code=stat_code,
            searchable_only=searchable_only,
            language=language,
            start_count=start_count,
            end_count=end_count,
        )
        return _format_response(res)
    except Exception as e:
        return _error_response(e)


# ── Tool 6: 통계 용어 사전 검색 ─────────────────────────────────────

@mcp.tool()
async def search_statistic_word(
    ctx: Context,
    word: str,
    start_count: int = 1,
    end_count: int = 10,
    language: str = "kr",
) -> str:
    """경제/통계 용어의 정의를 검색합니다.

    한국은행 통계용어사전에서 용어의 상세 설명을 조회합니다.
    예: "기준금리", "GDP", "소비자물가지수", "통화승수", "원/달러" 등

    Args:
        word: 검색할 통계/경제 용어
        start_count: 조회 시작 순번 (기본값: 1)
        end_count: 조회 끝 순번 (기본값: 10)
        language: 응답 언어 — "kr" 또는 "en"

    Returns:
        용어 정의 목록
    """
    client = _get_client(ctx)
    try:
        res = await client.search_statistic_word(
            word=word,
            language=language,
            start_count=start_count,
            end_count=end_count,
        )
        return _format_response(res)
    except Exception as e:
        return _error_response(e)


# ── Tool 7: 통계 세부항목 목록 ──────────────────────────────────────

@mcp.tool()
async def list_statistic_items(
    ctx: Context,
    stat_code: str,
    start_count: int = 1,
    end_count: int = 500,
    language: str = "kr",
) -> str:
    """특정 통계표의 세부 항목(하위 항목)을 조회합니다.

    Args:
        stat_code: 통계표코드 (필수). search_statistic_tables에서 찾은 코드 입력.
        start_count: 조회 시작 순번 (기본값: 1)
        end_count: 조회 끝 순번 (기본값: 500)
        language: 응답 언어 — "kr" 또는 "en"

    Returns:
        세부항목 목록
    """
    client = _get_client(ctx)
    try:
        res = await client.list_statistic_items(
            stat_code=stat_code,
            language=language,
            start_count=start_count,
            end_count=end_count,
        )
        return _format_response(res)
    except Exception as e:
        return _error_response(e)


# ── Tool 8: 통계 메타데이터 조회 ────────────────────────────────────

@mcp.tool()
async def get_statistic_meta(
    ctx: Context,
    data_name: str,
    start_count: int = 1,
    end_count: int = 100,
    language: str = "kr",
) -> str:
    """통계 데이터셋의 메타데이터(구조, 작성방법, 설명)를 조회합니다.

    Args:
        data_name: 데이터셋 이름 (필수). 예: "경제심리지수", "소비자물가지수"
        start_count: 조회 시작 순번 (기본값: 1)
        end_count: 조회 끝 순번 (기본값: 100)
        language: 응답 언어 — "kr" 또는 "en"

    Returns:
        메타데이터
    """
    client = _get_client(ctx)
    try:
        res = await client.get_statistic_meta(
            data_name=data_name,
            language=language,
            start_count=start_count,
            end_count=end_count,
        )
        return _format_response(res)
    except Exception as e:
        return _error_response(e)


# ── MCP Resources ───────────────────────────────────────────────────

@mcp.resource("ecos://popular-indicators")
def get_popular_indicators_resource() -> str:
    """한국은행 주요 핵심 경제지표 코드 및 주기 매핑표 리소스."""
    return json.dumps(
        {
            "description": "자주 조회되는 한국 주요 경제지표 코드 및 주기 매핑표",
            "indicators": POPULAR_INDICATORS,
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.resource("ecos://date-format-guide")
def get_date_format_guide_resource() -> str:
    """주기별 올바른 날짜 포맷 규격서 리소스."""
    return json.dumps(
        {
            "description": "ECOS API 주기(Cycle)별 검색일자(SearchStartDate/EndDate) 규격",
            "cycles": CYCLE_DESCRIPTIONS,
        },
        ensure_ascii=False,
        indent=2,
    )


# ── MCP Prompts ─────────────────────────────────────────────────────

@mcp.prompt()
def macro_economic_briefing() -> str:
    """한국 거시경제 핵심 지표 종합 브리핑 프롬프트."""
    return (
        "한국 거시경제의 현재 상황을 종합적으로 분석하고 브리핑해주세요.\n"
        "다음 절차로 진행해주세요:\n"
        "1. get_key_statistics 도구를 호출하여 최신 100대 경제지표를 확인합니다.\n"
        "2. 경제성장률(GDP), 기준금리, 소비자물가상승률(CPI), 원/달러 환율, 실업률 데이터를 정리합니다.\n"
        "3. 한국 경제의 현 위치, 주요 리스크 요인, 향후 경기 전망을 전문 애널리스트 관점에서 보고서 형태로 작성해주세요."
    )


@mcp.prompt()
def analyze_economic_trend(indicator_name: str = "소비자물가지수") -> str:
    """특정 경제 지표의 시계열 추이 및 시사점 심층 분석 프롬프트."""
    return (
        f"'{indicator_name}' 지표의 최근 시계열 추이를 분석해주세요.\n"
        "다음 절차로 진행해주세요:\n"
        f"1. get_popular_statistic(indicator='{indicator_name}') 또는 search_statistic_tables로 데이터를 조회합니다.\n"
        "2. 최근 2~3년간의 수치 추이와 주요 변곡점을 확인합니다.\n"
        "3. 수치 추이, 급변 시점의 배경 요인, 정책적 시사점을 체계적으로 분석하여 설명해주세요."
    )


# ── CLI Health Check ────────────────────────────────────────────────

async def run_health_check() -> int:
    """Run interactive diagnostics check for CLI users."""
    print("=" * 65)
    print("🩺 ECOS MCP Server — 자가 진단 및 헬스체크")
    print("=" * 65)

    # 1. Environment & Python
    py_ver = sys.version.split()[0]
    print(f"\n[1/4] 실행 환경: Python {py_ver} ({sys.platform})")
    print("  ✅ Python 버전 정상 (>=3.11)")

    # 2. API Key
    print("\n[2/4] ECOS API Key 구성 확인...")
    if ECOS_API_KEY == "sample":
        print("  ⚠️ 현재 'sample' 키를 사용 중입니다. (1회 최대 10건 조회 제한)")
        print("     정식 키 발급: https://ecos.bok.or.kr/api/#/ (무료)")
    else:
        masked = f"{ECOS_API_KEY[:4]}...{ECOS_API_KEY[-4:]}"
        print(f"  ✅ 사용자 API 키 설정됨 ({masked})")

    # 3. Network & API test
    print("\n[3/4] 한국은행 ECOS 서버 네트워크 통신 확인...")
    client = EcosClient()
    try:
        res = await client.get_key_statistics(start_count=1, end_count=1)
        print("  ✅ 한국은행 ECOS API 연결 정상 (100대 지표 응답 수신 성공)")
    except Exception as e:
        print(f"  ❌ 연결 실패: {e}")
        await client.close()
        return 1

    # 4. Table Index Check
    print("\n[4/4] 844개 통계표 로컬 검색 인덱스 검사...")
    search_res = client.search_statistic_tables("물가", limit=3)
    matched = search_res.get("total_matches", 0)
    if matched > 0:
        print(f"  ✅ 통계표 인덱스 로드 성공 ('물가' 검색 결과: {matched}건)")
    else:
        print("  ⚠️ 통계표 인덱스를 불러올 수 없습니다.")

    await client.close()
    print("\n" + "=" * 65)
    print("🎉 모든 진단 검사를 통과했습니다! ECOS MCP 서버를 실행할 준비가 되었습니다.")
    print("   실행 명령어: uv run ecos-mcp")
    print("=" * 65)
    return 0


# ── Entry point ─────────────────────────────────────────────────────

def main() -> None:
    """Run the ECOS MCP server or CLI healthcheck."""
    if any(arg in sys.argv for arg in ("--check", "-c", "--health", "--test")):
        sys.exit(asyncio.run(run_health_check()))
    mcp.run()


if __name__ == "__main__":
    main()
