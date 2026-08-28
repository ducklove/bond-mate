"""bond-mate 카탈로그 — 국가·만기·신용등급·발행사의 단일 진실 공급원(SSOT).

여기 정의된 식별자가 그대로 published JSON 의 키가 되고, value-invest 를 비롯한
소비자가 그 키로 조회한다. 따라서 **기존 키의 이름은 바꾸지 않는다**(추가는 자유).

금리/환율 시리즈 식별자 규칙
    국채   ``{국가}{만기}``      예) US10Y, KR3Y, JP30Y
    정책금리 ``{국가}_BASE``      예) US_BASE
    무위험 지표금리 ``{국가}_ON`` 예) US_ON(SOFR), KR_ON(KOFR)
    신용등급 커브 ``CORP_{등급}`` 예) CORP_AAA
    환율   ``{통화}_{기준통화}``  예) USD_KRW
"""

from __future__ import annotations

# --- 국가 -------------------------------------------------------------------
# curve = 만기별 곡선을 그릴 수 있을 만큼 만기가 확보된 국가.
COUNTRIES: dict[str, dict] = {
    "US": {"name": "미국", "name_en": "United States", "currency": "USD", "flag": "🇺🇸", "curve": True},
    "KR": {"name": "한국", "name_en": "South Korea", "currency": "KRW", "flag": "🇰🇷", "curve": True},
    "JP": {"name": "일본", "name_en": "Japan", "currency": "JPY", "flag": "🇯🇵", "curve": True},
    "DE": {"name": "독일", "name_en": "Germany", "currency": "EUR", "flag": "🇩🇪", "curve": False},
    "FR": {"name": "프랑스", "name_en": "France", "currency": "EUR", "flag": "🇫🇷", "curve": False},
    "IT": {"name": "이탈리아", "name_en": "Italy", "currency": "EUR", "flag": "🇮🇹", "curve": False},
    "ES": {"name": "스페인", "name_en": "Spain", "currency": "EUR", "flag": "🇪🇸", "curve": False},
    "GB": {"name": "영국", "name_en": "United Kingdom", "currency": "GBP", "flag": "🇬🇧", "curve": False},
    "CH": {"name": "스위스", "name_en": "Switzerland", "currency": "CHF", "flag": "🇨🇭", "curve": False},
    "CA": {"name": "캐나다", "name_en": "Canada", "currency": "CAD", "flag": "🇨🇦", "curve": False},
    "AU": {"name": "호주", "name_en": "Australia", "currency": "AUD", "flag": "🇦🇺", "curve": False},
    "CN": {"name": "중국", "name_en": "China", "currency": "CNY", "flag": "🇨🇳", "curve": False},
    "IN": {"name": "인도", "name_en": "India", "currency": "INR", "flag": "🇮🇳", "curve": False},
    "BR": {"name": "브라질", "name_en": "Brazil", "currency": "BRL", "flag": "🇧🇷", "curve": False},
    "MX": {"name": "멕시코", "name_en": "Mexico", "currency": "MXN", "flag": "🇲🇽", "curve": False},
    "ID": {"name": "인도네시아", "name_en": "Indonesia", "currency": "IDR", "flag": "🇮🇩", "curve": False},
}

# 만기를 연 단위 실수로 정규화한다. 정책금리는 -1, 익일물은 0 — value-invest
# market_indicators.CATALOG 의 maturity 규약과 동일하게 맞춰 두 카탈로그를 섞어
# 정렬해도 곡선이 깨지지 않게 한다.
POLICY_MATURITY = -1.0
OVERNIGHT_MATURITY = 0.0

TENORS: dict[str, float] = {
    "1M": 1 / 12,
    "3M": 0.25,
    "6M": 0.5,
    "1Y": 1.0,
    "2Y": 2.0,
    "3Y": 3.0,
    "5Y": 5.0,
    "7Y": 7.0,
    "10Y": 10.0,
    "15Y": 15.0,
    "20Y": 20.0,
    "30Y": 30.0,
    "40Y": 40.0,
    "50Y": 50.0,
}


def tenor_label(tenor: str) -> str:
    if tenor.endswith("M"):
        return f"{tenor[:-1]}개월"
    return f"{tenor[:-1]}년"


# --- 신용등급 ---------------------------------------------------------------
# ICE BofA 미국 회사채 지수 등급 구간. investment_grade=False 는 하이일드.
RATINGS: dict[str, dict] = {
    "AAA": {"label": "AAA", "order": 1, "investment_grade": True, "color": "#0ea5e9"},
    "AA": {"label": "AA", "order": 2, "investment_grade": True, "color": "#2563eb"},
    "A": {"label": "A", "order": 3, "investment_grade": True, "color": "#7c3aed"},
    "BBB": {"label": "BBB", "order": 4, "investment_grade": True, "color": "#c026d3"},
    "BB": {"label": "BB", "order": 5, "investment_grade": False, "color": "#f59e0b"},
    "B": {"label": "B", "order": 6, "investment_grade": False, "color": "#ea580c"},
    "CCC": {"label": "CCC 이하", "order": 7, "investment_grade": False, "color": "#dc2626"},
}


