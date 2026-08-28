"""소스 어댑터의 순수 파싱 로직 — 네트워크 없이 검증한다."""

import pytest

from bondmate.http import SourceError
from bondmate.sources import cnbc, ecos, finance_pi, fred, mof, naver

# --- FRED --------------------------------------------------------------------


def test_FRED_결측치는_버린다():
    csv = "observation_date,DGS10\n2026-08-27,4.67\n2026-08-28,.\n"
    assert fred._parse_csv_text(csv, "DGS10") == {"2026-08-27": 4.67}


def test_FRED_CSV가_아니면_실패로_올린다():
    with pytest.raises(SourceError):
        fred._parse_csv_text("<html>error</html>", "DGS10")


def test_원화_크로스는_달러를_매개로_계산한다():
    """FRED 에 유로/원 직접 시리즈가 없어 USD 를 거쳐 만든다."""
    raw = {
        "KRW_PER_USD": {"2026-08-21": 1385.01},
        "USD_PER_EUR": {"2026-08-21": 1.1684},
        "JPY_PER_USD": {"2026-08-21": 158.91},
        "CNY_PER_USD": {"2026-08-21": 6.7210},
    }
    derived = fred.derive_fx(raw)

    assert derived["USD_KRW"]["2026-08-21"] == 1385.01
    assert round(derived["EUR_KRW"]["2026-08-21"], 2) == 1618.25
    # 엔화는 100엔 단위로 고시한다.
    assert round(derived["JPY_KRW"]["2026-08-21"], 2) == 871.57
    assert round(derived["CNY_KRW"]["2026-08-21"], 2) == 206.07


def test_날짜가_겹치지_않으면_크로스를_만들지_않는다():
    raw = {"KRW_PER_USD": {"2026-08-21": 1385.0}, "USD_PER_EUR": {"2026-08-20": 1.17}}
    assert "EUR_KRW" not in fred.derive_fx(raw)


# --- 일본 재무성 --------------------------------------------------------------


def test_일본_연호_날짜를_서기로_바꾼다():
    assert mof._to_iso("R8.8.28") == "2026-08-28"      # 레이와 8년 = 2026년
    assert mof._to_iso("R1.5.1") == "2019-05-01"
    assert mof._to_iso("2026.8.28") is None


def test_JGB_CSV에서_만기별_시계열을_뽑는다():
    # 실제 CSV 는 첫 줄이 안내문이고 둘째 줄이 만기 헤더다. 인코딩은 cp932.
    csv = "国債金利情報\n基準日,1年,10年,40年\nR8.8.27,0.85,2.897,3.5\nR8.8.28,0.86,2.910,-\n"
    parsed = mof.parse_csv(csv.encode("cp932"))

    assert parsed["JP10Y"] == {"2026-08-27": 2.897, "2026-08-28": 2.910}
    assert parsed["JP40Y"] == {"2026-08-27": 3.5}      # '-' 는 미발행


def test_만기_컬럼이_없으면_실패로_올린다():
    with pytest.raises(SourceError):
        mof.parse_csv("a\nb,c\nR8.8.28,1\n".encode("cp932"))


# --- CNBC --------------------------------------------------------------------


def test_CNBC_시세는_퍼센트_기호를_뗀다():
    assert cnbc._parse_last({"last": "4.73%"}) == 4.73
    assert cnbc._parse_last({"last": "1,385.01"}) == 1385.01
    assert cnbc._parse_last({"last": "N/A"}) is None


def test_CNBC_시각에서_날짜만_취한다():
    assert cnbc._quote_date({"last_time": "2026-08-28T16:59:00.000-0400"}) == "2026-08-28"
    assert cnbc._quote_date({"last_time": ""}) is None


# --- 네이버 ------------------------------------------------------------------


def test_네이버_일별_환율_표를_파싱한다():
    html = (
        '<tr class="up"><td class="date">2026.08.28</td><td class="num">1,380.50</td></tr>'
        '<tr class="down"><td class="date">2026.08.27</td><td class="num">1,382.00</td></tr>'
    )
    assert naver.parse_page(html) == {"2026-08-28": 1380.50, "2026-08-27": 1382.00}


def test_네이버_빈_페이지는_빈_결과():
    assert naver.parse_page("<table></table>") == {}


# --- ECOS --------------------------------------------------------------------


def test_ECOS_행을_시리즈별_시계열로_묶는다():
    rows = [
        {"ITEM_CODE1": "010210000", "TIME": "20260828", "DATA_VALUE": "4.284"},
        {"ITEM_CODE1": "010200000", "TIME": "20260828", "DATA_VALUE": "3.788"},
        {"ITEM_CODE1": "010210000", "TIME": "20260827", "DATA_VALUE": "4.270"},
        {"ITEM_CODE1": "999999999", "TIME": "20260828", "DATA_VALUE": "1.0"},  # 관심 밖
        {"ITEM_CODE1": "010210000", "TIME": "20260826", "DATA_VALUE": ""},     # 결측
    ]
    grouped = ecos._group(rows, ecos.ITEMS)

    assert grouped["KR10Y"] == {"2026-08-28": 4.284, "2026-08-27": 4.270}
    assert grouped["KR3Y"] == {"2026-08-28": 3.788}
    assert "2026-08-26" not in grouped["KR10Y"]


def test_ECOS는_키가_없으면_조용히_비활성():
    """키 없이도 나머지 소스만으로 서비스가 서야 한다."""
    assert ecos.collect() == ({}, {})


# --- finance-pi ---------------------------------------------------------------


def test_finance_pi_행을_bond_mate_시리즈로_옮긴다():
    rows = [
        {"series_id": "US_TREASURY_10Y", "date": "2026-08-28", "value": 4.73},
        {"series_id": "KR_GOVT_3Y_ECOS", "date": "2026-08-28", "value": 3.788},
        {"series_id": "알수없음", "date": "2026-08-28", "value": 1.0},
        {"series_id": "US_TREASURY_10Y", "date": None, "value": 4.0},
    ]
    grouped = finance_pi._group(rows, finance_pi.RATE_SERIES)

    assert grouped == {"US10Y": {"2026-08-28": 4.73}, "KR3Y": {"2026-08-28": 3.788}}


def test_finance_pi_비활성화면_프로브하지_않는다(monkeypatch):
    monkeypatch.setenv("FINANCE_PI_ENABLED", "0")
    assert finance_pi.probe() is False


def test_finance_pi_토큰이_있으면_헤더에_싣는다(monkeypatch):
    monkeypatch.setenv("FINANCE_PI_API_TOKEN", "비밀")
    assert finance_pi._headers() == {"X-Admin-Token": "비밀"}


def test_finance_pi_토큰이_없으면_헤더_없음(monkeypatch):
    monkeypatch.delenv("FINANCE_PI_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOSE_PRICE_API_TOKEN", raising=False)
    assert finance_pi._headers() is None
