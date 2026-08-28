"""FRED(세인트루이스 연은) CSV 소스 — 히스토리의 백본.

``fredgraph.csv?id=<시리즈>`` 는 **API 키 없이** 전체 히스토리를 CSV 로 준다.
등급별 회사채 지수(ICE BofA)와 미국 국채 전 만기를 한 소스에서 일간으로
받을 수 있어 bond-mate 히스토리의 기준 소스로 쓴다.

한계 — 각국 10년물(``IRLTLT01*``)은 월간이고 두 달쯤 지연된다. 그래서 장기
히스토리는 FRED, 당일 값은 CNBC(:mod:`bondmate.sources.cnbc`)로 나눠 받는다.
"""

from __future__ import annotations

import csv
import io
import logging

from bondmate.http import SourceError, fetch

logger = logging.getLogger(__name__)

CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# --- 미국 국채 커브 + 단기 지표금리 (일간) -----------------------------------
TREASURY_SERIES = {
    "US1M": "DGS1MO",
    "US3M": "DGS3MO",
    "US6M": "DGS6MO",
    "US1Y": "DGS1",
    "US2Y": "DGS2",
    "US3Y": "DGS3",
    "US5Y": "DGS5",
    "US7Y": "DGS7",
    "US10Y": "DGS10",
    "US20Y": "DGS20",
    "US30Y": "DGS30",
    "US_ON": "SOFR",
    "US_BASE": "DFEDTARU",
}

# --- 각국 10년물 (월간, 2개월 지연) ------------------------------------------
GOVT_10Y_SERIES = {
    "KR10Y": "IRLTLT01KRM156N",
    "JP10Y": "IRLTLT01JPM156N",
    "DE10Y": "IRLTLT01DEM156N",
    "FR10Y": "IRLTLT01FRM156N",
    "IT10Y": "IRLTLT01ITM156N",
    "ES10Y": "IRLTLT01ESM156N",
    "GB10Y": "IRLTLT01GBM156N",
    "CH10Y": "IRLTLT01CHM156N",
    "CA10Y": "IRLTLT01CAM156N",
    "AU10Y": "IRLTLT01AUM156N",
}

# --- 정책금리 ----------------------------------------------------------------
# 유로존 4개국(DE/FR/IT/ES)은 ECB 예금금리를 공유한다.
POLICY_SERIES = {
    "US_BASE": "DFEDTARU",
    "DE_BASE": "ECBDFR",
    "FR_BASE": "ECBDFR",
    "IT_BASE": "ECBDFR",
    "ES_BASE": "ECBDFR",
    "GB_BASE": "IUDSOIA",
}

# --- 신용등급별 회사채 (ICE BofA 미국 지수, 일간) ----------------------------
# effective yield = 실효 만기수익률, OAS = 옵션조정 스프레드(국채 대비 bp/100).
CREDIT_YIELD_SERIES = {
    "AAA": "BAMLC0A1CAAAEY",
    "AA": "BAMLC0A2CAAEY",
    "A": "BAMLC0A3CAEY",
    "BBB": "BAMLC0A4CBBBEY",
    "BB": "BAMLH0A1HYBBEY",
    "B": "BAMLH0A2HYBEY",
    "CCC": "BAMLH0A3HYCEY",
}

CREDIT_OAS_SERIES = {
    "AAA": "BAMLC0A1CAAA",
    "AA": "BAMLC0A2CAA",
    "A": "BAMLC0A3CA",
    "BBB": "BAMLC0A4CBBB",
    "BB": "BAMLH0A1HYBB",
    "B": "BAMLH0A2HYB",
    "CCC": "BAMLH0A3HYC",
}

# --- 환율 원시 시리즈 --------------------------------------------------------
# FRED 는 통화쌍 방향이 제각각이라(USD 가 기준인 것과 상대인 것이 섞여 있다)
# 원시 시리즈를 먼저 받고 아래 ``derive_fx`` 에서 카탈로그 방향으로 환산한다.
FX_RAW_SERIES = {
    "KRW_PER_USD": "DEXKOUS",
    "JPY_PER_USD": "DEXJPUS",
    "USD_PER_EUR": "DEXUSEU",
    "CNY_PER_USD": "DEXCHUS",
    "USD_PER_GBP": "DEXUSUK",
    "USD_PER_AUD": "DEXUSAL",
    "CAD_PER_USD": "DEXCAUS",
    "CHF_PER_USD": "DEXSZUS",
    "INR_PER_USD": "DEXINUS",
    "BRL_PER_USD": "DEXBZUS",
    "MXN_PER_USD": "DEXMXUS",
    "DOLLAR_INDEX": "DTWEXBGS",
}


