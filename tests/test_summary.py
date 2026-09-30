"""value-invest 허브용 summary.json — Value Compass 발행 데이터 계약 v1 (§6.8 bond-mate).

계약 정본: value-invest ``docs/ecosystem/data-contract.md`` +
``config/schemas/summary/bond-mate.schema.json``. 스키마 검사는 jsonschema 없이
필요한 규칙만 옮겨 확인한다(허브의 fixture 검증과 같은 규칙).
"""

import json
import re
from pathlib import Path

import pytest

from bondmate import build, summary, vc_publish

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "summary.json"
NUM = (int, float, type(None))
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _snapshot():
    snapshot = build.build_snapshot(
        {
            "US10Y": {"2026-09-24": 5.18, "2026-09-25": 5.165},
            "US2Y": {"2026-09-25": 4.86},
            "KR3Y": {"2026-09-26": 2.9},
            "KR10Y": {"2026-09-26": 3.303},
            "US_BASE": {"2026-09-25": 3.75},
            "정체불명": {"2026-09-25": 1.0},        # 국가·만기를 모르는 시리즈는 빠진다
        },
        {"USD_KRW": {"2026-09-17": 1380.46, "2026-09-18": 1387.97}, "USD_IDX": {"2026-09-18": 120.1}},
        {
            "yield": {"BBB": {"2026-09-24": 5.9}},
            "oas": {"BBB": {"2026-09-24": 0.97}, "CCC": {"2026-09-24": 11.12}},
        },
        [{"issuer": "GOOGL", "filing_date": "2026-08-07", "total_amount": 25_000_000_000.0,
          "tranches": [{}] * 10}],
        sources={"rates": ["fred", "cnbc"], "fx": ["fred", "naver"], "credit": ["fred"], "issuers": []},
    )
    return snapshot


def check_schema(data: dict) -> None:
    """config/schemas/summary/bond-mate.schema.json 의 규칙."""
    for key in ("highlights", "creditSpreadBp", "latestOffering", "rates", "fx"):
        assert key in data, key
    h = data["highlights"]
    for key in ("usCurveSpreadBp", "usCurveInverted", "krCurveSpreadBp"):
        assert key in h
    assert isinstance(h["usCurveSpreadBp"], NUM) and isinstance(h["krCurveSpreadBp"], NUM)
    assert h["usCurveInverted"] in (True, False, None)
    assert all(isinstance(v, (int, float)) for v in data["creditSpreadBp"].values())
    offering = data["latestOffering"]
    if offering is not None:
        assert "issuerName" in offering and "totalAmount" in offering
        assert offering.get("filingDate") is None or DATE.match(offering["filingDate"])
    for series_id, row in data["rates"].items():
        assert re.match(r"^[A-Z0-9_]{2,16}$", series_id)
        for key in ("country", "maturity", "value", "change", "date"):
            assert key in row, (series_id, key)
        assert re.match(r"^[A-Z]{2}$", row["country"])
        assert isinstance(row["maturity"], (int, float))
        assert isinstance(row["value"], NUM) and isinstance(row["change"], NUM)
        assert row["date"] is None or DATE.match(row["date"])
    for pair, row in data["fx"].items():
        assert re.match(r"^[A-Z]{3}_[A-Z]{3}$", pair)
        for key in ("value", "change", "date"):
            assert key in row, (pair, key)


def test_요약은_계약_필드를_camelCase로_싣는다():
    data = summary.build_summary(_snapshot())
    check_schema(data)
    assert data["highlights"] == {
        "usCurveSpreadBp": 30.5, "usCurveInverted": False, "krCurveSpreadBp": 40.3, "igHySpreadBp": 1015.0,
    }
    assert data["creditSpreadBp"] == {"BBB": 97.0, "CCC": 1112.0}      # OAS %p → bp
    assert data["latestOffering"] == {
        "issuer": "GOOGL", "issuerName": "알파벳(구글)", "filingDate": "2026-08-07",
        "totalAmount": 25_000_000_000.0, "tranches": 10,
    }
    assert data["rates"]["US10Y"] == {
        "country": "US", "maturity": 10.0, "tenor": "10년", "value": 5.165,
        "change": -0.015, "changePct": -0.29, "date": "2026-09-25",
    }
    assert data["rates"]["US_BASE"]["maturity"] == -1.0
    assert data["rates"]["US2Y"]["change"] is None, "관측치 하나면 변동은 null (0 이 아니다)"
    assert "정체불명" not in data["rates"]
    assert data["fx"]["USD_KRW"]["label"] == "달러/원"
    assert data["fx"]["USD_KRW"]["changePct"] == 0.544
    assert set(data["fx"]) == {"USD_KRW", "USD_IDX"}


