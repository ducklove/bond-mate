"""한국은행 ECOS 소스 — 한국 국고채 전 만기와 무보증 회사채.

CNBC 는 한국물을 5·10·50년만 준다. 국고채 2·3·20·30년과 통안채, KOFR·CD(91일),
그리고 **신용등급별 회사채(AA-/BBB- 3년)** 는 ECOS 가 사실상 유일한 공개
일간 소스다. 통계표 ``817Y002``(시장금리, 일별) 하나에 모두 들어 있어 요청
한 번으로 받는다.

``ECOS_API_KEY`` 가 없으면 조용히 빈 결과를 돌려준다 — 키 없이도 나머지
소스만으로 서비스가 서도록.

ECOS 일별 금리는 직전 영업일 기준으로 공표된다(당일 장중값이 아님).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta

from bondmate.http import SourceError, fetch

logger = logging.getLogger(__name__)

BASE_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
MARKET_RATE_STAT = "817Y002"    # 시장금리(일별) — 국고채·회사채·단기금리
POLICY_RATE_STAT = "722Y001"    # 한국은행 기준금리 등 정책금리
MAX_ROWS = 10000

# ECOS ITEM_CODE1 → bond-mate 시리즈 ID (통계표 817Y002).
ITEMS = {
    "010901000": "KR_ON",       # KOFR (공시 무위험지표금리)
    "010502000": "KR3M",        # CD(91일)
    "010151000": "KR6M",        # KORIBOR(6개월) — 국고채 6M 이 없어 대용
    "010190000": "KR1Y",        # 국고채(1년)
    "010195000": "KR2Y",        # 국고채(2년)
    "010200000": "KR3Y",        # 국고채(3년)
    "010200001": "KR5Y",        # 국고채(5년)
    "010210000": "KR10Y",       # 국고채(10년)
    "010220000": "KR20Y",       # 국고채(20년)
    "010230000": "KR30Y",       # 국고채(30년)
    "010240000": "KR50Y",       # 국고채(50년)
}

# 신용등급별 회사채 — 미국 ICE BofA 커브의 한국 대응물.
CREDIT_ITEMS = {
    "010300000": "AA-",         # 회사채(무보증 3년, AA-)
    "010320000": "BBB-",        # 회사채(무보증 3년, BBB-)
}

# 통계표 722Y001. 기준금리는 시장금리표에 없어 따로 받아야 한다.
POLICY_ITEMS = {"0101000": "KR_BASE"}

# 기본 조회 구간 — 첫 실행에서 히스토리를 채우기 위해 넉넉히 잡는다.
DEFAULT_LOOKBACK_DAYS = 365 * 12


def api_key() -> str:
    return (os.getenv("ECOS_API_KEY") or "").strip()


def enabled() -> bool:
    return bool(api_key())


def _rows(stat_code: str, since: date, until: date) -> list[dict]:
    url = (
        f"{BASE_URL}/{api_key()}/json/kr/1/{MAX_ROWS}/"
        f"{stat_code}/D/{since:%Y%m%d}/{until:%Y%m%d}"
    )
    resp = fetch(url)
    try:
        payload = json.loads(resp.text)
    except json.JSONDecodeError as exc:
        raise SourceError("ECOS: JSON 아님") from exc
    if "RESULT" in payload:      # 키 오류·조회 없음은 이 형태로 온다.
        raise SourceError(f"ECOS: {payload['RESULT'].get('MESSAGE', '조회 실패')}")
    return (payload.get("StatisticSearch") or {}).get("row") or []


def _group(rows: list[dict], mapping: dict[str, str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        series = mapping.get(str(row.get("ITEM_CODE1") or ""))
        stamp, raw = row.get("TIME"), row.get("DATA_VALUE")
        if not series or not stamp or raw in (None, ""):
            continue
        stamp = str(stamp)
        if len(stamp) != 8:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        out.setdefault(series, {})[f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"] = value
    return out


def collect(*, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> tuple[dict, dict]:
    """``(국채·정책금리, 등급별 회사채)``. 키가 없으면 둘 다 빈 딕셔너리."""
    if not enabled():
        logger.info("ECOS_API_KEY 미설정 — 한국 국고채 전 만기·회사채는 건너뜀")
        return {}, {}

    until = date.today()
    since = until - timedelta(days=lookback_days)
    rates: dict[str, dict[str, float]] = {}
    credit: dict[str, dict[str, float]] = {}

    def absorb(stat_code: str, mappings: list[tuple[dict, dict]]) -> None:
        """한 요청의 행 수가 제한돼 있어 긴 구간은 1년 단위로 나눠 받는다."""
        window_start = since
        while window_start <= until:
            window_end = min(until, window_start + timedelta(days=365))
            try:
                rows = _rows(stat_code, window_start, window_end)
            except SourceError as exc:
                logger.warning("ECOS %s %s~%s 건너뜀 — %s", stat_code, window_start, window_end, exc)
            else:
                for mapping, target in mappings:
                    for series, points in _group(rows, mapping).items():
                        target.setdefault(series, {}).update(points)
            window_start = window_end + timedelta(days=1)

    absorb(MARKET_RATE_STAT, [(ITEMS, rates), (CREDIT_ITEMS, credit)])
    absorb(POLICY_RATE_STAT, [(POLICY_ITEMS, rates)])
    return rates, credit