def _parse_csv_text(text: str, fred_id: str) -> dict[str, float]:
    """``observation_date,<시리즈>`` CSV → ``{날짜: 값}``. 결측(``.``)은 버린다.

    FRED 가 오류를 HTML 로 돌려주는 경우가 있어 헤더로 형식을 먼저 확인한다.
    """
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise SourceError(f"FRED {fred_id}: 빈 응답") from exc
    if not header or "observation_date" not in header[0]:
        raise SourceError(f"FRED {fred_id}: CSV 형식이 아님 — {header[:2]}")

    out: dict[str, float] = {}
    for row in reader:
        if len(row) < 2:
            continue
        raw = row[1].strip()
        if not raw or raw == ".":
            continue
        try:
            out[row[0].strip()] = float(raw)
        except ValueError:
            continue
    if not out:
        raise SourceError(f"FRED {fred_id}: 유효 관측치 없음")
    return out


def fetch_series(fred_id: str) -> dict[str, float]:
    """FRED 시리즈 하나의 전체 히스토리."""
    return _parse_csv_text(fetch(CSV_URL, params={"id": fred_id}).text, fred_id)


def _collect(mapping: dict[str, str]) -> dict[str, dict[str, float]]:
    """매핑을 훑되, 한 시리즈의 실패가 나머지를 막지 않게 한다."""
    out: dict[str, dict[str, float]] = {}
    cache: dict[str, dict[str, float]] = {}
    for series_id, fred_id in mapping.items():
        if fred_id in cache:                     # ECB 금리처럼 여러 국가가 공유
            out[series_id] = cache[fred_id]
            continue
        try:
            points = fetch_series(fred_id)
        except SourceError as exc:
            logger.warning("FRED %s(%s) 건너뜀 — %s", series_id, fred_id, exc)
            continue
        cache[fred_id] = points
        out[series_id] = points
    return out


def collect_rates() -> dict[str, dict[str, float]]:
    """국채 커브·각국 10년물·정책금리를 한 번에."""
    rates: dict[str, dict[str, float]] = {}
    rates.update(_collect(TREASURY_SERIES))
    rates.update(_collect(GOVT_10Y_SERIES))
    rates.update(_collect(POLICY_SERIES))
    return rates


def collect_credit() -> dict[str, dict[str, dict[str, float]]]:
    """등급별 수익률과 OAS. ``{"yield": {...}, "oas": {...}}``."""
    return {
        "yield": {r: p for r, p in _collect(CREDIT_YIELD_SERIES).items()},
        "oas": {r: p for r, p in _collect(CREDIT_OAS_SERIES).items()},
    }


def _ratio(numer: dict[str, float], denom: dict[str, float], scale: float = 1.0) -> dict[str, float]:
    """두 시리즈의 교집합 날짜에서 numer/denom × scale."""
    out = {}
    for day, value in numer.items():
        base = denom.get(day)
        if base:
            out[day] = value / base * scale
    return out


def _product(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    return {day: value * b[day] for day, value in a.items() if day in b}


def derive_fx(raw: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """FRED 원시 통화쌍을 카탈로그의 base/quote 방향으로 환산한다.

    원화 크로스는 FRED 에 직접 시리즈가 없어 달러를 매개로 계산한다
    (예: 유로/원 = USD당원 × 유로당USD).
    """
    krw = raw.get("KRW_PER_USD", {})
    out: dict[str, dict[str, float]] = {}

    def put(pair: str, points: dict[str, float]) -> None:
        if points:
            out[pair] = points

    put("USD_KRW", dict(krw))
    put("EUR_KRW", _product(raw.get("USD_PER_EUR", {}), krw))
    put("GBP_KRW", _product(raw.get("USD_PER_GBP", {}), krw))
    put("AUD_KRW", _product(raw.get("USD_PER_AUD", {}), krw))
    # 엔화는 100엔 단위로 고시한다.
    put("JPY_KRW", _ratio(krw, raw.get("JPY_PER_USD", {}), scale=100.0))
    put("CNY_KRW", _ratio(krw, raw.get("CNY_PER_USD", {})))
    put("CAD_KRW", _ratio(krw, raw.get("CAD_PER_USD", {})))
    put("CHF_KRW", _ratio(krw, raw.get("CHF_PER_USD", {})))
    put("USD_JPY", raw.get("JPY_PER_USD", {}))
    put("EUR_USD", raw.get("USD_PER_EUR", {}))
    put("GBP_USD", raw.get("USD_PER_GBP", {}))
    put("USD_CNY", raw.get("CNY_PER_USD", {}))
    put("USD_INR", raw.get("INR_PER_USD", {}))
    put("USD_BRL", raw.get("BRL_PER_USD", {}))
    put("USD_MXN", raw.get("MXN_PER_USD", {}))
    put("USD_IDX", raw.get("DOLLAR_INDEX", {}))
    return out


def collect_fx() -> dict[str, dict[str, float]]:
    return derive_fx(_collect(FX_RAW_SERIES))
