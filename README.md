# 🏦 ECOS MCP Server

한국은행 경제통계시스템(ECOS) Open API를 위한 최신 MCP(Model Context Protocol) 서버입니다.

AI 에이전트(Claude Desktop, Cursor 등)가 한국 거시경제 통계 데이터를 자연어로 실시간 검색하고 고효율 시계열 분석을 수행할 수 있게 해줍니다.

---

## ✨ 핵심 기능

### 🛠️ MCP Tools (8개)

| Tool | 설명 | 주요 특징 |
|------|------|-----------|
| `get_popular_statistic` | **1-Shot 인기 지표 즉시 조회** (NEW) | 기준금리, GDP, 물가, 환율 등을 코드 검색 없이 한 번의 호출로 즉시 조회 |
| `search_statistics` | **통계 시계열 데이터 조회** (핵심) | 스마트 날짜 자동 추정, 날짜 규격 검증, 컴팩트/CSV 포맷 지원 |
| `search_statistic_tables` | **통계표 키워드 검색** | 844개 전체 통계표 대상 초고속 이름 검색 ("물가", "금리", "GDP" 등) |
| `get_key_statistics` | 100대 주요 경제지표 조회 | GDP, 기준금리, 환율, 통화량 등 실시간 핵심 지표 |
| `list_statistic_tables` | 통계표 목록/계층 구조 조회 | 상위 분류별 계층 탐색 및 실제 조회 가능 표(`SRCH_YN='Y'`) 필터 |
| `search_statistic_word` | 통계 용어 사전 검색 | 한국은행 공식 용어 해설 (슬래시 등 특수문자 안전 인코딩) |
| `list_statistic_items` | 통계표 세부항목 목록 조회 | 특정 통계표의 항목코드, 지원 주기, 수록 기간 확인 |
| `get_statistic_meta` | 통계 메타데이터 조회 | 통계 작성 배경, 작성 주기, 편제 기준 등 상세 메타정보 |

### ⚡ 토큰 최적화 포맷 (`format`)

시계열 데이터 조회(`search_statistics`, `get_popular_statistic`) 시 토큰 소모를 극적으로 줄일 수 있습니다:

- **`format="compact"`** (기본값): 중복 메타데이터와 null 필드를 제거한 깔끔한 JSON (**토큰 ~70% 절감**)
- **`format="csv"`**: CSV 텍스트 포맷으로 차트 생성 및 장기 시계열 분석에 최적 (**토큰 ~85% 절감**)
- **`format="json"`**: ECOS 공식 전체 원본 JSON

### 🗓️ 스마트 날짜 자동 추정 (Smart Date Fallback)

`start_date`나 `end_date`를 지정하지 않으면, 주기에 맞춰 **최근 2년치 데이터 범위가 자동으로 계산**되어 즉시 반환됩니다.

---

## 📚 MCP Resources & Prompts

### Resources
- `ecos://popular-indicators`: 한국은행 주요 핵심 경제지표(기준금리, 실질 GDP, 소비자물가지수, 환율, M2 등) 프리셋 매핑표
- `ecos://date-format-guide`: 주기(Cycle)별 올바른 날짜 포맷 규격 안내서

### Prompts
- `macro-economic-briefing`: 100대 지표 기반 대한민국 경제 현황 종합 분석 및 브리핑 보고서
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

| 지표명 | 키워드(별칭) | 통계표코드 | 주기 | 항목코드 |
|--------|-------------|:---:|:---:|:---:|
| **한국은행 기준금리** | `기준금리`, `금리`, `base_rate` | `722Y001` | `D` | `0101000` |
| **실질 GDP(분기)** | `GDP`, `실질GDP`, `국내총생산` | `200Y108` | `Q` | `10601` |
| **소비자물가지수(CPI)** | `CPI`, `소비자물가`, `물가` | `901Y009` | `M` | `0` |
| **원/달러 환율** | `환율`, `원달러`, `달러`, `USD` | `731Y001` | `D` | `0000001` |
| **본원통화(평잔)** | `본원통화`, `reserve_money` | `102Y004` | `M` | `ABA1` |
| **M2 광의통화** | `M2`, `통화량`, `광의통화` | `161Y006` | `M` | `BBHA00` |
| **국고채(3년) 수익률** | `국고채`, `국고채3년`, `채권금리` | `817Y002` | `D` | `010200000` |
| **생산자물가지수(PPI)** | `PPI`, `생산자물가` | `404Y014` | `M` | `*AA` |

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

### 1. 인기 지표 원스톱 조회 (1-Shot)
> "최근 기준금리 추이 보여줘"
* `get_popular_statistic(indicator="기준금리", recent_years=2)` 한 번으로 2년치 데이터 즉시 반환

### 2. CSV 포맷으로 차트 그리기
> "소비자물가지수 최근 3년치 CSV로 뽑아서 분석해줘"
* `get_popular_statistic(indicator="CPI", recent_years=3, format="csv")`

### 3. 통계표 검색 후 세부 항목 분석
> "생산자물가지수 농림수산품 추이 보여줘"
1. `search_statistic_tables("생산자물가")` → `STAT_CODE="404Y014"`
2. `list_statistic_items("404Y014")` → 농림수산품 항목코드 확인
3. `search_statistics(stat_code="404Y014", cycle="M", item_code1="...")`

---

## 🧪 테스트 실행

```bash
uv run python test_smoke.py
```
10개 핵심 기능(100대 지표, 키워드 검색, 계층 조회, 용어, 항목, 시계열, 메타, 날짜 검증, 스마트 날짜, 컴팩트/CSV 포맷)을 종합 검증합니다.

---

## 📝 라이선스

MIT License
