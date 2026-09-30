"""스냅샷 조립 규칙 — 소스 우선순위, 커브 구성, 하이라이트."""

import pytest

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


def test_reset_series는_옛_소스의_히스토리를_버린다(tmp_path, monkeypatch):
    """소스를 바꾸면 옛 관측치가 새 소스보다 뒤 날짜로 남아 최신값을 가린다.

    영국 정책금리를 SONIA(FRED)에서 Bank Rate(BIS)로 옮겼을 때 실제로 겪은 일:
    BIS 는 08-24 까지인데 08-25·26 의 SONIA 값이 계속 노출됐다.
    """
    build.write_json(
        tmp_path / build.RATES_FILE,
        {"series": {"GB_BASE": {"d": ["2026-08-25", "2026-08-26"], "v": [3.7316, 3.7309]}}},
    )

    # 수집은 건너뛰고 히스토리 처리만 본다.
    monkeypatch.setattr(build.finance_pi, "probe", lambda: False)
    monkeypatch.setattr(build, "collect_rates", lambda **kw: ({}, {}, []))
    monkeypatch.setattr(build, "collect_fx", lambda **kw: ({}, []))
    monkeypatch.setattr(build, "collect_credit", lambda kr: ({"yield": {}, "oas": {}}, []))

    build.run(tmp_path, skip_issuers=True, reset_series={"GB_BASE"})

    stored = build.read_json(tmp_path / build.RATES_FILE).get("series", {})
    assert "GB_BASE" not in stored, "리셋 대상은 옛 히스토리가 남지 않아야 한다"


def test_reset_series가_비면_히스토리를_유지한다(tmp_path, monkeypatch):
    build.write_json(
        tmp_path / build.RATES_FILE,
        {"series": {"GB_BASE": {"d": ["2026-08-25"], "v": [3.7316]}}},
    )
    monkeypatch.setattr(build.finance_pi, "probe", lambda: False)
    monkeypatch.setattr(build, "collect_rates", lambda **kw: ({"GB_BASE": {"2026-08-24": 3.75}}, {}, []))
    monkeypatch.setattr(build, "collect_fx", lambda **kw: ({}, []))
    monkeypatch.setattr(build, "collect_credit", lambda kr: ({"yield": {}, "oas": {}}, []))

    build.run(tmp_path, skip_issuers=True)

    stored = build.read_json(tmp_path / build.RATES_FILE)["series"]["GB_BASE"]
    # 옛 관측치가 그대로 남아 새 소스(08-24)보다 뒤 날짜를 차지한다 — 이게 리셋이 필요한 이유.
    assert stored["d"] == ["2026-08-24", "2026-08-25"]


def test_write_json은_비표준_JSON을_거부한다(tmp_path):
    """NaN/Infinity 가 조용히 배포되면 브라우저가 파일 전체를 못 읽는다."""
    with pytest.raises(ValueError):
        build.write_json(tmp_path / "bad.json", {"v": float("nan")})


def test_round는_비유한값을_None으로_만든다():
    assert build._round(float("nan")) is None
    assert build._round(float("inf")) is None
    assert build._round(4.7345, 2) == 4.73


def test_환율_단독_갱신은_금리와_기존_시리즈를_유지한다(tmp_path, monkeypatch):
    snapshot = build.build_snapshot(
        {"US10Y": {"2026-09-28": 5.234}},
        {"USD_KRW": {"2026-09-18": 1388}, "USD_IDX": {"2026-09-18": 120}},
        {}, [], sources={"rates": ["cnbc"], "fx": ["fred"]},
    )
    build.write_json(tmp_path / build.SNAPSHOT_FILE, snapshot)
    build.write_json(tmp_path / build.FX_FILE, {"series": {
        "USD_KRW": {"d": ["2026-09-18"], "v": [1388]},
        "USD_IDX": {"d": ["2026-09-18"], "v": [120]},
    }})
    build.write_json(tmp_path / build.RATES_FILE, {"unchanged": True})
    rate_bytes = (tmp_path / build.RATES_FILE).read_bytes()

    def fake_collect(**kwargs):
        assert kwargs["recent_only"] is True
        kwargs["quote_metadata"]["USD_KRW"] = {
            "date": "2026-09-29", "value": 1360.1, "change": 1.1,
            "as_of": "2026-09-29T05:29:34+09:00", "source": "naver",
        }
        return {"USD_KRW": {"2026-09-29": 1360.1}}, ["naver"]

    monkeypatch.setattr(build, "collect_fx", fake_collect)
    monkeypatch.setattr(build, "collect_rates", lambda **kw: pytest.fail("금리 수집 금지"))
    updated = build.refresh_fx(tmp_path)
    assert updated["rates"] == snapshot["rates"]
    assert (tmp_path / build.RATES_FILE).read_bytes() == rate_bytes
    assert updated["fx"]["USD_IDX"] == snapshot["fx"]["USD_IDX"]
    assert updated["fx"]["USD_KRW"]["change"] == 1.1  # 9/18과의 차이가 아님
    assert updated["fx"]["USD_KRW"]["as_of"] == "2026-09-29T05:29:34+09:00"
    assert updated["updated_at"]["rates"] == snapshot["generated_at"]


