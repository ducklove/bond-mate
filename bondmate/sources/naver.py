"""네이버 금융 환율 소스 — 원화 크로스의 **당일** 고시 환율.

FRED 의 ``DEX*`` 시리즈는 주 1회 공표라 최대 일주일까지 밀린다. 긴 히스토리는
FRED 가 채우고(:mod:`bondmate.sources.fred`), 최근 며칠은 여기서 덮어써
스냅샷이 낡아 보이지 않게 한다.

``exchangeDailyQuote`` 는 한 페이지에 영업일 10일치를 날짜와 함께 주므로
몇 페이지만 받아도 FRED 의 지연 구간을 충분히 덮는다. 인코딩은 euc-kr.
"""

from __future__ import annotations

import logging
import re

from bondmate.http import SourceError, fetch

logger = logging.getLogger(__name__)

DAILY_URL = "https://finance.naver.com/marketindex/exchangeDailyQuote.naver"

# 네이버 marketindexCd → bond-mate 통화쌍. 엔화는 네이버도 100엔 기준이라
# 카탈로그의 ``scale: 100`` 과 그대로 맞는다.
PAIRS = {
    "USD_KRW": "FX_USDKRW",
    "EUR_KRW": "FX_EURKRW",
    "JPY_KRW": "FX_JPYKRW",
    "CNY_KRW": "FX_CNYKRW",
    "GBP_KRW": "FX_GBPKRW",
    "AUD_KRW": "FX_AUDKRW",
    "CAD_KRW": "FX_CADKRW",
    "CHF_KRW": "FX_CHFKRW",
}

# 페이지당 영업일 10일 — 3페이지면 약 6주로 FRED 지연을 넉넉히 덮는다.
DEFAULT_PAGES = 3

_ROW = re.compile(
    r'<td class="date">\s*([\d.]+)\s*</td>\s*<td class="num">\s*([\d,.]+)\s*</td>'
)


def parse_page(html: str) -> dict[str, float]:
    """``2026.08.28 / 1,380.50`` 행들을 ``{ISO날짜: 값}`` 으로."""
    out: dict[str, float] = {}
    for raw_date, raw_value in _ROW.findall(html):
        parts = raw_date.strip().strip(".").split(".")
        if len(parts) != 3:
            continue
        try:
            out[f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"] = float(
                raw_value.replace(",", "")
            )
        except ValueError:
            continue
    return out


def fetch_pair(market_code: str, *, pages: int = DEFAULT_PAGES) -> dict[str, float]:
    points: dict[str, float] = {}
    for page in range(1, pages + 1):
        resp = fetch(DAILY_URL, params={"marketindexCd": market_code, "page": page})
        parsed = parse_page(resp.content.decode("euc-kr", errors="ignore"))
        if not parsed:
            break               # 더 받아도 빈 페이지 — 여기서 멈춘다.
        points.update(parsed)
    if not points:
        raise SourceError(f"네이버 {market_code}: 파싱된 행 없음")
    return points


def collect(pairs: list[str] | None = None, *, pages: int = DEFAULT_PAGES) -> dict[str, dict[str, float]]:
    """통화쌍 하나가 실패해도 나머지는 살린다."""
    wanted = {p: PAIRS[p] for p in (pairs or PAIRS) if p in PAIRS}
    out: dict[str, dict[str, float]] = {}
    for pair, market_code in wanted.items():
        try:
            out[pair] = fetch_pair(market_code, pages=pages)
        except SourceError as exc:
            logger.warning("네이버 %s 건너뜀 — %s", pair, exc)
    if not out:
        raise SourceError("네이버: 수집된 통화쌍 없음")
    return out
