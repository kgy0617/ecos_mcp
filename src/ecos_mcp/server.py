"""MCP Server for the Bank of Korea ECOS Open API.

Provides tools, resources, and prompts to query and analyze Korean economic statistics:
Tools (7개):
- get_popular_statistic: 1-Shot 인기 지표 조회 (기준금리, 성장률, 물가상승률, 환율 등 코드 없이 즉시 조회)
- search_statistics: 통계 시계열 데이터 조회 (스마트 날짜, 최신 우선, 증감률 계산, 컴팩트/CSV 포맷)
- search_statistic_tables: 통계표 키워드 검색 및 계층 탐색 (로컬 인덱스, API 호출 없음)
- get_key_statistics: 100대 주요 경제지표 조회
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
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from ecos_mcp.client import EcosApiError, EcosClient
from ecos_mcp.config import (
    CYCLE_DESCRIPTIONS,
    ECOS_API_KEY,
    POPULAR_INDICATORS,
    SAMPLE_API_KEY,
    VALID_CYCLES,
    find_popular_indicator,
    get_default_date_range,
    match_popular_indicators,
    period_to_index,
    shift_period,
    validate_date_format,
)
from ecos_mcp.timeseries import (
    OUTPUT_FORMATS,
    TRANSFORMS,
    apply_transform,
    drop_unchanged,
    dumps,
    format_timeseries,
    transform_lookback,
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
    instructions=(
        "1) 기준금리·성장률·물가(상승률)·환율·통화량·국고채·PPI는 get_popular_statistic 한 번으로 조회하세요. "
        "2) 그 외 지표는 search_statistic_tables로 STAT_CODE를 찾고, list_statistic_items로 항목코드·주기를 확인한 뒤 "
        "search_statistics로 조회하세요. "
        "3) 증감률이 필요하면 transform='yoy'(전년동기비) 또는 'pop'(전기비)을 사용하세요."
    ),
    lifespan=lifespan,
)

REMOTE_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)
LOCAL_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def _get_client(ctx: Context) -> EcosClient:
    """Extract the EcosClient from the lifespan context."""
    return ctx.request_context.lifespan_context["ecos_client"]


def _compact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop null/empty fields, which make up much of ECOS metadata rows."""
    return [{k: v for k, v in r.items() if v not in (None, "")} for r in rows]


def _format_response(result: dict[str, Any]) -> str:
    """Format a non-time-series result as compact JSON."""
    output: dict[str, Any] = {}
    for key in (
        "query",
        "parent",
        "total_count",
        "total_matches",
        "count",
        "start_count",
        "end_count",
        "has_more",
        "index_generated_at",
        "note",
    ):
        if result.get(key) is not None:
            output[key] = result[key]
    output.setdefault("count", len(result.get("rows", [])))
    output["data"] = _compact_rows(result.get("rows", []))
    return dumps(output)


async def _call_ecos(coro: Any) -> dict[str, Any]:
    """Await an ECOS client call, surfacing API failures as MCP tool errors."""
    try:
        return await coro
    except EcosApiError as e:
        raise ToolError(str(e)) from e


def _normalize_transform(transform: str | None) -> str | None:
    value = (transform or "").strip().lower()
    if value in ("", "none", "raw"):
        return None
    if value not in TRANSFORMS:
        raise ToolError(
            f"지원되지 않는 transform입니다: '{transform}'. "
            "'yoy'(전년동기대비 %), 'pop'(직전 관측치 대비 %), 'none' 중 하나를 사용하세요."
        )
    return value