def test_최신_환율_전체실패면_직전_파일을_보존한다(tmp_path, monkeypatch):
    from bondmate.http import SourceError

    build.write_json(tmp_path / build.SNAPSHOT_FILE, {"generated_at": "2026-09-28T00:00:00Z"})
    before = (tmp_path / build.SNAPSHOT_FILE).read_bytes()

    def fail(**kwargs):
        raise SourceError("원본 장애")

    monkeypatch.setattr(build.naver, "collect", fail)
    monkeypatch.setattr(build.cnbc, "fetch_fx_quotes", fail)
    with pytest.raises(SourceError):
        build.refresh_fx(tmp_path)
    assert (tmp_path / build.SNAPSHOT_FILE).read_bytes() == before


def test_다른_관측값에는_과거_시세시각을_붙이지_않는다():
    quotes = {"USD_KRW": {"date": "2026-09-29", "value": 1362}}
    previous = {"USD_KRW": {"date": "2026-09-28", "value": 1360,
                            "as_of": "2026-09-28T12:00:00+09:00"}}
    build.apply_fx_metadata(quotes, {}, previous)
    assert "as_of" not in quotes["USD_KRW"]


# --- 소스 실패에도 히스토리 보존 (합집합) ----------------------------------------
def _stub_collectors(monkeypatch, *, rates=None, kr_credit=None, fx=None, credit=None):
    monkeypatch.setattr(build.finance_pi, "probe", lambda: False)
    monkeypatch.setattr(build, "collect_rates", lambda **kw: (rates or {}, kr_credit or {}, ["stub"]))
    monkeypatch.setattr(build, "collect_fx", lambda **kw: (fx or {}, ["stub"]))
    monkeypatch.setattr(
        build, "collect_credit",
        lambda kr: ({**(credit or {"yield": {}, "oas": {}}), **({"kr_yield": kr} if kr else {})}, ["stub"]),
    )


def test_이번에_빠진_금리_시리즈도_직전_히스토리를_유지한다(tmp_path, monkeypatch):
    """MOF 가 한 번 실패해도 JP1Y 히스토리가 사라지면 안 된다(이번 달 CSV 만 주는 소스)."""
    build.write_json(tmp_path / build.RATES_FILE, {"series": {
        "JP1Y": {"d": ["2026-08-17", "2026-08-18"], "v": [0.71, 0.72]},
        "US10Y": {"d": ["2026-08-18"], "v": [4.3]},
    }})
    _stub_collectors(monkeypatch, rates={"US10Y": {"2026-08-19": 4.31}})

    snapshot = build.run(tmp_path, skip_issuers=True)

    stored = build.read_json(tmp_path / build.RATES_FILE)["series"]
    assert stored["JP1Y"] == {"d": ["2026-08-17", "2026-08-18"], "v": [0.71, 0.72]}
    assert stored["US10Y"]["d"] == ["2026-08-18", "2026-08-19"]
    # 스냅샷에도 남아 허브 패널이 한 번의 실패로 비지 않는다.
    assert snapshot["rates"]["JP1Y"]["value"] == 0.72
    assert snapshot["rates"]["JP1Y"]["date"] == "2026-08-18"


