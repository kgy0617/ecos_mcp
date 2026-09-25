"""Async HTTP client for the ECOS (Bank of Korea) Open API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import urllib.parse

import httpx

from ecos_mcp.config import (
    ECOS_API_KEY,
    ECOS_BASE_URL,
    ECOS_ERROR_MAP,
    ECOS_RESPONSE_TYPE,
    SAMPLE_KEY_MAX_COUNT,
)


class EcosApiError(Exception):
    """Raised when the ECOS API returns an error response or network fails."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        friendly = ECOS_ERROR_MAP.get(code, "")
        full_message = f"[{code}] {message}"
        if friendly:
            full_message += f" — {friendly}"
        super().__init__(full_message)


class EcosClient:
    """Async client for the ECOS Open API.

    All API responses are requested as JSON. The client handles URL construction,
    safe path encoding, response parsing, error detection, sample-key clamping,
    and cached table search.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = ECOS_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or ECOS_API_KEY
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=timeout)
        self._tables_cache: list[dict[str, Any]] | None = None

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    # ── Internal helpers ──────────────────────────────────────────────

    def _build_url(self, *path_segments: str) -> str:
        """Build a full ECOS API URL from path segments.

        URL pattern:
        {base}/{ServiceName}/{ApiKey}/{Type}/{Language}/{StartCount}/{EndCount}/...
        Each segment is sanitized (slashes replaced with space to prevent BOK WAF 503)
        and properly URL-encoded.
        """
        clean_segments = [
            urllib.parse.quote(str(seg).replace("/", " ").strip(), safe="")
            for seg in path_segments
        ]
        return f"{self.base_url}/" + "/".join(clean_segments)

    @staticmethod
    def _extract_result(
        data: dict[str, Any], service_name: str
    ) -> tuple[int, list[dict[str, Any]]]:
        """Extract total_count and row list from ECOS JSON responses.

        ECOS responses are wrapped like:
        {
            "ServiceName": {
                "list_total_count": N,
                "row": [...]
            }
        }
        """
        # Check for top-level error response
        if "RESULT" in data:
            result = data["RESULT"]
            raise EcosApiError(
                code=result.get("CODE", "UNKNOWN"),
                message=result.get("MESSAGE", "Unknown error"),
            )

        service_data = data.get(service_name)
        if service_data is None:
            raise EcosApiError(
                code="PARSE_ERROR",
                message=f"예상치 못한 응답 구조입니다. '{service_name}' 키가 누락되었습니다.",
            )

        # Check for nested error
        if "RESULT" in service_data:
            result_code = service_data["RESULT"].get("CODE", "")
            if result_code and not result_code.startswith("INFO-000"):
                raise EcosApiError(
                    code=result_code,
                    message=service_data["RESULT"].get("MESSAGE", ""),
                )

        total_count = int(service_data.get("list_total_count", 0))
        rows = service_data.get("row", [])
        return total_count, rows

    async def _request(
        self,
        service_name: str,
        language: str,
        start_count: int,
        end_count: int,
        *extra_params: str,
    ) -> dict[str, Any]:
        """Make a request to the ECOS API and return parsed result dict."""
        is_sample = self.api_key == "sample"
        clamped = False

        # sample key only allows up to 10 items per call
        if is_sample and (end_count - start_count + 1 > SAMPLE_KEY_MAX_COUNT):
            end_count = start_count + SAMPLE_KEY_MAX_COUNT - 1
            clamped = True

        url = self._build_url(
            service_name,
            self.api_key,
            ECOS_RESPONSE_TYPE,
            language,
            str(start_count),
            str(end_count),
            *extra_params,
        )

        try:
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as e:
            raise EcosApiError(
                code="TIMEOUT",
                message=f"ECOS API 서버 응답 시간 초과 (30초): {e}",
            ) from e
        except httpx.HTTPStatusError as e:
            raise EcosApiError(
                code=f"HTTP_{e.response.status_code}",
                message=f"ECOS 서버 HTTP 에러: {e}",
            ) from e
        except httpx.RequestError as e:
            raise EcosApiError(
                code="NETWORK_ERROR",
                message=f"ECOS 서버와 통신할 수 없습니다: {e}",
            ) from e

        total_count, rows = self._extract_result(data, service_name)

        result: dict[str, Any] = {
            "total_count": total_count,
            "count": len(rows),
            "start_count": start_count,
            "end_count": end_count,
            "rows": rows,
        }
        if clamped:
            result["note"] = (
                "API 인증키가 'sample'이므로 1회 최대 조회 한도(10건)로 자동 제한되었습니다. "
                "전체 조회를 원하시면 ECOS에서 무료 인증키를 발급받아 ECOS_API_KEY에 설정하세요."
            )
        return result

    # ── Table Cache Helper ───────────────────────────────────────────

    def _load_tables_cache(self) -> list[dict[str, Any]]:
        """Load the pre-indexed statistical table metadata."""
        if self._tables_cache is None:
            cache_file = Path(__file__).parent / "tables.json"
            if cache_file.exists():
                with open(cache_file, "r", encoding="utf-8") as f:
                    self._tables_cache = json.load(f)
            else:
                self._tables_cache = []
        return self._tables_cache

    # ── Public API methods ────────────────────────────────────────────

    async def get_key_statistics(
        self,
        language: str = "kr",
        start_count: int = 1,
        end_count: int = 100,
    ) -> dict[str, Any]:
        """Fetch the top 100 key economic indicators."""
        return await self._request(
            "KeyStatisticList", language, start_count, end_count
        )

    async def list_statistic_tables(
        self,
        stat_code: str | None = None,
        searchable_only: bool = False,
        language: str = "kr",
        start_count: int = 1,
        end_count: int = 100,
    ) -> dict[str, Any]:
        """List available statistical tables.

        Args:
            stat_code: Optional statistic table code to filter children by.
            searchable_only: If True, returns only searchable tables (SRCH_YN == 'Y').
            language: kr or en.
            start_count: Start 1-based index.
            end_count: End index.
        """
        extra = [stat_code] if stat_code else []
        result = await self._request(
            "StatisticTableList", language, start_count, end_count, *extra
        )
        if searchable_only:
            filtered_rows = [r for r in result["rows"] if r.get("SRCH_YN") == "Y"]
            result["rows"] = filtered_rows
            result["count"] = len(filtered_rows)
        return result

    def search_statistic_tables(
        self,
        keyword: str,
        searchable_only: bool = True,
        limit: int = 30,
    ) -> dict[str, Any]:
        """Search statistical tables by name using pre-indexed table metadata.

        This provides instant keyword discovery across all 844+ ECOS tables.

        Args:
            keyword: Search query (e.g., '물가', '금리', '환율', 'GDP').
            searchable_only: If True, returns only tables where SRCH_YN == 'Y'.
            limit: Maximum number of results to return.
        """
        tables = self._load_tables_cache()
        keyword_lower = keyword.strip().lower()

        matches: list[dict[str, Any]] = []
        for t in tables:
            name = t.get("STAT_NAME", "")
            code = t.get("STAT_CODE", "")
            if keyword_lower in name.lower() or keyword_lower in code.lower():
                if searchable_only and t.get("SRCH_YN") != "Y":
                    continue
                matches.append(t)
                if len(matches) >= limit:
                    break

        return {
            "query": keyword,
            "total_matches": len(matches),
            "searchable_only": searchable_only,
            "rows": matches,
        }

    async def search_statistic_word(
        self,
        word: str,
        language: str = "kr",
        start_count: int = 1,
        end_count: int = 10,
    ) -> dict[str, Any]:
        """Search the statistical terminology dictionary."""
        return await self._request(
            "StatisticWord", language, start_count, end_count, word
        )

    async def list_statistic_items(
        self,
        stat_code: str,
        language: str = "kr",
        start_count: int = 1,
        end_count: int = 100,
    ) -> dict[str, Any]:
        """List sub-items for a specific statistical table."""
        return await self._request(
            "StatisticItemList", language, start_count, end_count, stat_code
        )

    async def search_statistics(
        self,
        stat_code: str,
        cycle: str,
        start_date: str,
        end_date: str,
        item_code1: str | None = None,
        item_code2: str | None = None,
        item_code3: str | None = None,
        item_code4: str | None = None,
        language: str = "kr",
        start_count: int = 1,
        end_count: int = 1000,
    ) -> dict[str, Any]:
        """Search for time-series statistical data."""
        extra: list[str] = [stat_code, cycle, start_date, end_date]

        # Item codes: must be provided in order; use "?" wildcard for intermediate skips
        item_codes = [item_code1, item_code2, item_code3, item_code4]
        # Trim trailing None values
        while item_codes and item_codes[-1] is None:
            item_codes.pop()
        for code in item_codes:
            extra.append(code if code is not None else "?")

        return await self._request(
            "StatisticSearch", language, start_count, end_count, *extra
        )

    async def get_statistic_meta(
        self,
        data_name: str,
        language: str = "kr",
        start_count: int = 1,
        end_count: int = 100,
    ) -> dict[str, Any]:
        """Get metadata for a statistical dataset."""
        return await self._request(
            "StatisticMeta", language, start_count, end_count, data_name
        )
