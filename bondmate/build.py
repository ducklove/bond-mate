"""수집 → 병합 → published JSON 조립.

산출물 (``data/`` 아래, GitHub Pages 로 그대로 서빙된다)
    ``current.json``     최신 스냅샷. value-invest 가 읽는 계약 파일이다.
    ``rates.json``       국채·정책금리 히스토리
    ``fx.json``          환율 히스토리
    ``credit.json``      신용등급별 회사채 수익률·OAS 히스토리
    ``issuers.json``     발행사별 회사채 발행 이력
    ``summary.json``     value-invest 허브용 요약(Value Compass envelope v1,
                         :mod:`bondmate.summary`) — ``version.json`` 과 함께

타임스탬프
    ``generated_at``/``updated_at`` 은 **값이 마지막으로 바뀐 시각**이다. 수집 결과가
    직전과 같으면(타임스탬프를 뺀 내용이 같으면) 그대로 두고 ``checked_at`` 만
    새로 찍는다. 그래야 같은 데이터를 다시 받은 실행이 히스토리 파일을 바이트
    단위로 바꾸지 않고, 워크플로가 커밋·배포를 건너뛸 수 있다(:func:`publish_due`).

소스 우선순위
    같은 시리즈를 여러 소스가 주면 **먼저 얹힌 값이 이긴다**. 순서는

    1. finance-pi — 이미 정규화된 원본. 살아 있고 최신이면 이게 기준이다.
    2. 한국은행 ECOS — 국고채 전 만기·회사채. 한국물의 원본.
    3. BIS CBPOL — 주요국 중앙은행 정책금리(미국·유로존 제외).
    4. 일본 MOF — 일본 국채 전 만기 커브.
    5. FRED — 미국 커브·등급별 회사채·환율. 넓고 길지만 각국 10년물은 월간·지연.
    6. CNBC — 오늘자 시세만. 위 소스들이 아직 반영 못 한 최신 하루를 메운다.

    CNBC 와 (환율의) 네이버만 예외적으로 덮어쓴다. 나머지가 며칠 지연될 때
    스냅샷이 낡아 보이는 걸 막기 위해서다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from bondmate import catalog, history, summary
from bondmate.http import SourceError
from bondmate.sources import bis, cnbc, ecos, edgar, finance_pi, fred, mof, naver

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
SNAPSHOT_FILE = "current.json"
RATES_FILE = "rates.json"
FX_FILE = "fx.json"
CREDIT_FILE = "credit.json"
ISSUERS_FILE = "issuers.json"

# 스냅샷에 실을 최근 발행 건수 (전체 이력은 issuers.json 에 남는다).
RECENT_OFFERINGS = 40

# 값이 그대로여도 이 간격마다 한 번은 발행한다 — checked_at 이 사이트에 반영돼야
# 화면의 '수집 지연'(1시간) 표시가 정상 수집을 지연으로 오인하지 않는다.
HEARTBEAT = timedelta(minutes=45)

# 내용 비교에서 빼는 스냅샷 키 (시각만 담는다).
VOLATILE_KEYS = frozenset({"generated_at", "updated_at", "checked_at"})

# 시장별 updated_at 을 가르는 기준 — 스냅샷 섹션과 히스토리 파일.
MARKET_PARTS = {
    "rates": (("rates", "curves", "countries"), RATES_FILE),
    "fx": (("fx",), FX_FILE),
    "credit": (("credit", "credit_kr"), CREDIT_FILE),
}


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
    # allow_nan=False 는 방어선이다 — NaN/Infinity 는 표준 JSON 이 아니라
    # 브라우저가 파일 전체를 거부하는데, 기본값으로 두면 조용히 나가 버린다.
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )


def _digest(payload) -> str:
    """타임스탬프를 뺀 내용 비교용 해시(키 순서 무관)."""
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _without(payload: dict, keys=VOLATILE_KEYS) -> dict:
    return {k: v for k, v in (payload or {}).items() if k not in keys}


def _write_history(path: Path, body: dict, stamp: str) -> bool:
    """히스토리 파일을 쓴다. 내용이 직전과 같으면 직전 ``generated_at`` 을 유지한다.

    반환값은 내용이 바뀌었는지. 같으면 파일을 아예 다시 쓰지 않는다(바이트 그대로).
    """
    previous = read_json(path)
    changed = _digest(_without(previous)) != _digest(body)
    if not changed and previous.get("generated_at"):
        return False
    write_json(path, {"generated_at": stamp, **body})
    return True


def settle_timestamps(snapshot: dict, previous: dict, files_changed: dict[str, bool]) -> bool:
    """값이 그대로면 직전 ``generated_at``/``updated_at`` 을 되살리고 ``checked_at`` 을 찍는다.

    ``snapshot["generated_at"]`` 은 이번 실행 시각으로 들어와 있어야 한다.
    반환값은 발행 내용(스냅샷 또는 히스토리 파일)이 하나라도 바뀌었는지.
    """
    now = snapshot["generated_at"]
    prev_updated = previous.get("updated_at") or {}
    updated = {}
    for market, (keys, filename) in MARKET_PARTS.items():
        changed = files_changed.get(filename, False) or any(
            _digest(snapshot.get(k)) != _digest(previous.get(k)) for k in keys
        )
        updated[market] = prev_updated.get(market) if not changed and prev_updated.get(market) else now

    changed = (
        any(files_changed.values())
        or not previous.get("generated_at")
        or _digest(_without(snapshot)) != _digest(_without(previous))
    )
    if not changed:
        snapshot["generated_at"] = previous["generated_at"]
    snapshot["updated_at"] = updated
    snapshot["checked_at"] = now
    return changed


def publish_due(previous: dict, snapshot: dict, *, now: datetime | None = None) -> bool:
    """이번 결과를 data 브랜치에 커밋·배포해야 하는지.

    내용이 바뀌었거나(``generated_at`` 이 달라짐), 직전 발행의 ``checked_at`` 이
    :data:`HEARTBEAT` 보다 오래됐을 때만. ``previous`` 는 실행 전의 current.json.
    """
    if snapshot.get("generated_at") != previous.get("generated_at"):
        return True
    last = previous.get("checked_at") or previous.get("generated_at")
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except ValueError:
        return True
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - last_dt >= HEARTBEAT


def _round(value: float | None, digits: int = 4) -> float | None:
    """반올림. 비유한값은 None 으로 — allow_nan=False 에 걸리지 않도록."""
    return round(value, digits) if history._finite(value) else None


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

    # BIS CBPOL — 주요국 중앙은행 정책금리. FRED 는 미국·유로존만 커버해서
    # 이게 없으면 기준금리 화면이 미국과 유럽만 남는다.
    for name, collect in (("bis", bis.collect), ("mof", mof.collect), ("fred", fred.collect_rates)):
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


def collect_fx(*, use_finance_pi: bool = False, recent_only: bool = False,
               quote_metadata: dict | None = None) -> tuple[dict[str, dict[str, float]], list[str]]:
    merged: dict[str, dict[str, float]] = {}
    used: list[str] = []

    if use_finance_pi and not recent_only:
        try:
            _underlay(merged, finance_pi.collect_fx())
            used.append("finance-pi")
        except SourceError as exc:
            logger.warning("finance-pi fx 실패 — %s", exc)

    if not recent_only:
        try:
            _underlay(merged, fred.collect_fx())
            used.append("fred")
        except SourceError as exc:
            logger.warning("fred fx 실패 — %s", exc)

    # FRED 의 DEX* 는 주 1회 공표라 최대 일주일 밀린다 — 최근 구간만 덮어쓴다.
    try:
        _overlay(merged, naver.collect(quote_metadata=quote_metadata))
        used.append("naver")
    except SourceError as exc:
        logger.warning("네이버 환율 실패 — %s", exc)

    try:
        quotes = cnbc.fetch_fx_quotes()
        _overlay(merged, {pair: {q["date"]: q["value"]} for pair, q in quotes.items()})
        if quote_metadata is not None:
            quote_metadata.update(quotes)
        used.append("cnbc")
    except SourceError as exc:
        logger.warning("CNBC 환율 실패 — %s", exc)

    if recent_only and not merged:
        raise SourceError("최신 환율 소스가 모두 실패했습니다. 직전 데이터를 보존합니다.")

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
def _credit_kinds(prev_credit: dict) -> set[str]:
    """credit.json 의 종류 키(yield·oas·kr_yield …). ``generated_at`` 같은 값은 뺀다."""
    return {kind for kind, value in (prev_credit or {}).items() if isinstance(value, dict)}


def apply_fx_metadata(quotes: dict, metadata: dict, previous: dict) -> None:
    """원본 시세 시각과 전일대비를 붙인다. 오래된 메타데이터로 새 값을 꾸미지 않는다."""
    for pair, quote in quotes.items():
        meta = metadata.get(pair) or previous.get(pair, {})
        digits = catalog.FX_PAIRS.get(pair, {}).get("decimals", 4)
        if meta.get("date") != quote["date"] or _round(meta.get("value"), digits) != quote["value"]:
            continue
        for key in ("as_of", "source", "quote_type", "change", "change_pct"):
            if meta.get(key) is not None:
                quote[key] = meta[key]
        if meta.get("source") and "change" in meta:
            # 일별 히스토리의 직전 날짜가 원본 전일 종가의 날짜라는 보장은 없다.
            quote.pop("prev_date", None)


def refresh_fx(data_dir: Path = DATA_DIR) -> dict:
    """5분 간격 환율 수집. 금리·신용·발행 데이터와 파일은 그대로 유지한다."""
    snapshot = read_json(data_dir / SNAPSHOT_FILE)
    if not snapshot.get("generated_at"):
        raise SourceError("환율 단독 갱신 전에 전체 데이터를 한 번 수집해야 합니다.")
    metadata: dict[str, dict] = {}
    incoming, sources = collect_fx(recent_only=True, quote_metadata=metadata)
    previous = read_json(data_dir / FX_FILE).get("series", {})
    stored = {
        pair: history.store(previous.get(pair), incoming.get(pair, {}), today=date.today())
        for pair in sorted(previous.keys() | incoming.keys())
    }
    fresh = build_snapshot({}, {p: history.decode(v) for p, v in stored.items()}, {}, [], sources={})
    apply_fx_metadata(fresh["fx"], metadata, snapshot.get("fx", {}))
    before = json.loads(json.dumps(snapshot))
    before.setdefault("updated_at", {"rates": snapshot["generated_at"],
                                     "credit": snapshot["generated_at"],
                                     "fx": snapshot["generated_at"]})
    snapshot["generated_at"] = fresh["generated_at"]
    snapshot["fx"] = fresh["fx"]
    previous_sources = snapshot.setdefault("sources", {}).get("fx", [])
    snapshot["sources"]["fx"] = list(dict.fromkeys([*previous_sources, *sources]))
    fx_changed = _write_history(data_dir / FX_FILE, {"series": stored}, fresh["generated_at"])
    settle_timestamps(snapshot, before, {FX_FILE: fx_changed})
    write_json(data_dir / SNAPSHOT_FILE, snapshot)
    summary.publish(data_dir, snapshot)
    return snapshot


def run(
    data_dir: Path = DATA_DIR,
    *,
    skip_issuers: bool = False,
    reset_series: set[str] | None = None,
) -> dict:
    """수집·병합·기록을 한 번 수행하고 스냅샷을 돌려준다.

    히스토리는 ``data_dir`` 에 있던 직전 결과 위에 upsert 한다 — 소스가 과거를
    사후 정정하는 경우가 있어 append 가 아니라 병합이어야 한다.

    ``reset_series`` 는 그 upsert 규칙의 탈출구다. **한 시리즈의 소스를 바꾸면**
    옛 소스가 남긴 관측치가 그대로 살아남는데, 새 소스보다 날짜가 뒤면 그게
    최신값 자리를 차지해 버린다(영국 정책금리를 SONIA 에서 BIS Bank Rate 로
    옮겼을 때 실제로 겪었다: BIS 는 08-24 까지라 08-25·26 의 SONIA 값이 계속
    노출됐다). 여기 넣은 시리즈는 직전 히스토리를 버리고 새 소스로만 다시 쌓는다.
    """
    reset_series = reset_series or set()
    data_dir.mkdir(parents=True, exist_ok=True)
    today = date.today()

    # 프로브는 한 번만 — 금리·환율 수집이 같은 판단을 공유한다.
    use_finance_pi = finance_pi.probe()

    rates, kr_credit, rate_sources = collect_rates(use_finance_pi=use_finance_pi)
    fx_metadata: dict[str, dict] = {}
    fx, fx_sources = collect_fx(use_finance_pi=use_finance_pi, quote_metadata=fx_metadata)
    credit, credit_sources = collect_credit(kr_credit)

    prev_rates = read_json(data_dir / RATES_FILE).get("series", {})
    prev_fx = read_json(data_dir / FX_FILE).get("series", {})
    prev_credit = read_json(data_dir / CREDIT_FILE)

    for series in reset_series:
        dropped = [prev_rates.pop(series, None), prev_fx.pop(series, None)]
        for kind in _credit_kinds(prev_credit):
            dropped.append(prev_credit[kind].pop(series, None))
        if any(d is not None for d in dropped):
            logger.info("%s 히스토리를 버리고 새 소스로 다시 쌓습니다", series)

    # 직전 히스토리와 이번 수집의 **합집합**을 저장한다. 소스 하나가 이번 실행에서
    # 실패해도(MOF 는 이번 달 CSV 만 주므로 한 번 빠지면 복구가 안 된다) 쌓아 둔
    # 히스토리가 사라지지 않게 — 환율과 같은 규칙이다. 리셋 대상은 위에서
    # prev_* 에서 뺐으므로 이번에 다시 받지 못했다면 남지 않는다.
    stored_rates = {
        series: history.store(prev_rates.get(series), rates.get(series, {}), today=today)
        for series in sorted(prev_rates.keys() | rates.keys())
    }
    stored_fx = {
        series: history.store(prev_fx.get(series), fx.get(series, {}), today=today)
        for series in sorted(prev_fx.keys() | fx.keys())
    }
    stored_credit: dict[str, dict] = {}
    for kind in sorted(_credit_kinds(prev_credit) | credit.keys()):
        prev_by_rating = prev_credit.get(kind) if isinstance(prev_credit.get(kind), dict) else {}
        new_by_rating = credit.get(kind) or {}
        stored_credit[kind] = {
            rating: history.store(prev_by_rating.get(rating), new_by_rating.get(rating, {}), today=today)
            for rating in sorted(prev_by_rating.keys() | new_by_rating.keys())
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
    previous = read_json(data_dir / SNAPSHOT_FILE)
    apply_fx_metadata(snapshot["fx"], fx_metadata, previous.get("fx", {}))
    files_changed = {
        RATES_FILE: _write_history(data_dir / RATES_FILE, {"series": stored_rates}, stamp),
        FX_FILE: _write_history(data_dir / FX_FILE, {"series": stored_fx}, stamp),
        CREDIT_FILE: _write_history(data_dir / CREDIT_FILE, stored_credit, stamp),
        ISSUERS_FILE: _write_history(data_dir / ISSUERS_FILE, {"offerings": offerings}, stamp),
    }
    settle_timestamps(snapshot, previous, files_changed)
    write_json(data_dir / SNAPSHOT_FILE, snapshot)
    summary.publish(data_dir, snapshot)

    logger.info(
        "완료 — 금리 %d · 환율 %d · 등급 %d · 발행 %d",
        len(stored_rates), len(stored_fx), len(stored_credit.get("yield", {})), len(offerings),
    )
    return snapshot
