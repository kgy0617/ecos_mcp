# 🏦 ECOS MCP Server

한국은행 경제통계시스템(ECOS) Open API를 위한 최신 MCP(Model Context Protocol) 서버입니다.

AI 에이전트(Claude Desktop, Cursor 등)가 한국 거시경제 통계 데이터를 자연어로 실시간 검색하고 고효율 시계열 분석을 수행할 수 있게 해줍니다.

---

## ✨ 핵심 기능

### 🛠️ MCP Tools (7개)

모든 도구는 읽기 전용(`readOnlyHint`)으로 표시되어 있고, 실패 시 MCP 표준 에러(`isError: true`)를 반환합니다.

| Tool | 설명 | 주요 특징 |
|------|------|-----------|
| `get_popular_statistic` | **1-Shot 인기 지표 즉시 조회** | 기준금리, 성장률, 물가상승률, 환율 등을 코드 검색 없이 한 번의 호출로 조회 |
| `search_statistics` | **통계 시계열 데이터 조회** (핵심) | 스마트 날짜, 최신 구간 우선, 증감률 계산(`transform`), 컴팩트/CSV 포맷 |
| `search_statistic_tables` | **통계표 검색·계층 탐색** | 로컬 인덱스로 즉시 응답. 띄어쓰기 무시·다중 단어·관련도 순 정렬, `parent_code`로 분류 트리 탐색 |
| `get_key_statistics` | 100대 주요 경제지표 조회 | GDP, 기준금리, 환율, 통화량 등 실시간 핵심 지표 |
| `search_statistic_word` | 통계 용어 사전 검색 | 한국은행 공식 용어 해설 |
| `list_statistic_items` | 통계표 세부항목 목록 조회 | 항목코드, 지원 주기, 수록 기간, 단위 확인 (결과 캐시) |
| `get_statistic_meta` | 통계 메타데이터 조회 | 통계 작성 배경, 작성 주기, 편제 기준 등 (결과 캐시) |

### ⚡ 토큰 최적화 포맷 (`output_format`)

시계열 조회(`search_statistics`, `get_popular_statistic`) 결과는 공백 없는 JSON으로 반환됩니다.

- **`"compact"`** (기본값): 계열(항목)별로 이름·단위를 한 번만 쓰고 값은 `[시점, 값]` 배열로 반환
- **`"csv"`**: 한 줄에 관측치 하나. 여러 항목을 표·차트로 옮길 때 편리
- **`"json"`**: ECOS 원본 행 그대로

측정 예시(소비자물가지수 24개월 단일 계열, 문자 수 기준): 원본 JSON 6,545자 → compact 605자(약 91% 축소), csv 805자.

### 📈 증감률·변경 시점 (`transform`, `changes_only`)

- `transform="yoy"`: 전년동기대비 증감률(%) 열(`yoy_pct`) 추가. 기준 시점 데이터는 자동으로 함께 조회합니다.
- `transform="pop"`: 직전 관측치 대비 증감률(%) 열(`pop_pct`) 추가
- `changes_only=True`: 값이 바뀐 시점만 반환 (예: 일별 기준금리 2년치 약 500행 → 변경 시점 몇 행)

### 🗓️ 스마트 날짜 & 최신 구간 우선

- `start_date`/`end_date`를 생략하면 **일간(D)은 최근 3개월, 그 외 주기는 최근 2년**이 자동 설정됩니다.
- 결과가 한 번에 다 담기지 않으면(`end_count` 초과, sample 키는 10건) **가장 최근 구간**을 반환하고 `truncated: true`와 안내 문구를 붙입니다. 과거부터 페이지 단위로 받으려면 `prefer_latest=False`를 쓰세요.

---

## 📚 MCP Resources & Prompts

### Resources
- `ecos://popular-indicators`: 한국은행 주요 핵심 경제지표(기준금리, 실질 GDP, 소비자물가지수, 환율, M2 등) 프리셋 매핑표
- `ecos://date-format-guide`: 주기(Cycle)별 올바른 날짜 포맷 규격 안내서

### Prompts
- `macro-economic-briefing`: 100대 지표와 성장률·물가상승률·기준금리·환율 추이 기반 경제 현황 브리핑
- `analyze-economic-trend`: 특정 경제 지표(소비자물가지수 등) 시계열 추이 및 정책 시사점 심층 분석

---

## 📅 주기(Cycle)별 날짜 포맷 규칙