def test_등급별_회사채_수집이_실패해도_직전_히스토리를_유지한다(tmp_path, monkeypatch):
    build.write_json(tmp_path / build.CREDIT_FILE, {
        "generated_at": "2026-08-18T00:00:00+00:00",
        "yield": {"BBB": {"d": ["2026-08-18"], "v": [5.1]}},
        "oas": {"BBB": {"d": ["2026-08-18"], "v": [0.97]}},
        "kr_yield": {"AA-": {"d": ["2026-08-18"], "v": [3.2]}},
    })
    # FRED 실패(빈 yield/oas) + ECOS 실패(kr_yield 없음)
    _stub_collectors(monkeypatch, rates={"US10Y": {"2026-08-19": 4.31}})

    snapshot = build.run(tmp_path, skip_issuers=True)

    stored = build.read_json(tmp_path / build.CREDIT_FILE)
    assert stored["yield"]["BBB"]["v"] == [5.1]
    assert stored["oas"]["BBB"]["v"] == [0.97]
    assert stored["kr_yield"]["AA-"]["v"] == [3.2]
    assert "generated_at" not in stored["yield"]
    assert snapshot["credit"]["BBB"]["oas"]["value"] == 0.97
    assert snapshot["credit_kr"]["AA-"]["value"] == 3.2


def test_등급별_회사채는_새_관측치를_직전_히스토리에_합친다(tmp_path, monkeypatch):
    build.write_json(tmp_path / build.CREDIT_FILE, {
        "yield": {"BBB": {"d": ["2026-08-18"], "v": [5.1]}, "CCC": {"d": ["2026-08-18"], "v": [14.0]}},
        "oas": {},
    })
    _stub_collectors(monkeypatch, credit={"yield": {"BBB": {"2026-08-19": 5.2}}, "oas": {}})

    build.run(tmp_path, skip_issuers=True)

    stored = build.read_json(tmp_path / build.CREDIT_FILE)["yield"]
    assert stored["BBB"] == {"d": ["2026-08-18", "2026-08-19"], "v": [5.1, 5.2]}
    assert stored["CCC"]["v"] == [14.0]


def test_reset_series는_합집합에서도_다시_받지_못한_시리즈를_버린다(tmp_path, monkeypatch):
    build.write_json(tmp_path / build.RATES_FILE, {"series": {
        "GB_BASE": {"d": ["2026-08-25"], "v": [3.73]},
        "JP1Y": {"d": ["2026-08-25"], "v": [0.7]},
    }})
    build.write_json(tmp_path / build.CREDIT_FILE, {"yield": {"CCC": {"d": ["2026-08-25"], "v": [14.0]}}})
    _stub_collectors(monkeypatch)

    build.run(tmp_path, skip_issuers=True, reset_series={"GB_BASE", "CCC"})

    assert set(build.read_json(tmp_path / build.RATES_FILE)["series"]) == {"JP1Y"}
    assert "CCC" not in build.read_json(tmp_path / build.CREDIT_FILE)["yield"]


def test_FRED_금리는_같은_시리즈를_한_번만_받는다(monkeypatch):
    """DFEDTARU 는 국채 커브 표와 정책금리 표 양쪽에 있다."""
    calls = []

    def fake_fetch(fred_id):
        calls.append(fred_id)
        return {"2026-08-18": 1.0}

    monkeypatch.setattr(build.fred, "fetch_series", fake_fetch)
    rates = build.fred.collect_rates()
    assert calls.count("DFEDTARU") == 1
    assert calls.count("ECBDFR") == 1
    assert rates["US_BASE"] == {"2026-08-18": 1.0}
    assert rates["DE_BASE"] == rates["FR_BASE"]


# --- 값이 그대로면 타임스탬프 유지 (no-op 실행) ---------------------------------
def test_값이_그대로면_generated_at과_updated_at을_유지하고_checked_at만_찍는다(tmp_path, monkeypatch):
    _stub_collectors(
        monkeypatch,
        rates={"US10Y": {"2026-08-18": 4.3, "2026-08-19": 4.31}},
        fx={"USD_KRW": {"2026-08-19": 1388.0}},
        credit={"yield": {"BBB": {"2026-08-19": 5.2}}, "oas": {"BBB": {"2026-08-19": 0.97}}},
    )
    first = build.run(tmp_path, skip_issuers=True)
    history_bytes = {
        name: (tmp_path / name).read_bytes()
        for name in (build.RATES_FILE, build.FX_FILE, build.CREDIT_FILE, build.ISSUERS_FILE,
                     "summary.json", "version.json")
    }

    monkeypatch.setattr(build, "datetime", _FrozenDatetime("2099-01-01T00:00:00+00:00"))
    second = build.run(tmp_path, skip_issuers=True)

    assert second["generated_at"] == first["generated_at"]
    assert second["updated_at"] == first["updated_at"]
    assert second["checked_at"] == "2099-01-01T00:00:00+00:00"
    for name, before in history_bytes.items():
        assert (tmp_path / name).read_bytes() == before, f"{name} 가 다시 쓰였다"