async def _query_timeseries(
    ctx: Context,
    *,
    stat_code: str,
    cycle: str,
    start_date: str | None,
    end_date: str | None,
    item_codes: list[str | None],
    recent_years: int | None = None,
    output_format: str = "compact",
    transform: str | None = None,
    changes_only: bool = False,
    language: str = "kr",
    start_count: int = 1,
    end_count: int = 1000,
    prefer_latest: bool = True,
    meta: dict[str, Any] | None = None,
) -> str:
    """Validate inputs, fetch StatisticSearch rows, post-process, and format them."""
    cycle_upper = (cycle or "").strip().upper()
    if cycle_upper not in VALID_CYCLES:
        valid_str = ", ".join(f"{k}: {v}" for k, v in CYCLE_DESCRIPTIONS.items())
        raise ToolError(f"유효하지 않은 주기(cycle)입니다: '{cycle}'. 허용 주기 목록:\n{valid_str}")

    fmt = (output_format or "compact").strip().lower()
    if fmt not in OUTPUT_FORMATS:
        raise ToolError(f"지원되지 않는 output_format입니다: '{output_format}'. compact, csv, json 중 하나를 사용하세요.")

    transform_key = _normalize_transform(transform)
    if transform_key == "yoy" and cycle_upper == "D":
        raise ToolError("일간(D) 데이터에는 transform='yoy'를 쓸 수 없습니다. 'pop'을 쓰거나 월간 통계표를 사용하세요.")

    # Smart date fallback
    if not start_date or not end_date:
        def_start, def_end = get_default_date_range(cycle_upper, recent_years=recent_years)
        start_date = start_date or def_start
        end_date = end_date or def_end
    start_date, end_date = start_date.strip(), end_date.strip()

    for label, value in (("start_date", start_date), ("end_date", end_date)):
        is_valid, expected = validate_date_format(cycle_upper, value)
        if not is_valid:
            raise ToolError(
                f"{label}('{value}') 형식이 주기 '{cycle_upper}'와 일치하지 않습니다. 요구되는 포맷: {expected}"
            )
    if period_to_index(cycle_upper, start_date) > period_to_index(cycle_upper, end_date):
        raise ToolError(f"start_date('{start_date}')가 end_date('{end_date}')보다 늦습니다.")

    lookback = transform_lookback(cycle_upper, transform_key)
    fetch_start = shift_period(cycle_upper, start_date, -lookback) if lookback else start_date

    client = _get_client(ctx)
    codes = (list(item_codes) + [None] * 4)[:4]

    async def fetch(first: str, last: str) -> dict[str, Any]:
        return await _call_ecos(
            client.search_statistics(
                stat_code=stat_code.strip(),
                cycle=cycle_upper,
                start_date=first,
                end_date=last,
                item_code1=codes[0],
                item_code2=codes[1],
                item_code3=codes[2],
                item_code4=codes[3],
                language=language,
                start_count=start_count,
                end_count=end_count,
                prefer_latest=prefer_latest,
            )
        )

    res = await fetch(fetch_start, end_date)

    if transform_key:
        rows = res["rows"]
        base_rows: list[dict[str, Any]] = []
        if transform_key == "yoy" and res.get("truncated") and rows:
            # A truncated page may not reach back a full year; fetch the base periods.
            times = sorted(str(r["TIME"]) for r in rows)
            base = await fetch(
                shift_period(cycle_upper, times[0], -lookback),
                shift_period(cycle_upper, times[-1], -lookback),
            )
            base_rows = base["rows"]
        apply_transform(base_rows + rows, cycle_upper, transform_key)
        # Lookback rows only served as the base for the first periods; drop them.
        res["rows"] = [r for r in rows if str(r.get("TIME", "")) >= start_date]
        if not res.get("truncated"):
            res["total_count"] = len(res["rows"])
    if changes_only:
        res["rows"] = drop_unchanged(res["rows"])

    summary_meta: dict[str, Any] = {
        **(meta or {}),
        "cycle": cycle_upper,
        "start_date": start_date,
        "end_date": end_date,
    }
    if changes_only:
        summary_meta["changes_only"] = True
    return format_timeseries(res, fmt, transform_key, meta=summary_meta)


# ── Tool 1: 1-Shot 인기 지표 즉시 조회 ─────────────────────────────