| 주기 코드 | 주기명 | 시작/종료일 포맷 규격 | 예시 |
|:---:|:---:|:---:|:---:|
| **`A`** | 연간 | `YYYY` | `"2020"`, `"2024"` |
| **`S`** | 반기 | `YYYYS1` / `YYYYS2` | `"2023S1"`, `"2023S2"` |
| **`Q`** | 분기 | `YYYYQ1` ~ `YYYYQ4` | `"2023Q1"`, `"2024Q3"` |
| **`M`** | 월간 | `YYYYMM` | `"202401"`, `"202412"` |
| **`SM`** | 반월 | `YYYYMMS1` / `YYYYMMS2` | `"202401S1"`, `"202401S2"` |
| **`D`** | 일간 | `YYYYMMDD` | `"20240101"`, `"20240315"` |

---

## 📌 주요 인기 통계표 프리셋

| 지표명 | 키워드(별칭) | 통계표코드 | 주기 | 항목코드 | 기본 처리 |
|--------|-------------|:---:|:---:|:---:|:---:|
| **한국은행 기준금리** | `기준금리`, `금리`, `base_rate` | `722Y001` | `D` | `0101000` | 변경 시점만 |
| **경제성장률(실질, 전기비 %)** | `성장률`, `경제성장률`, `GDP성장률` | `200Y102` | `Q` | `10111` | |
| **실질 GDP(분기, 십억원)** | `GDP`, `실질GDP`, `국내총생산` | `200Y108` | `Q` | `10601` | |
| **소비자물가상승률(%)** | `물가상승률`, `인플레이션` | `901Y009` | `M` | `0` | `yoy` |
| **소비자물가지수(CPI)** | `CPI`, `소비자물가`, `물가` | `901Y009` | `M` | `0` | |
| **원/달러 환율(일별)** | `환율`, `원달러`, `달러`, `USD` | `731Y001` | `D` | `0000001` | |
| **원/달러 환율(월평균)** | `월평균환율`, `usd_krw_monthly` | `731Y004` | `M` | `0000001`/`0000100` | |
| **본원통화(평잔)** | `본원통화`, `reserve_money` | `102Y004` | `M` | `ABA1` | |
| **M2 광의통화** | `M2`, `통화량`, `광의통화` | `161Y006` | `M` | `BBHA00` | |
| **국고채(3년) 수익률(일별)** | `국고채`, `국고채3년`, `채권금리` | `817Y002` | `D` | `010200000` | |
| **국고채(3년) 수익률(월평균)** | `국고채월평균`, `treasury_3y_monthly` | `721Y001` | `M` | `5020000` | |
| **생산자물가지수(PPI)** | `PPI`, `생산자물가` | `404Y014` | `M` | `*AA` | |

`"통화"`, `"지수"`처럼 여러 지표에 걸치는 키워드는 후보 목록을 담은 에러를 돌려주므로, 더 구체적인 키워드나 `id`를 쓰면 됩니다.

---

## 🚀 빠른 시작

### 1. 설치 (로컬 개발 시)
```bash
git clone https://github.com/kgy0617/ecos_mcp.git
cd ecos_mcp
uv sync
```

### 2. API 키 설정 (선택)
```bash
cp .env.example .env
# .env 파일에서 ECOS_API_KEY 입력 (미입력 시 sample 키 자동 적용)
```
> 💡 API 키 없이도 `sample` 키로 테스트 가능하며, 1회 최대 허용치(10건)로 자동 클램핑됩니다.

### 3. 자가 진단 헬스체크 실행
```bash
uv run ecos-mcp --check
```
네트워크 연결, API 키 상태, 통계표 인덱스 로드가 자동으로 진단됩니다.

---

