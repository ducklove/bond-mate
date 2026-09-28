"""네이버 환율 JSON API — 하나은행의 최신 고시와 최근 일별 환율.

구 exchangeDailyQuote HTML 주소는 HTTP 410으로 종료됐다.
엔화는 원본과 화면 모두 100엔 기준이며, 시세 시각을 수집 시각으로 바꾸지 않는다.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime

from bondmate.http import SourceError, fetch

logger = logging.getLogger(__name__)
BASE_URL = "https://api.stock.naver.com/marketindex/exchange"
PAIRS = {
    "USD_KRW": "FX_USDKRW", "EUR_KRW": "FX_EURKRW", "JPY_KRW": "FX_JPYKRW",
    "CNY_KRW": "FX_CNYKRW", "GBP_KRW": "FX_GBPKRW", "AUD_KRW": "FX_AUDKRW",
    "CAD_KRW": "FX_CADKRW", "CHF_KRW": "FX_CHFKRW",
}
DEFAULT_PAGES = 3


def number(raw) -> float:
    value = float(str(raw).replace(",", ""))
    if not math.isfinite(value):
        raise ValueError("비유한값")
    return value


def parse_prices(rows) -> dict[str, float]:
    if not isinstance(rows, list):
        raise SourceError("네이버: 일별 환율 배열 없음")
    points = {}
    for row in rows:
        try:
            day = date.fromisoformat(row["localTradedAt"][:10]).isoformat()
            value = number(row["closePrice"])
            if value > 0:
                points[day] = value
        except (KeyError, TypeError, ValueError):
            continue
    return points


def parse_quote(payload) -> dict:
    try:
        info = payload["exchangeInfo"]
        stamp = datetime.fromisoformat(info["localTradedAt"])
        value = number(info["closePrice"])
        if not stamp.tzinfo or value <= 0:
            raise ValueError("시세 시각/값 오류")
        quote = {"date": stamp.date().isoformat(), "value": value,
                 "as_of": stamp.isoformat(timespec="seconds"), "source": "naver",
                 "quote_type": "하나은행 고시"}
        # 같은 날 재수집해도 전일대비는 원본의 직전 영업일 기준을 유지한다.
        if info.get("fluctuations") is not None:
            quote["change"] = number(info["fluctuations"])
        if info.get("fluctuationsRatio") is not None:
            quote["change_pct"] = number(info["fluctuationsRatio"])
        return quote
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceError("네이버: 유효한 최신 고시 없음") from exc


def fetch_pair(market_code: str, *, pages: int = DEFAULT_PAGES,
               quote_metadata: dict | None = None) -> dict[str, float]:
    points = {}
    # 일별 조회 실패 시에도 최신 고시는 살린다.
    try:
        rows = fetch(f"{BASE_URL}/{market_code}/prices",
                     params={"page": 1, "pageSize": pages * 10}).json()
        points.update(parse_prices(rows))
    except (SourceError, ValueError) as exc:
        logger.warning("네이버 %s 일별 환율 실패 — %s", market_code, exc)
    try:
        quote = parse_quote(fetch(f"{BASE_URL}/{market_code}").json())
        points[quote["date"]] = quote["value"]
        if quote_metadata is not None:
            quote_metadata.update(quote)
    except (SourceError, ValueError) as exc:
        logger.warning("네이버 %s 최신 고시 실패 — %s", market_code, exc)
    if not points:
        raise SourceError(f"네이버 {market_code}: 유효 환율 없음")
    return points


def collect(pairs: list[str] | None = None, *, pages: int = DEFAULT_PAGES,
            quote_metadata: dict | None = None) -> dict[str, dict[str, float]]:
    out = {}
    for pair in pairs if pairs is not None else PAIRS:
        if pair not in PAIRS:
            continue
        meta = {}
        try:
            out[pair] = fetch_pair(PAIRS[pair], pages=pages, quote_metadata=meta)
            if meta and quote_metadata is not None:
                quote_metadata[pair] = meta
        except SourceError as exc:
            logger.warning("네이버 %s 건너뜀 — %s", pair, exc)
    if not out:
        raise SourceError("네이버: 수집된 통화쌍 없음")
    return out
