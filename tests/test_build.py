"""스냅샷 조립 규칙 — 소스 우선순위, 커브 구성, 하이라이트."""

from bondmate import build, catalog


def test_underlay는_기존_값을_지킨다():
    """우선순위 낮은 소스는 빈 날짜만 메운다."""
    base = {"US10Y": {"2026-08-28": 4.7}}
    build._underlay(base, {"US10Y": {"2026-08-28": 9.9, "2026-08-27": 4.6}})
    assert base["US10Y"] == {"2026-08-28": 4.7, "2026-08-27": 4.6}


def test_overlay는_같은_날짜를_덮어쓴다():
    """CNBC 처럼 더 신선한 소스는 기존 값을 이긴다."""
    base = {"US10Y": {"2026-08-28": 4.7}}
    build._overlay(base, {"US10Y": {"2026-08-28": 4.73}})
    assert base["US10Y"]["2026-08-28"] == 4.73


def test_시리즈ID에서_국가와_만기를_되돌린다():
    assert build._rate_meta("US10Y") == {"country": "US", "tenor": "10년", "maturity": 10.0}
    assert build._rate_meta("KR3M")["maturity"] == 0.25
    assert build._rate_meta("US_BASE")["maturity"] == catalog.POLICY_MATURITY
    assert build._rate_meta("JP_ON")["maturity"] == catalog.OVERNIGHT_MATURITY
    assert build._rate_meta("정체불명")["country"] is None


def test_전일대비는_히스토리_두_점에서_나온다():
    quote = build._quote({"2026-08-27": 4.60, "2026-08-28": 4.73}, decimals=3)
    assert quote["value"] == 4.73
    assert quote["date"] == "2026-08-28"
    assert quote["change"] == 0.13
    assert quote["prev_date"] == "2026-08-27"


def test_관측치가_하나뿐이면_변동은_비운다():
    quote = build._quote({"2026-08-28": 4.73})
    assert quote["value"] == 4.73
    assert "change" not in quote


def test_커브는_만기_오름차순이고_정책금리가_맨_앞이다():
    rate_quotes = {
        "US10Y": {"country": "US", "maturity": 10.0, "value": 4.73, "tenor": "10년"},
        "US_BASE": {"country": "US", "maturity": -1.0, "value": 3.75, "tenor": "기준금리"},
        "US2Y": {"country": "US", "maturity": 2.0, "value": 4.36, "tenor": "2년"},
    }
    curve = build.build_curves(rate_quotes)["US"]
    assert [p["maturity"] for p in curve] == [-1.0, 2.0, 10.0]


def test_국가가_없는_시리즈는_커브에서_빠진다():
    assert build.build_curves({"XX": {"country": None, "maturity": None}}) == {}


def test_하이라이트는_장단기_스프레드를_bp로_계산한다():
    rate_quotes = {
        "US2Y": {"value": 4.36, "country": "US", "maturity": 2.0},
        "US10Y": {"value": 4.73, "country": "US", "maturity": 10.0},
    }
    highlights = build.build_highlights(rate_quotes, {}, [])
    assert highlights["us_curve_spread_bp"] == 37.0
    assert highlights["us_curve_inverted"] is False


def test_하이라이트는_커브_역전을_알아본다():
    rate_quotes = {
        "US2Y": {"value": 4.90, "country": "US", "maturity": 2.0},
        "US10Y": {"value": 4.30, "country": "US", "maturity": 10.0},
    }
    highlights = build.build_highlights(rate_quotes, {}, [])
    assert highlights["us_curve_inverted"] is True
    assert highlights["us_curve_spread_bp"] == -60.0


def test_하이라이트는_값이_없으면_None을_남긴다():
    """소스 하나가 실패해도 스냅샷 전체가 깨지면 안 된다."""
    highlights = build.build_highlights({}, {}, [])
    assert highlights["us_curve_spread_bp"] is None
    assert highlights["latest_offering"] is None


def test_하이라이트는_최근_발행을_요약한다():
    offerings = [
        {
            "issuer": "GOOGL",
            "filing_date": "2026-08-07",
            "total_amount": 25_000_000_000,
            "tranches": [{}, {}],
        }
    ]
    latest = build.build_highlights({}, {}, offerings)["latest_offering"]
    assert latest["issuer_name"] == "알파벳(구글)"
    assert latest["tranches"] == 2


def test_스냅샷은_소비자가_읽는_키를_모두_담는다():
    """value-invest 와 임베드 뷰가 의존하는 계약 — 키 이름을 바꾸면 깨진다."""
    snapshot = build.build_snapshot(
        rates={"US10Y": {"2026-08-27": 4.6, "2026-08-28": 4.73}},
        fx={"USD_KRW": {"2026-08-27": 1382.0, "2026-08-28": 1380.5}},
        credit={"yield": {"BBB": {"2026-08-28": 5.56}}, "oas": {"BBB": {"2026-08-28": 0.98}}},
        offerings=[],
        sources={"rates": ["fred"]},
    )
    for key in ("generated_at", "sources", "countries", "rates", "fx", "credit", "curves",
                "offerings", "issuers", "highlights"):
        assert key in snapshot

    assert snapshot["rates"]["US10Y"]["country_name"] == "미국"
    assert snapshot["fx"]["USD_KRW"]["label"] == "달러/원"
    assert snapshot["credit"]["BBB"]["investment_grade"] is True
    assert snapshot["credit"]["BBB"]["yield"]["value"] == 5.56


def test_한국_회사채는_미국_커브와_섞이지_않는다():
    """등급 체계(AA-/BBB-)와 만기(3년 고정)가 달라 따로 실어야 한다."""
    snapshot = build.build_snapshot(
        rates={},
        fx={},
        credit={"yield": {}, "oas": {}, "kr_yield": {"AA-": {"2026-08-28": 4.476}}},
        offerings=[],
        sources={},
    )
    assert "AA-" not in snapshot["credit"]
    assert snapshot["credit_kr"]["AA-"]["value"] == 4.476