# --- 환율 -------------------------------------------------------------------
# base/quote 는 "base 1단위 = quote 얼마" 로 읽는다. scale 은 표시 배수
# (엔화처럼 100단위로 고시하는 통화).
FX_PAIRS: dict[str, dict] = {
    "USD_KRW": {"base": "USD", "quote": "KRW", "label": "달러/원", "scale": 1, "decimals": 2},
    "EUR_KRW": {"base": "EUR", "quote": "KRW", "label": "유로/원", "scale": 1, "decimals": 2},
    "JPY_KRW": {"base": "JPY", "quote": "KRW", "label": "엔/원(100엔)", "scale": 100, "decimals": 2},
    "CNY_KRW": {"base": "CNY", "quote": "KRW", "label": "위안/원", "scale": 1, "decimals": 2},
    "GBP_KRW": {"base": "GBP", "quote": "KRW", "label": "파운드/원", "scale": 1, "decimals": 2},
    "AUD_KRW": {"base": "AUD", "quote": "KRW", "label": "호주달러/원", "scale": 1, "decimals": 2},
    "CAD_KRW": {"base": "CAD", "quote": "KRW", "label": "캐나다달러/원", "scale": 1, "decimals": 2},
    "CHF_KRW": {"base": "CHF", "quote": "KRW", "label": "스위스프랑/원", "scale": 1, "decimals": 2},
    "USD_JPY": {"base": "USD", "quote": "JPY", "label": "달러/엔", "scale": 1, "decimals": 2},
    "EUR_USD": {"base": "EUR", "quote": "USD", "label": "유로/달러", "scale": 1, "decimals": 4},
    "GBP_USD": {"base": "GBP", "quote": "USD", "label": "파운드/달러", "scale": 1, "decimals": 4},
    "USD_CNY": {"base": "USD", "quote": "CNY", "label": "달러/위안", "scale": 1, "decimals": 4},
    "USD_INR": {"base": "USD", "quote": "INR", "label": "달러/루피", "scale": 1, "decimals": 3},
    "USD_BRL": {"base": "USD", "quote": "BRL", "label": "달러/헤알", "scale": 1, "decimals": 4},
    "USD_MXN": {"base": "USD", "quote": "MXN", "label": "달러/페소", "scale": 1, "decimals": 4},
    "USD_IDX": {"base": "USD", "quote": "IDX", "label": "달러지수", "scale": 1, "decimals": 2},
}


# --- 사채 발행사 -------------------------------------------------------------
# 미국 투자등급 회사채 시장에서 벤치마크 역할을 하는 대형 발행사. cik 는 SEC
# EDGAR 조회 키(10자리 zero-pad).
ISSUERS: dict[str, dict] = {
    "GOOGL": {"cik": "0001652044", "name": "Alphabet", "name_ko": "알파벳(구글)", "sector": "Tech"},
    "META": {"cik": "0001326801", "name": "Meta Platforms", "name_ko": "메타", "sector": "Tech"},
    "ORCL": {"cik": "0001341439", "name": "Oracle", "name_ko": "오라클", "sector": "Tech"},
    "MSFT": {"cik": "0000789019", "name": "Microsoft", "name_ko": "마이크로소프트", "sector": "Tech"},
    "AAPL": {"cik": "0000320193", "name": "Apple", "name_ko": "애플", "sector": "Tech"},
    "AMZN": {"cik": "0001018724", "name": "Amazon", "name_ko": "아마존", "sector": "Tech"},
    "AVGO": {"cik": "0001730168", "name": "Broadcom", "name_ko": "브로드컴", "sector": "Tech"},
    "NVDA": {"cik": "0001045810", "name": "NVIDIA", "name_ko": "엔비디아", "sector": "Tech"},
    "INTC": {"cik": "0000050863", "name": "Intel", "name_ko": "인텔", "sector": "Tech"},
    "IBM": {"cik": "0000051143", "name": "IBM", "name_ko": "IBM", "sector": "Tech"},
    "CSCO": {"cik": "0000858877", "name": "Cisco", "name_ko": "시스코", "sector": "Tech"},
    "T": {"cik": "0000732717", "name": "AT&T", "name_ko": "AT&T", "sector": "Telecom"},
    "VZ": {"cik": "0000732712", "name": "Verizon", "name_ko": "버라이즌", "sector": "Telecom"},
}


def issuer_label(ticker: str) -> str:
    meta = ISSUERS.get(ticker)
    return meta["name_ko"] if meta else ticker