## 🔧 MCP 클라이언트 설정

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`:

#### 방법 A: GitHub URL 직접 실행 (클론 불필요, 추천 ⭐)
```json
{
  "mcpServers": {
    "ecos": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/kgy0617/ecos_mcp", "ecos-mcp"],
      "env": {
        "ECOS_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

#### 방법 B: 로컬 클론 실행
```json
{
  "mcpServers": {
    "ecos": {
      "command": "uv",
      "args": ["--directory", "/path/to/ecos_mcp", "run", "ecos-mcp"],
      "env": {
        "ECOS_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add ecos -e ECOS_API_KEY=your_api_key_here -- uvx --from git+https://github.com/kgy0617/ecos_mcp ecos-mcp
```

### Cursor
Settings > Features > MCP Servers > Add New MCP Server:
- **방법 A (GitHub 직접 실행)**:
  - **Name**: `ecos`
  - **Type**: `command`
  - **Command**: `uvx --from git+https://github.com/kgy0617/ecos_mcp ecos-mcp`
- **방법 B (로컬 클론)**:
  - **Name**: `ecos`
  - **Type**: `command`
  - **Command**: `uv --directory /path/to/ecos_mcp run ecos-mcp`

---

## 📖 사용 예시

### 1. 인기 지표 원스톱 조회 (`get_popular_statistic`)
> **사용자**: "최근 한국 기준금리 어떻게 바뀌었어?"

**Tool 호출**:
```json
{
  "indicator": "기준금리",
  "recent_years": 2,
  "output_format": "compact"
}
```

**응답 예시** (일별 500여 행 대신 `changes_only=True`가 기본 적용되어 **금리 변동 시점만** 간결하게 반환):
```json
{
  "stat_code": "722Y001",
  "stat_name": "한국은행 기준금리 및 여수신금리",
  "indicator": "base_rate",
  "total_count": 500,
  "count": 3,
  "columns": ["time", "value"],
  "series": [
    {
      "item": "한국은행 기준금리",
      "item_code": "0101000",
      "unit": "연%",
      "data": [
        ["20230113", 3.5],
        ["20241011", 3.25],
        ["20241128", 3.0]
      ]
    }
  ]
}
```

---

### 2. 물가상승률 CSV 수신 후 차트 분석
> **사용자**: "소비자물가 상승률 최근 데이터 CSV로 뽑아서 분석해줘"

**Tool 호출**:
```json
{
  "indicator": "물가상승률",
  "recent_years": 1,
  "output_format": "csv"
}
```

**응답 예시** (`transform="yoy"`가 자동 적용되어 전년동기대비 증감률 열인 `YOY_PCT`가 포함됨):
```csv
# stat_code: 901Y009
# stat_name: 4.2.1. 소비자물가지수
# indicator: inflation_rate
# total_count: 12
# count: 12
TIME,ITEM_CODE,ITEM,VALUE,UNIT,YOY_PCT
202401,0,총지수,113.15,2020=100,2.8
202402,0,총지수,113.77,2020=100,3.1
202403,0,총지수,113.94,2020=100,3.1
202404,0,총지수,114.09,2020=100,2.9
202405,0,총지수,114.14,2020=100,2.7
...
```

---

### 3. 통계표 키워드 검색 및 계층 탐색 (`search_statistic_tables`)
> **사용자**: "소비자물가 관련 통계표 찾아줘"

**Tool 호출**:
```json
{
  "keyword": "소비자 물가",
  "searchable_only": true,
  "limit": 3
}
```

**응답 예시** (로컬 인덱스 기반으로 띄어쓰기 무시 및 관련도 순 정렬):
```json
{
  "query": "소비자 물가",
  "total_matches": 3,
  "count": 2,
  "searchable_only": true,
  "index_generated_at": "2026-09-26",
  "rows": [
    {
      "P_STAT_CODE": "0000000211",
      "STAT_CODE": "901Y009",
      "STAT_NAME": "4.2.1. 소비자물가지수",
      "CYCLE": "M",
      "SRCH_YN": "Y",
      "ORG_NAME": "국가데이터처(02-2012-9114)"
    },
    {
      "P_STAT_CODE": "0000000211",
      "STAT_CODE": "901Y010",
      "STAT_NAME": "4.2.2. 소비자물가지수(특수분류)",
      "CYCLE": "M",
      "SRCH_YN": "Y",
      "ORG_NAME": "국가데이터처(02-2012-9114)"
    }
  ]
}
```
*Tip*: `parent_code="0000000211"`를 지정하면 해당 분류의 하위 통계표 트리를 직접 탐색할 수도 있습니다.

---

### 4. 통계 용어 사전 검색 (`search_statistic_word`)
> **사용자**: "한국은행에서 정의하는 기준금리의 정확한 의미가 뭐야?"

**Tool 호출**:
```json
{
  "word": "기준금리"
}
```

**응답 예시**:
```json
{
  "total_count": 1,
  "count": 1,
  "rows": [
    {
      "WORD": "기준금리",
      "CONTENT": "한국은행이 금융기관과 환매조건부증권(RP) 매매, 자금조정 예금 및 대출 등의 거래를 할 때 기준이 되는 정책금리"
    }
  ]
}
```

---

## 🧪 테스트 실행

```bash
uv run pytest            # 오프라인 단위 테스트 (ECOS API를 모킹, 네트워크 불필요)
uv run pytest -m live    # 실제 ECOS API 호출 테스트 (모든 프리셋 조회 확인)
```

## 🗂️ 통계표 인덱스 갱신

`search_statistic_tables`는 패키지에 포함된 `tables.json`(생성일 기록됨)을 사용합니다. ECOS 통계표 목록이 바뀌면 다시 생성하세요.

```bash
ECOS_API_KEY=your_api_key_here uv run python scripts/update_tables.py
```

---

## 📝 라이선스

MIT License