@mcp.tool(title="인기 경제지표 즉시 조회", annotations=REMOTE_READ_ONLY, structured_output=False)
async def get_popular_statistic(
    ctx: Context,
    indicator: str,
    recent_years: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    output_format: str = "compact",
    transform: str | None = None,
    changes_only: bool | None = None,
) -> str:
    """한국은행 핵심 경제지표를 코드 검색 없이 단 1번의 호출로 즉시 조회합니다.

    사용자가 "기준금리 알려줘", "최근 성장률", "물가상승률 추이" 등을 물을 때
    통계표코드나 항목코드를 검색할 필요 없이 즉각적으로 시계열 데이터를 반환합니다.

    지원하는 지표 키워드:
    - 기준금리 ("기준금리", "금리", "정책금리") — 변경 시점만 반환(changes_only 기본 True)
    - 경제성장률 ("경제성장률", "성장률", "GDP성장률") — 실질 GDP 전기비 %
    - 국내총생산 ("GDP", "실질GDP", "국내총생산") — 실질 GDP 수준(십억원)
    - 소비자물가상승률 ("물가상승률", "인플레이션") — CPI 전년동월비 %(yoy_pct)
    - 소비자물가지수 ("CPI", "소비자물가", "물가") — 지수 수준(2020=100)
    - 원/달러 환율 ("환율", "원달러", "달러", "USD") — 일별 / ("월평균환율") — 월평균
    - 본원통화 ("본원통화", "중앙은행부채")
    - M2 광의통화 ("M2", "통화량", "광의통화")
    - 국고채 3년 ("국고채", "국고채3년", "채권금리") — 일별 / ("국고채월평균") — 월평균
    - 생산자물가지수 ("PPI", "생산자물가")

    Args:
        indicator: 조회할 지표명 또는 키워드 (예: "기준금리", "물가상승률", "성장률", "환율")
        recent_years: start_date 미지정 시 최근 몇 년치를 조회할지 (기본: 일별 지표 최근 3개월, 그 외 2년)
        start_date: 검색 시작일 (주기에 맞는 포맷. 미입력 시 자동 계산)
        end_date: 검색 종료일 (미입력 시 현재 시점)
        output_format: "compact"(기본값, 계열별 [시점, 값] 배열), "csv", "json"(ECOS 원본 행)
        transform: "yoy"(전년동기대비 %), "pop"(직전 관측치 대비 %), "none". 미지정 시 지표 기본값 사용
        changes_only: True면 값이 바뀐 시점만 반환. 미지정 시 지표 기본값 사용

    Returns:
        핵심 경제지표 시계열 데이터. 결과가 한 번에 다 담기지 않으면 최신 구간을 우선 반환합니다.
    """
    preset = find_popular_indicator(indicator)
    if not preset:
        candidates = match_popular_indicators(indicator)
        if candidates:
            listed = ", ".join(f"'{p['id']}'({p['name']})" for p in candidates)
            raise ToolError(
                f"'{indicator}'에 해당하는 지표가 여러 개입니다: {listed}. 더 구체적인 키워드나 id를 사용하세요."
            )
        valid_names = ", ".join(f"'{p['id']}'({p['name']})" for p in POPULAR_INDICATORS)
        raise ToolError(
            f"'{indicator}'에 일치하는 인기 지표를 찾을 수 없습니다.\n"
            f"지원 지표 목록: {valid_names}\n"
            "다른 지표를 찾으려면 search_statistic_tables 도구를 사용하세요."
        )

    return await _query_timeseries(
        ctx,
        stat_code=preset["stat_code"],
        cycle=preset["cycle"],
        start_date=start_date,
        end_date=end_date,
        item_codes=[preset.get("item_code1"), preset.get("item_code2")],
        recent_years=recent_years,
        output_format=output_format,
        transform=preset.get("transform") if transform is None else transform,
        changes_only=preset.get("changes_only", False) if changes_only is None else changes_only,
        meta={"indicator": preset["id"], "indicator_name": preset["name"]},
    )


# ── Tool 2: 통계 데이터 조회 ───────────────────────────────────────