def test_envelope는_계약을_지키고_asOf는_데이터_날짜다():
    envelope = summary.build_envelope(_snapshot())
    vc_publish.validate_envelope(envelope)
    assert envelope["tool"] == "bond-mate" and envelope["kind"] == "summary"
    assert envelope["asOf"] == "2026-09-26"                     # 관측일 최댓값, 실행 시각 아님
    assert [s["id"] for s in envelope["sources"]] == ["fred", "cnbc", "naver"]
    assert envelope["generatedAt"].endswith("+09:00")
    assert len(vc_publish.dumps_compact(envelope)) < 16 * 1024


def test_관측일이_없으면_envelope를_만들지_않는다(tmp_path):
    with pytest.raises(vc_publish.EnvelopeError):
        summary.build_envelope({"rates": {}, "fx": {}})
    assert summary.publish(tmp_path, {"rates": {}, "fx": {}}) is False
    assert not (tmp_path / "summary.json").exists()


def test_내용이_그대로면_summary와_version을_다시_쓰지_않는다(tmp_path):
    snapshot = _snapshot()
    assert summary.publish(tmp_path, snapshot) is True
    before = {name: (tmp_path / name).read_bytes() for name in ("summary.json", "version.json")}

    snapshot["generated_at"] = "2099-01-01T00:00:00+00:00"       # 시각만 다른 재실행
    assert summary.publish(tmp_path, snapshot) is False
    for name, content in before.items():
        assert (tmp_path / name).read_bytes() == content, name

    snapshot["rates"]["US10Y"]["value"] = 5.2                    # 값이 바뀌면 다시 쓴다
    assert summary.publish(tmp_path, snapshot) is True
    version = json.loads((tmp_path / "version.json").read_text(encoding="utf-8"))
    written = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert version["files"] == {"summary.json": written["contentHash"]}
    assert version["tool"] == "bond-mate"


def test_run은_data_디렉터리에_summary를_남긴다(tmp_path, monkeypatch):
    monkeypatch.setattr(build.finance_pi, "probe", lambda: False)
    monkeypatch.setattr(build, "collect_rates", lambda **kw: ({"US10Y": {"2026-08-19": 4.31}}, {}, ["fred"]))
    monkeypatch.setattr(build, "collect_fx", lambda **kw: ({"USD_KRW": {"2026-08-19": 1388.0}}, ["naver"]))
    monkeypatch.setattr(build, "collect_credit", lambda kr: ({"yield": {}, "oas": {}}, []))
    build.run(tmp_path, skip_issuers=True)

    envelope = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    vc_publish.validate_envelope(envelope)
    check_schema(envelope["data"])
    assert envelope["data"]["rates"]["US10Y"]["value"] == 4.31
    assert (tmp_path / "version.json").exists()


def test_CLI는_current_json만으로_오프라인_생성한다(tmp_path):
    build.write_json(tmp_path / "current.json", _snapshot())
    out = tmp_path / "site"
    assert summary.main(["--data", str(tmp_path), "--out", str(out)]) == 0
    envelope = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    vc_publish.validate_envelope(envelope)
    first = (out / "summary.json").read_bytes()
    assert summary.main(["--data", str(tmp_path), "--out", str(out)]) == 0
    assert (out / "summary.json").read_bytes() == first
    assert summary.main(["--data", str(tmp_path / "없음")]) == 1


def test_커밋된_초기_summary는_계약을_지킨다():
    """data 브랜치의 current.json(2026-09-26 22:11 UTC)에서 오프라인으로 만든 초기본."""
    envelope = json.loads(FIXTURE.read_text(encoding="utf-8"))
    vc_publish.validate_envelope(envelope)
    check_schema(envelope["data"])
    assert envelope["tool"] == "bond-mate"
    assert len(envelope["data"]["rates"]) >= 60 and len(envelope["data"]["fx"]) == 16
    assert FIXTURE.read_text(encoding="utf-8") == vc_publish.dumps_compact(envelope) + "\n"
