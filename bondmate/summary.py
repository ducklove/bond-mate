"""value-invest 허브용 요약 ``summary.json`` (Value Compass 발행 데이터 계약 v1).

허브의 '채권 시황' 카드와 투자정보 병합은 지금 ``data/current.json``(약 112 KB,
그중 77% 가 발행 이력)을 통째로 받아 시리즈별 최신값과 하이라이트만 쓴다.
이 모듈은 그 필드만 추려 공통 envelope 로 감싼 약 10 KB 파일을 만든다.

계약 정본은 value-invest ``docs/ecosystem/data-contract.md`` §6.8 과
``config/schemas/summary/bond-mate.schema.json`` 이다. envelope·해시·무변경 판정은
벤더링된 :mod:`bondmate.vc_publish` (직접 고치지 않는다)가 맡는다.

위치: data 브랜치 ``data/summary.json``·``data/version.json`` → ``deploy.yml`` 이
Pages 루트(``/bond-mate/summary.json``)로 복사한다. 기존 ``current.json`` 은 그대로
발행한다(허브 폴백과 다른 소비자용).

이 모듈은 ``requests`` 에 의존하지 않는다 — 배포 워크플로가 의존성 설치 없이
``python -m bondmate.summary`` 로 current.json 에서 다시 만들 수 있어야 한다.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from bondmate import vc_publish

logger = logging.getLogger(__name__)

TOOL_ID = "bond-mate"
SUMMARY_FILE = "summary.json"
VERSION_FILE = "version.json"

# 계약 스키마의 키 모양. 어긋나는 키는 싣지 않는다(허브 검증에서 떨어지지 않게).
_RATE_KEY = re.compile(r"^[A-Z0-9_]{2,16}$")
_FX_KEY = re.compile(r"^[A-Z]{3}_[A-Z]{3}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# snapshot.sources 의 id → 사람이 읽는 이름·주소.
SOURCE_NAMES = {
    "finance-pi": ("finance-pi", None),
    "ecos": ("한국은행 ECOS", "https://ecos.bok.or.kr/"),
    "bis": ("BIS 중앙은행 정책금리", "https://data.bis.org/"),
    "mof": ("일본 재무성 국채 금리", "https://www.mof.go.jp/"),
    "fred": ("FRED", "https://fred.stlouisfed.org/"),
    "cnbc": ("CNBC", "https://www.cnbc.com/"),
    "naver": ("네이버 증권 환율", "https://finance.naver.com/"),
    "sec-edgar": ("SEC EDGAR", "https://www.sec.gov/edgar"),
}


def _num(value):
    """숫자면 그대로, 아니면 None. 모르는 값은 0 이 아니라 None 이다."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _date(value):
    return value if isinstance(value, str) and _DATE.match(value) else None


def _rate(quote: dict) -> dict:
    return {
        "country": quote.get("country"),
        "maturity": _num(quote.get("maturity")),
        "tenor": quote.get("tenor"),
        "value": _num(quote.get("value")),
        "change": _num(quote.get("change")),
        "changePct": _num(quote.get("change_pct")),
        "date": _date(quote.get("date")),
    }


def _fx(quote: dict) -> dict:
    return {
        "label": quote.get("label"),
        "value": _num(quote.get("value")),
        "change": _num(quote.get("change")),
        "changePct": _num(quote.get("change_pct")),
        "date": _date(quote.get("date")),
    }


def build_summary(snapshot: dict) -> dict:
    """current.json 스냅샷 → 계약 §6.8 ``data`` (camelCase, 히스토리 없음)."""
    highlights = snapshot.get("highlights") or {}
    offering = highlights.get("latest_offering")

    credit_spread = {}
    for rating, quote in (snapshot.get("credit") or {}).items():
        oas = (quote or {}).get("oas") or {}
        value = _num(oas.get("value"))
        if value is not None:
            credit_spread[rating] = round(value * 100, 1)       # %p → bp

    rates = {}
    for series_id, quote in sorted((snapshot.get("rates") or {}).items()):
        # 국가·만기를 모르는 시리즈는 계약(country 필수, maturity 숫자)에 못 싣는다.
        if not _RATE_KEY.match(series_id) or not isinstance(quote, dict):
            continue
        row = _rate(quote)
        if not isinstance(row["country"], str) or not _COUNTRY.match(row["country"]) or row["maturity"] is None:
            continue
        rates[series_id] = row

    fx = {
        pair: _fx(quote)
        for pair, quote in sorted((snapshot.get("fx") or {}).items())
        if _FX_KEY.match(pair) and isinstance(quote, dict)
    }

    return {
        "highlights": {
            "usCurveSpreadBp": _num(highlights.get("us_curve_spread_bp")),
            "usCurveInverted": highlights.get("us_curve_inverted")
            if isinstance(highlights.get("us_curve_inverted"), bool) else None,
            "krCurveSpreadBp": _num(highlights.get("kr_curve_spread_bp")),
            "igHySpreadBp": _num(highlights.get("ig_hy_spread_bp")),
        },
        "creditSpreadBp": credit_spread,
        "latestOffering": {
            "issuer": offering.get("issuer"),
            "issuerName": offering.get("issuer_name"),
            "filingDate": _date(offering.get("filing_date")),
            "totalAmount": _num(offering.get("total_amount")),
            "tranches": offering.get("tranches") if isinstance(offering.get("tranches"), int) else None,
        } if isinstance(offering, dict) else None,
        "rates": rates,
        "fx": fx,
    }