@mcp.tool(title="통계 시계열 조회", annotations=REMOTE_READ_ONLY, structured_output=False)
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
    output_format: str = "compact",
    transform: str | None = None,
    changes_only: bool = False,
    prefer_latest: bool = True,
    start_count: int = 1,
    end_count: int = 1000,
    language: str = "kr",
) -> str:
    """통계 시계열 데이터를 조건별로 조회합니다.

    ★ 스마트 날짜: start_date, end_date를 생략하면 일간(D)은 최근 3개월, 그 외 주기는 최근 2년이 자동 설정됩니다.
    ★ 최신 우선: 결과가 end_count를 넘으면 가장 최근 구간을 반환하고 truncated=true와 안내를 붙입니다.
    ★ 증감률: transform="yoy"(전년동기대비 %) 또는 "pop"(직전 관측치 대비 %)를 지정하면 계산 열이 추가됩니다.
    ★ 포맷: "compact"(기본값, 계열별 [시점, 값] 배열), "csv", "json"(ECOS 원본 행)

    ★ 주기(cycle) 및 날짜 포맷 규칙:
    - 연간(A): YYYY (예: "2024")
    - 반기(S): YYYYS1, YYYYS2 (예: "2023S1")
    - 분기(Q): YYYYQ1 ~ YYYYQ4 (예: "2024Q3")
    - 월간(M): YYYYMM (예: "202401")
    - 반월(SM): YYYYMMS1, YYYYMMS2 (예: "202401S1")
    - 일간(D): YYYYMMDD (예: "20240315")

    Args:
        stat_code: 통계표코드 (필수). 예: "722Y001"(기준금리), "901Y009"(소비자물가)
        cycle: 주기 (필수). A(연), S(반기), Q(분기), M(월), SM(반월), D(일)
        start_date: 검색 시작일 (선택)
        end_date: 검색 종료일 (선택)
        item_code1~4: 통계항목코드 (선택. 미지정 시 전체 세부항목 조회 — 결과가 매우 커질 수 있음)
        output_format: "compact"(기본값), "csv", "json"
        transform: "yoy", "pop", "none"(기본값)
        changes_only: True면 값이 바뀐 시점만 반환 (금리처럼 드물게 변하는 일별 지표에 유용)
        prefer_latest: 결과가 잘릴 때 최신 구간을 우선 반환 (기본값 True)
        start_count: 조회 시작 순번 (기본값: 1)
        end_count: 조회 끝 순번 (기본값: 1000)
        language: 응답 언어 — "kr" 또는 "en"

    Returns:
        시계열 데이터 (지정된 포맷)
    """
    return await _query_timeseries(
        ctx,
        stat_code=stat_code,
        cycle=cycle,
        start_date=start_date,
        end_date=end_date,
        item_codes=[item_code1, item_code2, item_code3, item_code4],
        output_format=output_format,
        transform=transform,
        changes_only=changes_only,
        language=language,
        start_count=start_count,
        end_count=end_count,
        prefer_latest=prefer_latest,
    )


# ── Tool 3: 통계표 검색 및 계층 탐색 (로컬 인덱스) ─────────────────

@mcp.tool(title="통계표 검색·탐색", annotations=LOCAL_READ_ONLY, structured_output=False)
async def search_statistic_tables(
    ctx: Context,
    keyword: str | None = None,
    parent_code: str | None = None,
    searchable_only: bool = True,
    limit: int = 20,
) -> str:
    """통계표 이름으로 통계표코드(STAT_CODE)를 검색하거나, 통계표 분류 트리를 탐색합니다.

    ECOS 통계표 전체의 로컬 인덱스를 사용하므로 API 호출 없이 즉시 응답합니다.
    - keyword 지정: 이름 검색. 띄어쓰기로 나눈 단어가 모두 포함된 통계표를 관련도 순으로 반환
      ("소비자 물가" → "소비자물가지수"). parent_code를 함께 주면 그 분류 아래에서만 검색합니다.
    - keyword 없이 parent_code 지정: 해당 분류의 직속 하위 항목 반환 (분류 노드 포함)
    - 둘 다 없음: 최상위 분류 목록 반환

    Args:
        keyword: 검색할 통계명 또는 키워드 (예: "물가", "금리", "환율", "경상수지")
        parent_code: 상위 분류 STAT_CODE (예: "0000000001")
        searchable_only: keyword 검색 시 실제 데이터 조회가 가능한 통계표(SRCH_YN='Y')만 반환 (기본값: True)
        limit: keyword 검색 시 최대 반환 개수 (기본값: 20)

    Returns:
        통계표 목록 (STAT_CODE, STAT_NAME, CYCLE, SRCH_YN 등)
    """
    client = _get_client(ctx)
    if keyword and keyword.strip():
        res = client.search_statistic_tables(
            keyword=keyword,
            searchable_only=searchable_only,
            limit=limit,
            parent_code=parent_code,
        )
    else:
        res = client.browse_statistic_tables(parent_code=parent_code)
        if parent_code and res["parent"] is None:
            raise ToolError(f"통계표 인덱스에 '{parent_code}' 코드가 없습니다.")
    return _format_response(res)