def test_바뀐_시장의_updated_at만_새로_찍힌다(tmp_path, monkeypatch):
    rates = {"US10Y": {"2026-08-19": 4.31}}
    _stub_collectors(monkeypatch, rates=rates, fx={"USD_KRW": {"2026-08-19": 1388.0}})
    first = build.run(tmp_path, skip_issuers=True)

    _stub_collectors(monkeypatch, rates=rates, fx={"USD_KRW": {"2026-08-20": 1390.0}})
    monkeypatch.setattr(build, "datetime", _FrozenDatetime("2099-01-01T00:00:00+00:00"))
    second = build.run(tmp_path, skip_issuers=True)

    assert second["generated_at"] == "2099-01-01T00:00:00+00:00"
    assert second["updated_at"]["fx"] == "2099-01-01T00:00:00+00:00"
    assert second["updated_at"]["rates"] == first["updated_at"]["rates"]
    assert second["updated_at"]["credit"] == first["updated_at"]["credit"]
    rates_file = build.read_json(tmp_path / build.RATES_FILE)
    assert rates_file["generated_at"] == first["generated_at"], "금리 히스토리는 그대로다"


def test_환율_단독_갱신도_값이_그대로면_타임스탬프를_유지한다(tmp_path, monkeypatch):
    _stub_collectors(monkeypatch, rates={"US10Y": {"2026-08-19": 4.31}}, fx={"USD_KRW": {"2026-08-19": 1388.0}})
    first = build.run(tmp_path, skip_issuers=True)
    fx_bytes = (tmp_path / build.FX_FILE).read_bytes()

    monkeypatch.setattr(build, "collect_fx", lambda **kw: ({"USD_KRW": {"2026-08-19": 1388.0}}, ["stub"]))
    monkeypatch.setattr(build, "datetime", _FrozenDatetime("2099-01-01T00:00:00+00:00"))
    again = build.refresh_fx(tmp_path)

    assert again["generated_at"] == first["generated_at"]
    assert again["updated_at"] == first["updated_at"]
    assert again["checked_at"] == "2099-01-01T00:00:00+00:00"
    assert (tmp_path / build.FX_FILE).read_bytes() == fx_bytes


def test_publish_due는_내용이_바뀌었거나_하트비트가_지났을_때만_참이다():
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    previous = {"generated_at": "2026-09-30T09:00:00+00:00", "checked_at": "2026-09-30T11:40:00+00:00"}
    same = {**previous, "checked_at": now.isoformat()}
    assert build.publish_due(previous, same, now=now) is False
    assert build.publish_due(previous, {**same, "generated_at": now.isoformat()}, now=now) is True
    late = datetime(2026, 9, 30, 11, 40, tzinfo=UTC) + build.HEARTBEAT   # 직전 발행의 checked_at 기준
    assert build.publish_due(previous, same, now=late - timedelta(minutes=1)) is False
    assert build.publish_due(previous, same, now=late) is True
    assert build.publish_due({}, same, now=now) is True, "직전 파일이 없으면(첫 실행) 발행"
    # 옛 파일에는 checked_at 이 없다 — generated_at 으로 판단한다.
    assert build.publish_due({"generated_at": "2026-09-30T11:50:00+00:00"},
                             {"generated_at": "2026-09-30T11:50:00+00:00"}, now=now) is False


def test_하트비트는_수집_지연_기준에_예약_지연_여유를_남긴다():
    """화면은 checked_at 이 1시간 넘으면 '수집 지연'이다. 하트비트 + cron 간격(5분) +
    실행·배포(~5분)에 Actions 예약 지연 20분을 더해도 1시간 안이어야 오탐하지 않는다."""
    from datetime import timedelta

    assert build.HEARTBEAT + timedelta(minutes=5 + 5 + 20) <= timedelta(hours=1)


class _FrozenDatetime:
    """build.datetime.now() 만 고정한다(나머지는 진짜 datetime)."""

    def __init__(self, iso):
        from datetime import datetime

        self._real = datetime
        self._now = datetime.fromisoformat(iso)

    def now(self, tz=None):
        return self._now if tz is None else self._now.astimezone(tz)

    def __getattr__(self, name):
        return getattr(self._real, name)
