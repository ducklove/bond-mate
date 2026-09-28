"""CNBC 시세 소스 — 각국 국채의 **당일** 수익률.

FRED 의 ``IRLTLT01*`` 는 월간이라 두 달쯤 지연된다. 장기 히스토리는 FRED 가
채우고, 오늘자 스냅샷은 여기서 받아 둘을 합친다(:mod:`bondmate.build`).

심볼 표기는 value-invest ``market_indicators._CNBC_BOND_MAP`` 과 동일하게
유지한다 — 두 서비스가 같은 값을 보여야 하기 때문이다.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime

from bondmate.http import SourceError, fetch

logger = logging.getLogger(__name__)

QUOTE_URL = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"

SYMBOLS = {
    "US3M": "US3M", "US6M": "US6M", "US1Y": "US1Y", "US2Y": "US2Y",
    "US3Y": "US3Y", "US5Y": "US5Y", "US10Y": "US10Y", "US20Y": "US20Y", "US30Y": "US30Y",
    "KR3Y": "KR3Y-KR", "KR5Y": "KR5Y-KR", "KR10Y": "KR10Y-KR", "KR50Y": "KR50Y-KR",
    "JP3M": "JP3M-JP", "JP6M": "JP6M-JP", "JP2Y": "JP2Y-JP", "JP3Y": "JP3Y-JP",
    "JP5Y": "JP5Y-JP", "JP10Y": "JP10Y-JP", "JP20Y": "JP20Y-JP", "JP30Y": "JP30Y-JP",
    "JP40Y": "JP40Y-JP",
    "DE10Y": "DE10Y-DE", "FR10Y": "FR10Y-FR", "GB10Y": "UK10Y-GB", "AU10Y": "AU10Y-AU",
    "CN10Y": "CN10Y-CN", "IT10Y": "IT10Y-IT", "ES10Y": "ES10Y-ES", "CH10Y": "CH10Y-CH",
    "CA10Y": "CA10Y-CA", "IN10Y": "IN10Y-IN", "ID10Y": "ID10Y-ID", "BR10Y": "BR10Y-BR",
    "MX10Y": "MX10Y-MX",
}

# CNBC 는 한 요청에 심볼을 파이프로 이어 받는다. 너무 길면 잘리므로 나눠 보낸다.
BATCH_SIZE = 20

# 통화쌍 방향은 CNBC의 상품명과 일치한다. USD_IDX는 FRED의 광의 달러지수라
# ICE DXY로 대체하지 않는다(서로 다른 지수).
FX_SYMBOLS = {
    "USD_JPY": "JPY=", "EUR_USD": "EUR=", "GBP_USD": "GBP=", "USD_CNY": "CNY=",
    "USD_INR": "INR=", "USD_BRL": "BRL=", "USD_MXN": "MXN=",
}


def _parse_last(quote: dict) -> float | None:
    raw = str(quote.get("last", "")).strip().rstrip("%").strip().replace(",", "")
    try:
        value = float(raw)
        return value if math.isfinite(value) else None
    except ValueError:
        return None


def _quote_date(quote: dict) -> str | None:
    """CNBC ``last_time`` 은 ``2026-08-28T16:59:00.000-0400`` 형태."""
    raw = str(quote.get("last_time") or "").strip()
    return raw[:10] if len(raw) >= 10 and raw[4] == "-" else None


def fetch_quotes(codes: list[str] | None = None) -> dict[str, dict]:
    """``{시리즈ID: {"value": float, "date": "YYYY-MM-DD"|None}}``."""
    wanted = {c: SYMBOLS[c] for c in (codes or SYMBOLS) if c in SYMBOLS}
    return _fetch_quotes(wanted)


def fetch_fx_quotes() -> dict[str, dict]:
    return _fetch_quotes(FX_SYMBOLS)


def _fetch_quotes(wanted: dict[str, str]) -> dict[str, dict]:
    if not wanted:
        return {}

    symbols = list(wanted.values())
    reverse = {sym: code for code, sym in wanted.items()}
    out: dict[str, dict] = {}

    for start in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[start : start + BATCH_SIZE]
        try:
            resp = fetch(
                QUOTE_URL,
                params={
                    "symbols": "|".join(batch),
                    "requestMethod": "itv",
                    "noform": "1",
                    "partnerId": "2",
                    "fund": "1",
                    "exthrs": "1",
                    "output": "json",
                },
                headers={"Accept": "application/json"},
            )
            payload = json.loads(resp.text)
        except (SourceError, json.JSONDecodeError) as exc:
            logger.warning("CNBC 배치 건너뜀(%s…) — %s", batch[0], exc)
            continue

        quotes = payload.get("FormattedQuoteResult", {}).get("FormattedQuote") or []
        for quote in quotes:
            code = reverse.get(quote.get("symbol"))
            value = _parse_last(quote) if code else None
            if code and value is not None:
                out[code] = {"value": value, "date": _quote_date(quote)}
                if code in FX_SYMBOLS:
                    try:
                        stamp = datetime.fromisoformat(str(quote.get("last_time") or ""))
                        if not stamp.tzinfo or value <= 0:
                            raise ValueError("시각/환율 오류")
                    except ValueError:
                        del out[code]
                        continue
                    out[code].update(as_of=stamp.isoformat(timespec="seconds"), source="cnbc",
                                     quote_type="시장 환율")
                    for field in ("change", "change_pct"):
                        parsed = _parse_last({"last": quote.get(field)})
                        if parsed is not None:
                            out[code][field] = parsed

    if not out:
        raise SourceError("CNBC: 파싱된 시세 없음")
    return out