# ── Tool 4: 100대 주요 경제지표 ─────────────────────────────────────

@mcp.tool(title="100대 주요 경제지표", annotations=REMOTE_READ_ONLY, structured_output=False)
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
    res = await _call_ecos(
        _get_client(ctx).get_key_statistics(
            language=language,
            start_count=start_count,
            end_count=end_count,
        )
    )
    return _format_response(res)


# ── Tool 5: 통계 용어 사전 검색 ─────────────────────────────────────

@mcp.tool(title="통계 용어 사전", annotations=REMOTE_READ_ONLY, structured_output=False)
async def search_statistic_word(
    ctx: Context,
    word: str,
    start_count: int = 1,
    end_count: int = 10,
    language: str = "kr",
) -> str:
    """경제/통계 용어의 정의를 검색합니다.

    한국은행 통계용어사전에서 용어의 상세 설명을 조회합니다.
    예: "기준금리", "GDP", "소비자물가지수", "통화승수" 등
    (ECOS 방화벽 제약으로 '/'는 공백으로 바뀌어 검색됩니다.)

    Args:
        word: 검색할 통계/경제 용어
        start_count: 조회 시작 순번 (기본값: 1)
        end_count: 조회 끝 순번 (기본값: 10)
        language: 응답 언어 — "kr" 또는 "en"

    Returns:
        용어 정의 목록
    """
    res = await _call_ecos(
        _get_client(ctx).search_statistic_word(
            word=word,
            language=language,
            start_count=start_count,
            end_count=end_count,
        )
    )
    return _format_response(res)


# ── Tool 6: 통계 세부항목 목록 ──────────────────────────────────────

@mcp.tool(title="통계표 세부항목", annotations=REMOTE_READ_ONLY, structured_output=False)
async def list_statistic_items(
    ctx: Context,
    stat_code: str,
    start_count: int = 1,
    end_count: int = 500,
    language: str = "kr",
) -> str:
    """특정 통계표의 세부 항목(항목코드, 지원 주기, 수록 기간, 단위)을 조회합니다.

    Args:
        stat_code: 통계표코드 (필수). search_statistic_tables에서 찾은 코드 입력.
        start_count: 조회 시작 순번 (기본값: 1)
        end_count: 조회 끝 순번 (기본값: 500)
        language: 응답 언어 — "kr" 또는 "en"

    Returns:
        세부항목 목록 (has_more=true면 start_count를 늘려 다음 페이지 조회)
    """
    res = await _call_ecos(
        _get_client(ctx).list_statistic_items(
            stat_code=stat_code.strip(),
            language=language,
            start_count=start_count,
            end_count=end_count,
        )
    )
    return _format_response(res)


# ── Tool 7: 통계 메타데이터 조회 ────────────────────────────────────

@mcp.tool(title="통계 메타데이터", annotations=REMOTE_READ_ONLY, structured_output=False)
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
    res = await _call_ecos(
        _get_client(ctx).get_statistic_meta(
            data_name=data_name,
            language=language,
            start_count=start_count,
            end_count=end_count,
        )
    )
    return _format_response(res)


# ── MCP Resources ───────────────────────────────────────────────────

