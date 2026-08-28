"""수집 → 병합 → published JSON 조립.

산출물 (``data/`` 아래, GitHub Pages 로 그대로 서빙된다)
    ``current.json``     최신 스냅샷. value-invest 가 읽는 계약 파일이다.
    ``rates.json``       국채·정책금리 히스토리
    ``fx.json``          환율 히스토리
    ``credit.json``      신용등급별 회사채 수익률·OAS 히스토리
    ``issuers.json``     발행사별 회사채 발행 이력

소스 우선순위
    같은 시리즈를 여러 소스가 주면 **먼저 얹힌 값이 이긴다**. 순서는

    1. finance-pi — 이미 정규화된 원본. 살아 있으면 이게 기준이다.
    2. 각국 공식 소스 — 일본 MOF(전 만기 커브).
    3. FRED — 넓고 길지만 각국 10년물은 월간·지연.
    4. CNBC — 오늘자 시세만. 위 소스들이 아직 반영 못 한 최신 하루를 메운다.

    CNBC 만 예외적으로 덮어쓴다. 나머지가 며칠 지연될 때 스냅샷이 낡아 보이는
    걸 막기 위해서다.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

from bondmate import catalog, history
from bondmate.http import SourceError
from bondmate.sources import cnbc, ecos, edgar, finance_pi, fred, mof, naver

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
SNAPSHOT_FILE = "current.json"
RATES_FILE = "rates.json"
FX_FILE = "fx.json"
CREDIT_FILE = "credit.json"
ISSUERS_FILE = "issuers.json"

# 스냅샷에 실을 최근 발행 건수 (전체 이력은 issuers.json 에 남는다).
RECENT_OFFERINGS = 40


# --- 유틸 --------------------------------------------------------------------
def _underlay(base: dict[str, dict[str, float]], incoming: dict[str, dict[str, float]]) -> None:
    """빈 날짜만 채운다(기존 값 보존) — 우선순위 낮은 소스를 얹을 때."""
    for series, points in incoming.items():
        target = base.setdefault(series, {})
        for day, value in points.items():
            target.setdefault(day, value)


def _overlay(base: dict[str, dict[str, float]], incoming: dict[str, dict[str, float]]) -> None:
    """같은 날짜여도 덮어쓴다 — 더 신선한 소스를 얹을 때."""
    for series, points in incoming.items():
        base.setdefault(series, {}).update(points)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 공백을 줄여 Pages 전송량을 아낀다. ensure_ascii=False 로 한글 라벨이 그대로.
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


# --- 수집 --------------------------------------------------------------------
def collect_rates(
    *, use_finance_pi: bool = False
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]], list[str]]:
    """``(국채·정책금리, 한국 등급별 회사채, 사용한 소스들)``."""
    merged: dict[str, dict[str, float]] = {}
    kr_credit: dict[str, dict[str, float]] = {}
    used: list[str] = []

    if use_finance_pi:
        try:
            _underlay(merged, finance_pi.collect_rates())
            used.append("finance-pi")
        except SourceError as exc:
            logger.warning("finance-pi rates 실패 — %s", exc)

    # 각국 공식 소스 — 한국은행 ECOS(국고채 전 만기)와 일본 재무성(전 만기 커브).
    if ecos.enabled():
        try:
            kr_rates, kr_credit = ecos.collect()
            _underlay(merged, kr_rates)
            used.append("ecos")
        except SourceError as exc:
            logger.warning("ECOS 실패 — %s", exc)

    for name, collect in (("mof", mof.collect), ("fred", fred.collect_rates)):
        try:
            _underlay(merged, collect())
            used.append(name)
        except SourceError as exc:
            logger.warning("%s rates 실패 — %s", name, exc)

    # CNBC 는 오늘자 한 점뿐이지만 가장 신선하다 — 마지막에 덮어쓴다.
    try:
        quotes = cnbc.fetch_quotes()
        today = date.today().isoformat()
        _overlay(
            merged,
            {code: {(q["date"] or today): q["value"]} for code, q in quotes.items()},
        )
        used.append("cnbc")
    except SourceError as exc:
        logger.warning("cnbc 실패 — %s", exc)

    return merged, kr_credit, used


def collect_fx(*, use_finance_pi: bool = False) -> tuple[dict[str, dict[str, float]], list[str]]:
    merged: dict[str, dict[str, float]] = {}
    used: list[str] = []

    if use_finance_pi:
        try:
            _underlay(merged, finance_pi.collect_fx())
            used.append("finance-pi")
        except SourceError as exc:
            logger.warning("finance-pi fx 실패 — %s", exc)

    try:
        _underlay(merged, fred.collect_fx())
        used.append("fred")
    except SourceError as exc:
        logger.warning("fred fx 실패 — %s", exc)

    # FRED 의 DEX* 는 주 1회 공표라 최대 일주일 밀린다 — 최근 구간만 덮어쓴다.
    try:
        _overlay(merged, naver.collect())
        used.append("naver")
    except SourceError as exc:
        logger.warning("네이버 환율 실패 — %s", exc)

    return merged, used


def collect_credit(
    kr_credit: dict[str, dict[str, float]] | None = None,
) -> tuple[dict[str, dict[str, dict[str, float]]], list[str]]:
    """미국 등급별 커브(ICE BofA) + 한국 등급별 회사채(ECOS)."""
    used: list[str] = []
    try:
        credit = fred.collect_credit()
        used.append("fred")
    except SourceError as exc:
        logger.warning("등급별 회사채 수집 실패 — %s", exc)
        credit = {"yield": {}, "oas": {}}

    if kr_credit:
        credit["kr_yield"] = kr_credit
        used.append("ecos")
    return credit, used


def collect_issuers(tickers: list[str] | None = None) -> list[dict]:
    """발행사별 회사채 발행 이력(최신 발행일 순)."""
    wanted = tickers or list(catalog.ISSUERS)
    offerings: list[dict] = []
    for ticker in wanted:
        meta = catalog.ISSUERS.get(ticker)
        if not meta:
            continue
        found = edgar.collect_issuer(ticker, meta["cik"])
        logger.info("EDGAR %s — 발행 %d건", ticker, len(found))
        offerings.extend(found)
    return sorted(offerings, key=lambda o: o["filing_date"], reverse=True)


# --- 스냅샷 조립 --------------------------------------------------------------
def _quote(points: dict[str, float], decimals: int = 4) -> dict | None:
    """최신값 + 전일대비. 히스토리 두 점에서 만든다."""
    last, prev = history.latest_two(points)
    if not last:
        return None
    day, value = last
    quote = {"date": day, "value": _round(value, decimals)}
    if prev:
        change = value - prev[1]
        quote["change"] = _round(change, decimals)
        quote["change_pct"] = _round(change / prev[1] * 100, 3) if prev[1] else None
        quote["prev_date"] = prev[0]
    return quote


def _rate_meta(series_id: str) -> dict:
    """``US10Y`` → 국가·만기 메타. 카탈로그 규약에 맞춰 되돌린다."""
    for country in catalog.COUNTRIES:
        if not series_id.startswith(country):
            continue
        suffix = series_id[len(country) :]
        if suffix == "_BASE":
            return {"country": country, "tenor": "기준금리", "maturity": catalog.POLICY_MATURITY}
        if suffix == "_ON":
            return {"country": country, "tenor": "익일물", "maturity": catalog.OVERNIGHT_MATURITY}
        if suffix.lstrip("_") in catalog.TENORS:
            tenor = suffix.lstrip("_")
            return {
                "country": country,
                "tenor": catalog.tenor_label(tenor),
                "maturity": catalog.TENORS[tenor],
            }
    return {"country": None, "tenor": None, "maturity": None}


def build_snapshot(
    rates: dict[str, dict[str, float]],
    fx: dict[str, dict[str, float]],
    credit: dict[str, dict[str, dict[str, float]]],
    offerings: list[dict],
    *,
    sources: dict[str, list[str]],
) -> dict:
    """프론트와 value-invest 가 함께 읽는 최신 스냅샷."""
    rate_quotes: dict[str, dict] = {}
    for series_id, points in rates.items():
        quote = _quote(points, decimals=4)
        if not quote:
            continue
        meta = _rate_meta(series_id)
        country = meta["country"]
        rate_quotes[series_id] = {
            **quote,
            **meta,
            "country_name": (catalog.COUNTRIES.get(country) or {}).get("name") if country else None,
        }

    fx_quotes: dict[str, dict] = {}
    for pair, points in fx.items():
        meta = catalog.FX_PAIRS.get(pair)
        quote = _quote(points, decimals=(meta or {}).get("decimals", 4))
        if quote:
            fx_quotes[pair] = {**quote, "label": (meta or {}).get("label", pair)}

    credit_quotes: dict[str, dict] = {}
    for rating, meta in catalog.RATINGS.items():
        yield_quote = _quote(credit.get("yield", {}).get(rating, {}), decimals=3)
        oas_quote = _quote(credit.get("oas", {}).get(rating, {}), decimals=3)
        if not yield_quote and not oas_quote:
            continue
        credit_quotes[rating] = {
            "label": meta["label"],
            "order": meta["order"],
            "investment_grade": meta["investment_grade"],
            "color": meta["color"],
            "yield": yield_quote,
            "oas": oas_quote,
        }

    # 한국 회사채는 등급 체계(AA-/BBB-)와 만기(3년 고정)가 미국 지수와 달라
    # 같은 커브에 섞지 않고 따로 싣는다.
    kr_credit_quotes = {
        rating: {**quote, "label": f"회사채 3년 {rating}"}
        for rating, points in (credit.get("kr_yield") or {}).items()
        if (quote := _quote(points, decimals=3))
    }

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": sources,
        "countries": {
            code: {**meta, "has_curve": _curve_depth(rate_quotes, code) >= 3}
            for code, meta in catalog.COUNTRIES.items()
        },
        "rates": rate_quotes,
        "fx": fx_quotes,
        "credit": credit_quotes,
        "credit_kr": kr_credit_quotes,
        "curves": build_curves(rate_quotes),
        "offerings": offerings[:RECENT_OFFERINGS],
        "issuers": {t: catalog.ISSUERS[t] for t in catalog.ISSUERS},
        "highlights": build_highlights(rate_quotes, credit_quotes, offerings),
    }


def _curve_depth(rate_quotes: dict[str, dict], country: str) -> int:
    return sum(
        1
        for q in rate_quotes.values()
        if q.get("country") == country and (q.get("maturity") or -1) > 0
    )


def build_curves(rate_quotes: dict[str, dict]) -> dict[str, list[dict]]:
    """국가별 수익률 곡선. 만기 오름차순이고 정책금리(-1)도 앞에 포함한다."""
    curves: dict[str, list[dict]] = {}
    for series_id, quote in rate_quotes.items():
        country = quote.get("country")
        if not country or quote.get("maturity") is None:
            continue
        curves.setdefault(country, []).append(
            {
                "series_id": series_id,
                "tenor": quote.get("tenor"),
                "maturity": quote["maturity"],
                "value": quote.get("value"),
                "change": quote.get("change"),
                "date": quote.get("date"),
            }
        )
    for points in curves.values():
        points.sort(key=lambda p: p["maturity"])
    return curves


def build_highlights(
    rate_quotes: dict[str, dict], credit_quotes: dict[str, dict], offerings: list[dict]
) -> dict:
    """한눈 요약 — value-invest 인사이트 카드와 임베드 헤더가 쓴다."""

    def value_of(series_id: str) -> float | None:
        return (rate_quotes.get(series_id) or {}).get("value")

    us2, us10 = value_of("US2Y"), value_of("US10Y")
    kr3, kr10 = value_of("KR3Y"), value_of("KR10Y")

    highlights = {
        "us_curve_spread_bp": _round((us10 - us2) * 100, 1) if us2 is not None and us10 is not None else None,
        "us_curve_inverted": (us10 < us2) if us2 is not None and us10 is not None else None,
        "kr_curve_spread_bp": _round((kr10 - kr3) * 100, 1) if kr3 is not None and kr10 is not None else None,
        "ig_hy_spread_bp": None,
        "latest_offering": None,
    }

    bbb = (credit_quotes.get("BBB") or {}).get("oas") or {}
    ccc = (credit_quotes.get("CCC") or {}).get("oas") or {}
    if bbb.get("value") is not None and ccc.get("value") is not None:
        highlights["ig_hy_spread_bp"] = _round((ccc["value"] - bbb["value"]) * 100, 1)

    if offerings:
        newest = offerings[0]
        highlights["latest_offering"] = {
            "issuer": newest["issuer"],
            "issuer_name": catalog.issuer_label(newest["issuer"]),
            "filing_date": newest["filing_date"],
            "total_amount": newest["total_amount"],
            "tranches": len(newest["tranches"]),
        }
    return highlights


# --- 엔트리포인트 -------------------------------------------------------------
def run(data_dir: Path = DATA_DIR, *, skip_issuers: bool = False) -> dict:
    """수집·병합·기록을 한 번 수행하고 스냅샷을 돌려준다.

    히스토리는 ``data_dir`` 에 있던 직전 결과 위에 upsert 한다 — 소스가 과거를
    사후 정정하는 경우가 있어 append 가 아니라 병합이어야 한다.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    today = date.today()

    # 프로브는 한 번만 — 금리·환율 수집이 같은 판단을 공유한다.
    use_finance_pi = finance_pi.probe()

    rates, kr_credit, rate_sources = collect_rates(use_finance_pi=use_finance_pi)
    fx, fx_sources = collect_fx(use_finance_pi=use_finance_pi)
    credit, credit_sources = collect_credit(kr_credit)

    prev_rates = read_json(data_dir / RATES_FILE).get("series", {})
    prev_fx = read_json(data_dir / FX_FILE).get("series", {})
    prev_credit = read_json(data_dir / CREDIT_FILE)

    stored_rates = {
        series: history.store(prev_rates.get(series), points, today=today)
        for series, points in rates.items()
    }
    stored_fx = {
        series: history.store(prev_fx.get(series), points, today=today)
        for series, points in fx.items()
    }
    stored_credit = {
        kind: {
            rating: history.store(
                (prev_credit.get(kind) or {}).get(rating), points, today=today
            )
            for rating, points in by_rating.items()
        }
        for kind, by_rating in credit.items()
    }

    if skip_issuers:
        offerings = read_json(data_dir / ISSUERS_FILE).get("offerings", [])
        issuer_sources: list[str] = []
    else:
        offerings = collect_issuers()
        issuer_sources = ["sec-edgar"]
        # 수집이 통째로 실패했으면 직전 결과를 지키는 편이 낫다.
        if not offerings:
            offerings = read_json(data_dir / ISSUERS_FILE).get("offerings", [])
            issuer_sources = []

    # 스냅샷은 저장된 히스토리에서 뽑는다 — 화면의 값과 차트의 끝점이 항상 같도록.
    decoded_rates = {s: history.decode(p) for s, p in stored_rates.items()}
    decoded_fx = {s: history.decode(p) for s, p in stored_fx.items()}
    decoded_credit = {
        kind: {r: history.decode(p) for r, p in by_rating.items()}
        for kind, by_rating in stored_credit.items()
    }

    snapshot = build_snapshot(
        decoded_rates,
        decoded_fx,
        decoded_credit,
        offerings,
        sources={
            "rates": rate_sources,
            "fx": fx_sources,
            "credit": credit_sources,
            "issuers": issuer_sources,
        },
    )

    stamp = snapshot["generated_at"]
    write_json(data_dir / RATES_FILE, {"generated_at": stamp, "series": stored_rates})
    write_json(data_dir / FX_FILE, {"generated_at": stamp, "series": stored_fx})
    write_json(data_dir / CREDIT_FILE, {"generated_at": stamp, **stored_credit})
    write_json(data_dir / ISSUERS_FILE, {"generated_at": stamp, "offerings": offerings})
    write_json(data_dir / SNAPSHOT_FILE, snapshot)

    logger.info(
        "완료 — 금리 %d · 환율 %d · 등급 %d · 발행 %d",
        len(stored_rates), len(stored_fx), len(stored_credit.get("yield", {})), len(offerings),
    )
    return snapshot