def as_of(snapshot: dict) -> str | None:
    """데이터가 설명하는 날짜 = 금리·환율 관측일 중 가장 늦은 날. 실행 시각이 아니다."""
    days = [
        quote.get("date")
        for section in ("rates", "fx")
        for quote in (snapshot.get(section) or {}).values()
        if isinstance(quote, dict) and _date(quote.get("date"))
    ]
    return max(days) if days else None


def sources(snapshot: dict) -> list[dict]:
    """이번 스냅샷에 값을 댄 소스들(순서 유지, 중복 제거)."""
    ids: list[str] = []
    for used in (snapshot.get("sources") or {}).values():
        for source_id in used or []:
            if source_id not in ids:
                ids.append(source_id)
    out = []
    for source_id in ids or ["fred"]:
        name, url = SOURCE_NAMES.get(source_id, (source_id, None))
        out.append({"id": source_id, "name": name, **({"url": url} if url else {})})
    return out


def build_envelope(snapshot: dict, *, generated_at=None) -> dict:
    day = as_of(snapshot)
    if day is None:
        raise vc_publish.EnvelopeError("스냅샷에 관측일이 하나도 없어 summary 를 만들 수 없습니다")
    return vc_publish.build_envelope(
        TOOL_ID,
        build_summary(snapshot),
        as_of=day,
        sources=sources(snapshot),
        generated_at=generated_at,
    )


def publish(data_dir: Path, snapshot: dict) -> bool:
    """``summary.json`` + ``version.json`` 을 쓴다. 내용이 같으면 건드리지 않는다.

    반환값은 summary 가 바뀌었는지. 스냅샷이 비어 만들 수 없으면 직전 파일을 둔다.
    """
    try:
        envelope = build_envelope(snapshot)
    except vc_publish.EnvelopeError as exc:
        # 수집 자체는 계속한다. 직전 summary 가 남으니 조용히 넘기지 않고 남긴다.
        logger.warning("summary.json 을 만들지 못해 직전 파일을 유지합니다 — %s", exc)
        return False
    changed = vc_publish.write_if_changed(data_dir / SUMMARY_FILE, envelope)
    vc_publish.write_version(data_dir / VERSION_FILE, {SUMMARY_FILE: envelope}, tool=TOOL_ID)
    return changed


def main(argv: list[str] | None = None) -> int:
    """current.json 만으로 summary 를 (다시) 만든다 — 네트워크 없음.

        python -m bondmate.summary --data data           # data/summary.json, data/version.json
        python -m bondmate.summary --data data --out _site
    """
    parser = argparse.ArgumentParser(description="bond-mate summary.json 생성 (current.json 에서, 오프라인)")
    parser.add_argument("--data", default="data", help="current.json 이 있는 디렉터리")
    parser.add_argument("--out", default=None, help="summary.json/version.json 을 쓸 디렉터리 (기본 --data)")
    args = parser.parse_args(argv)

    data_dir = Path(args.data)
    try:
        snapshot = json.loads((data_dir / "current.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"current.json 을 읽지 못했습니다 — {exc}", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else data_dir
    out.mkdir(parents=True, exist_ok=True)
    try:
        envelope = build_envelope(snapshot)
    except vc_publish.EnvelopeError as exc:
        print(f"summary 를 만들지 못했습니다 — {exc}", file=sys.stderr)
        return 1
    changed = vc_publish.write_if_changed(out / SUMMARY_FILE, envelope)
    vc_publish.write_version(out / VERSION_FILE, {SUMMARY_FILE: envelope}, tool=TOOL_ID)
    print(f"{out / SUMMARY_FILE} {'갱신' if changed else '변경 없음'} — asOf {envelope['asOf']}, "
          f"금리 {len(envelope['data']['rates'])} · 환율 {len(envelope['data']['fx'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