@mcp.resource("ecos://popular-indicators")
def get_popular_indicators_resource() -> str:
    """한국은행 주요 핵심 경제지표 코드 및 주기 매핑표 리소스."""
    return dumps(
        {
            "description": "자주 조회되는 한국 주요 경제지표 코드 및 주기 매핑표",
            "indicators": POPULAR_INDICATORS,
        }
    )


@mcp.resource("ecos://date-format-guide")
def get_date_format_guide_resource() -> str:
    """주기별 올바른 날짜 포맷 규격서 리소스."""
    return dumps(
        {
            "description": "ECOS API 주기(Cycle)별 검색일자(SearchStartDate/EndDate) 규격",
            "cycles": CYCLE_DESCRIPTIONS,
        }
    )


# ── MCP Prompts ─────────────────────────────────────────────────────

@mcp.prompt(name="macro-economic-briefing")
def macro_economic_briefing() -> str:
    """한국 거시경제 핵심 지표 종합 브리핑 프롬프트."""
    return (
        "한국 거시경제의 현재 상황을 종합적으로 분석하고 브리핑해주세요.\n"
        "다음 절차로 진행해주세요:\n"
        "1. get_key_statistics 도구로 최신 100대 경제지표를 확인합니다.\n"
        "2. get_popular_statistic으로 '성장률', '물가상승률', '기준금리', '월평균환율'의 최근 추이를 조회합니다.\n"
        "3. 한국 경제의 현 위치, 주요 리스크 요인, 향후 경기 전망을 전문 애널리스트 관점에서 보고서 형태로 작성해주세요."
    )


@mcp.prompt(name="analyze-economic-trend")
def analyze_economic_trend(indicator_name: str = "소비자물가지수") -> str:
    """특정 경제 지표의 시계열 추이 및 시사점 심층 분석 프롬프트."""
    return (
        f"'{indicator_name}' 지표의 최근 시계열 추이를 분석해주세요.\n"
        "다음 절차로 진행해주세요:\n"
        f"1. get_popular_statistic(indicator='{indicator_name}', recent_years=3)으로 조회합니다. "
        "지원되지 않는 지표면 search_statistic_tables → list_statistic_items → search_statistics 순서로 조회합니다.\n"
        "2. 수준값 지표라면 transform='yoy'로 전년동기대비 증감률도 함께 확인합니다.\n"
        "3. 수치 추이, 주요 변곡점과 그 배경 요인, 정책적 시사점을 체계적으로 분석하여 설명해주세요."
    )


# ── CLI Health Check ────────────────────────────────────────────────

def _mask_key(key: str) -> str:
    return f"{key[:4]}...{key[-4:]}" if len(key) > 12 else "****"


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
    if ECOS_API_KEY == SAMPLE_API_KEY:
        print("  ⚠️ 현재 'sample' 키를 사용 중입니다. (1회 최대 10건 조회 제한)")
        print("     정식 키 발급: https://ecos.bok.or.kr/api/#/ (무료)")
    else:
        print(f"  ✅ 사용자 API 키 설정됨 ({_mask_key(ECOS_API_KEY)})")

    # 3. Network & API test
    print("\n[3/4] 한국은행 ECOS 서버 네트워크 통신 확인...")
    client = EcosClient()
    try:
        try:
            await client.get_key_statistics(start_count=1, end_count=1)
            print("  ✅ 한국은행 ECOS API 연결 정상 (100대 지표 응답 수신 성공)")
        except EcosApiError as e:
            print(f"  ❌ 연결 실패: {e}")
            return 1

        # 4. Table Index Check
        print("\n[4/4] 통계표 로컬 검색 인덱스 검사...")
        search_res = client.search_statistic_tables("물가", limit=3)
        table_count = len(client._load_tables_cache())
        if search_res.get("total_matches", 0) > 0:
            print(
                f"  ✅ 통계표 인덱스 로드 성공 ({table_count}개, 생성일: {client.tables_generated_at or '미상'}, "
                f"'물가' 검색 결과: {search_res['total_matches']}건)"
            )
        else:
            print("  ❌ 통계표 인덱스를 불러올 수 없습니다.")
            return 1
    finally:
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
