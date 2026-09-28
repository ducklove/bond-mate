"""소스 어댑터의 순수 파싱 로직 — 네트워크 없이 검증한다."""

import pytest

from bondmate.http import SourceError
from bondmate.sources import bis, cnbc, ecos, finance_pi, fred, mof, naver

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


def test_네이버_JSON_일별_환율을_파싱한다():
    rows = [
        {"localTradedAt": "2026-09-28", "closePrice": "1,360.10"},
        {"localTradedAt": "2026-09-23", "closePrice": "1,359.00"},
        {"localTradedAt": "bad", "closePrice": "1,300"},
        {"localTradedAt": "2026-09-22", "closePrice": "NaN"},
    ]
    assert naver.parse_prices(rows) == {"2026-09-28": 1360.1, "2026-09-23": 1359.0}


def test_네이버_응답_형식_변경을_실패로_알린다():
    with pytest.raises(SourceError):
        naver.parse_prices({"error": "removed"})


def test_네이버_최신_고시의_시각과_전일대비를_보존한다():
    quote = naver.parse_quote({"exchangeInfo": {
        "localTradedAt": "2026-09-29T05:29:34+09:00", "closePrice": "1,360.10",
        "fluctuations": "-1.10", "fluctuationsRatio": "-0.08",
    }})
    assert quote["date"] == "2026-09-29"
    assert quote["as_of"] == "2026-09-29T05:29:34+09:00"
    assert quote["value"] == 1360.1
    assert quote["change"] == -1.1


@pytest.mark.parametrize("stamp", [None, "", "invalid", "2026-09-29"])
def test_네이버_시세_시각을_오늘로_조작하지_않는다(stamp):
    with pytest.raises(SourceError):
        naver.parse_quote({"exchangeInfo": {"localTradedAt": stamp, "closePrice": "1360"}})


def test_네이버_일별_실패에도_최신_고시는_수집한다(monkeypatch):
    from types import SimpleNamespace

    def fake_fetch(url, **kwargs):
        if url.endswith("/prices"):
            raise SourceError("일별 실패")
        return SimpleNamespace(json=lambda: {"exchangeInfo": {
            "localTradedAt": "2026-09-29T05:29:34+09:00", "closePrice": "864.16",
        }})

    monkeypatch.setattr(naver, "fetch", fake_fetch)
    metadata = {}
    assert naver.fetch_pair("FX_JPYKRW", quote_metadata=metadata) == {"2026-09-29": 864.16}
    assert metadata["source"] == "naver"  # 100엔 단위도 재환산하지 않는다.


def test_CNBC_환율의_방향_시각_전일대비를_보존한다(monkeypatch):
    import json
    from types import SimpleNamespace

    payload = {"FormattedQuoteResult": {"FormattedQuote": [
        {"symbol": "EUR=", "last": "1.137", "last_time": "2026-09-28T16:31:00.000-0400",
         "change": "-0.0021", "change_pct": "-0.18%"},
        {"symbol": "JPY=", "last": "157.39", "last_time": ""},
    ]}}
    monkeypatch.setattr(cnbc, "fetch", lambda *a, **kw: SimpleNamespace(text=json.dumps(payload)))
    quotes = cnbc.fetch_fx_quotes()
    assert quotes["EUR_USD"]["value"] == 1.137
    assert quotes["EUR_USD"]["change"] == -0.0021
    assert quotes["EUR_USD"]["as_of"] == "2026-09-28T16:31:00-04:00"
    assert "USD_JPY" not in quotes
    assert "USD_IDX" not in quotes


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


def test_finance_pi_빈_환경변수는_기본값으로_돌아간다(monkeypatch):
    """GitHub Actions 는 정의 안 된 vars.X 를 빈 문자열로 넘긴다.

    그대로 쓰면 base_url 이 "" 가 돼 스킴 없는 URL 로 요청이 나간다.
    """
    monkeypatch.setenv("FINANCE_PI_BASE_URL", "")
    monkeypatch.setenv("FINANCE_PI_TIMEOUT", "")
    monkeypatch.setenv("FINANCE_PI_ENABLED", "")

    assert finance_pi.base_url() == finance_pi.DEFAULT_BASE_URL
    assert finance_pi._timeout() == 20
    assert finance_pi.enabled() is True


def test_finance_pi_환경변수_설정값이_기본값을_이긴다(monkeypatch):
    monkeypatch.setenv("FINANCE_PI_BASE_URL", "http://192.168.68.84:8400/")
    monkeypatch.setenv("FINANCE_PI_MAX_STALE_DAYS", "3")

    assert finance_pi.base_url() == "http://192.168.68.84:8400"
    assert finance_pi._max_stale_days() == 3


# --- BIS -----------------------------------------------------------------------


def test_BIS_CSV에서_관심국가만_추린다():
    csv = (
        "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE\n"
        "D,KR,2026-08-03,2.75\n"
        "D,JP,2026-08-25,1.00\n"
        "D,XM,2026-08-25,2.25\n"      # 유로존은 FRED(ECBDFR)가 맡는다
        "D,US,2026-08-25,3.62\n"      # 미국도 FRED(DFEDTARU)가 맡는다
        "D,GB,2026-08-24,\n"          # 결측
    )
    parsed = bis.parse_csv(csv)

    assert parsed == {"KR_BASE": {"2026-08-03": 2.75}, "JP_BASE": {"2026-08-25": 1.00}}


def test_BIS는_미국과_유로존을_다루지_않는다():
    """관행적 '기준금리' 정의가 달라(미국은 FF 목표 상단) FRED 가 맡는다."""
    assert "US" not in bis.REF_AREAS
    assert "XM" not in bis.REF_AREAS
    # 대신 FRED 가 정책금리로 다루지 않는 나라들을 메운다.
    assert {"JP", "GB", "AU", "CN", "CA", "CH", "IN", "ID", "BR", "MX"} <= set(bis.REF_AREAS)


def test_FRED와_BIS의_정책금리_담당이_겹치지_않는다():
    """같은 국가를 두 소스가 다루면 어느 값이 나올지 순서에 좌우된다."""
    fred_countries = {code.removesuffix("_BASE") for code in fred.POLICY_SERIES}
    bis_countries = {code.removesuffix("_BASE") for code in bis.REF_AREAS.values()}

    assert fred_countries.isdisjoint(bis_countries)
