"""Configuration management for ECOS MCP Server."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

# ECOS API Configuration
ECOS_BASE_URL = "https://ecos.bok.or.kr/api"
ECOS_API_KEY = os.getenv("ECOS_API_KEY", "sample")
ECOS_RESPONSE_TYPE = "json"

# Default pagination
DEFAULT_START_COUNT = 1
DEFAULT_END_COUNT = 100
DEFAULT_LANGUAGE = "kr"
SAMPLE_KEY_MAX_COUNT = 10

# Valid cycle values for StatisticSearch
VALID_CYCLES = {"A", "S", "Q", "M", "SM", "D"}
CYCLE_DESCRIPTIONS = {
    "A": "연간 (Annual) — 포맷: YYYY (예: 2024)",
    "S": "반기 (Semi-annual) — 포맷: YYYYS1 / YYYYS2 (예: 2024S1)",
    "Q": "분기 (Quarterly) — 포맷: YYYYQ1 ~ YYYYQ4 (예: 2024Q1)",
    "M": "월간 (Monthly) — 포맷: YYYYMM (예: 202401)",
    "SM": "반월 (Semi-monthly) — 포맷: YYYYMMS1 / YYYYMMS2 (예: 202401S1)",
    "D": "일간 (Daily) — 포맷: YYYYMMDD (예: 20240101)",
}

# Date validation patterns per cycle
CYCLE_DATE_FORMATS: dict[str, tuple[str, str]] = {
    "A": (r"^\d{4}$", "YYYY (예: '2024')"),
    "S": (r"^\d{4}S[12]$", "YYYYS1 또는 YYYYS2 (예: '2024S1')"),
    "Q": (r"^\d{4}Q[1-4]$", "YYYYQ1 ~ YYYYQ4 (예: '2024Q1')"),
    "M": (r"^\d{4}(0[1-9]|1[0-2])$", "YYYYMM (예: '202401')"),
    "SM": (r"^\d{4}(0[1-9]|1[0-2])S[12]$", "YYYYMMS1 또는 YYYYMMS2 (예: '202401S1')"),
    "D": (r"^\d{4}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$", "YYYYMMDD (예: '20240101')"),
}


def validate_date_format(cycle: str, date_str: str) -> tuple[bool, str]:
    """Validate that date_str matches the required format for cycle.

    Returns:
        (is_valid, expected_format_description)
    """
    cycle = cycle.upper()
    rule = CYCLE_DATE_FORMATS.get(cycle)
    if not rule:
        return False, f"지원되지 않는 주기입니다: '{cycle}'"
    pattern, desc = rule
    if re.match(pattern, str(date_str).strip()):
        return True, ""
    return False, desc


def get_default_date_range(cycle: str, recent_years: int = 2) -> tuple[str, str]:
    """Calculate default start and end dates relative to today.

    Args:
        cycle: Period cycle (A, S, Q, M, SM, D)
        recent_years: Number of years to look back (default: 2)

    Returns:
        (start_date, end_date) in valid format for cycle
    """
    now = datetime.now()
    year = now.year
    month = now.month
    day = now.day
    quarter = (month - 1) // 3 + 1
    semi = 1 if month <= 6 else 2
    semi_month = 1 if day <= 15 else 2

    start_year = max(1950, year - max(1, recent_years))

    cycle = cycle.upper()
    if cycle == "A":
        return str(start_year), str(year)
    elif cycle == "S":
        return f"{start_year}S1", f"{year}S{semi}"
    elif cycle == "Q":
        return f"{start_year}Q1", f"{year}Q{quarter}"
    elif cycle == "M":
        return f"{start_year}{month:02d}", f"{year}{month:02d}"
    elif cycle == "SM":
        return f"{start_year}{month:02d}S1", f"{year}{month:02d}S{semi_month}"
    elif cycle == "D":
        return f"{start_year}{month:02d}{day:02d}", f"{year}{month:02d}{day:02d}"
    return str(start_year), str(year)


# ECOS error code descriptions
ECOS_ERROR_MAP = {
    "INFO-100": "인증키가 유효하지 않습니다. ECOS_API_KEY 환경변수를 확인하세요.",
    "INFO-200": "해당 조건에 맞는 데이터가 없습니다.",
    "ERROR-100": "필수 입력값이 누락되었습니다.",
    "ERROR-101": "주기와 날짜 형식이 일치하지 않습니다. (예: 분기는 2024Q1, 월은 202401)",
    "ERROR-200": "파일 타입 오류입니다.",
    "ERROR-300": "조회건수 값이 누락되었습니다.",
    "ERROR-301": "조회건수 오류입니다. (참고: sample 키는 1회 최대 10건만 조회 가능합니다.)",
    "ERROR-400": "조회 범위가 너무 넓어 60초 타임아웃이 발생했습니다. 날짜 범위를 줄이거나 항목코드를 지정하세요.",
    "ERROR-500": "한국은행 ECOS 서버 내부 오류가 발생했습니다.",
    "ERROR-600": "한국은행 DB 연결 오류가 발생했습니다.",
    "ERROR-601": "한국은행 SQL 오류가 발생했습니다.",
    "ERROR-602": "API 일일 호출 한도를 초과했습니다. 잠시 후 다시 시도하세요.",
}

# Popular economic indicators cheat-sheet
POPULAR_INDICATORS: list[dict[str, Any]] = [
    {
        "id": "base_rate",
        "name": "한국은행 기준금리",
        "aliases": ["기준금리", "금리", "정책금리", "base_rate", "rate"],
        "stat_code": "722Y001",
        "stat_name": "1.3.1. 한국은행 기준금리 및 여수신금리",
        "cycle": "D",
        "item_code1": "0101000",
        "item_name1": "한국은행 기준금리",
        "unit": "연%",
    },
    {
        "id": "gdp",
        "name": "국내총생산(실질 GDP)",
        "aliases": ["국내총생산", "gdp", "실질gdp", "경제성장률", "성장률"],
        "stat_code": "200Y108",
        "stat_name": "2.1.2.2.2. 국내총생산에 대한 지출(계절조정, 실질, 분기)",
        "cycle": "Q",
        "item_code1": "10601",
        "item_name1": "국내총생산(실질)",
        "unit": "십억원",
    },
    {
        "id": "cpi",
        "name": "소비자물가지수(CPI)",
        "aliases": ["소비자물가지수", "소비자물가", "물가", "cpi", "물가지수"],
        "stat_code": "901Y009",
        "stat_name": "4.2.1. 소비자물가지수",
        "cycle": "M",
        "item_code1": "0",
        "item_name1": "총지수",
        "unit": "2020=100",
    },
    {
        "id": "usd_krw",
        "name": "원/달러 환율",
        "aliases": ["원달러", "원/달러", "환율", "달러", "usd", "usdkrw"],
        "stat_code": "731Y001",
        "stat_name": "3.1.1.1. 주요국 통화의 대원화환율",
        "cycle": "D",
        "item_code1": "0000001",
        "item_name1": "원/달러(매매기준율)",
        "unit": "원",
    },
    {
        "id": "reserve_money",
        "name": "본원통화(평잔)",
        "aliases": ["본원통화", "reserve_money", "중앙은행부채"],
        "stat_code": "102Y004",
        "stat_name": "1.1.1.1.1. 본원통화 구성내역(평잔, 계절조정계열)",
        "cycle": "M",
        "item_code1": "ABA1",
        "item_name1": "본원통화(평잔,계절조정계열)",
        "unit": "십억원",
    },
    {
        "id": "m2",
        "name": "M2 광의통화",
        "aliases": ["m2", "광의통화", "통화량", "m2통화량"],
        "stat_code": "161Y006",
        "stat_name": "1.1.3.1.2. M2 상품별 구성내역(평잔, 원계열)",
        "cycle": "M",
        "item_code1": "BBHA00",
        "item_name1": "M2(광의통화, 평잔)",
        "unit": "십억원",
    },
    {
        "id": "treasury_3y",
        "name": "국고채 3년 수익률",
        "aliases": ["국고채", "국고채3년", "채권금리", "시장금리", "treasury"],
        "stat_code": "817Y002",
        "stat_name": "1.3.2.1. 시장금리(일별)",
        "cycle": "D",
        "item_code1": "010200000",
        "item_name1": "국고채(3년)",
        "unit": "연%",
    },
    {
        "id": "ppi",
        "name": "생산자물가지수(PPI)",
        "aliases": ["생산자물가지수", "생산자물가", "ppi"],
        "stat_code": "404Y014",
        "stat_name": "4.1.1. 생산자물가지수",
        "cycle": "M",
        "item_code1": "*AA",
        "item_name1": "총지수",
        "unit": "2015=100",
    },
]


def find_popular_indicator(keyword: str) -> dict[str, Any] | None:
    """Find a popular indicator by name, alias, or ID.

    Args:
        keyword: Search query (e.g. '기준금리', 'GDP', '물가', '환율')

    Returns:
        Indicator preset dict or None if not matched
    """
    clean_kw = keyword.strip().lower().replace("/", "").replace(" ", "").replace("_", "")
    for ind in POPULAR_INDICATORS:
        if clean_kw == ind["id"].lower() or clean_kw in ind["name"].lower().replace("/", "").replace(" ", ""):
            return ind
        for alias in ind.get("aliases", []):
            if clean_kw == alias.lower().replace("/", "").replace(" ", ""):
                return ind
    return None
