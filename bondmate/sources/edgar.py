"""SEC EDGAR 소스 — 대형 발행사의 회사채 발행 조건과 조달금리.

무엇을 읽는가
    회사가 채권을 발행할 때 가격이 확정되면 **pricing term sheet** 를 Rule 433
    자유작성투자설명서(FWP)로, 최종 투자설명서 보충자료를 424B2/424B5 로
    제출한다. FWP 는 트랜치별로 다음을 표 형태로 담는다::

        Principal Amount:             $3,000,000,000
        Maturity:                     February 4, 2029
        Coupon:                       4.550%
        Benchmark Treasury Yield:     3.646%
        Spread to Benchmark Treasury: +95 basis points
        Yield to Maturity:            4.596%
        Expected Ratings:             Baa2 / BBB / BBB

    즉 **실제 조달금리(YTM)와 같은 만기 국채 대비 스프레드**가 그대로 들어 있다.
    XBRL 재무제표(``DebtInstrumentFaceAmount`` 등)는 차원 정보가 소실돼 트랜치를
    복원할 수 없어 쓰지 않는다.

왜 관대하게 파싱하는가
    term sheet 은 자유 서식이라 발행사·주관사마다 라벨과 표 구조가 조금씩 다르다.
    그래서 라벨을 정규화해 별칭으로 묶고, 못 읽은 항목은 ``None`` 으로 남긴다 —
    한 항목이 비어도 트랜치 자체는 살린다.

SEC 는 연락처가 담긴 User-Agent 와 초당 10회 이하 요청을 요구한다
(:mod:`bondmate.http` 의 ``USER_AGENT``, 아래 ``REQUEST_INTERVAL``).
"""

from __future__ import annotations

import html
import logging
import re
import time
from datetime import date

from bondmate.http import SourceError, fetch

logger = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{document}"

# 채권 가격결정 정보를 담는 서식. FWP(pricing term sheet)가 가장 정제돼 있고,
# 424B2/424B5 는 FWP 를 내지 않은 발행 건을 메우는 보완용이다.
# 424B3 은 기발행 채권의 교환청약(exchange offer)이라 신규 조달이 아니므로 제외.
BOND_FORMS = ("FWP", "424B2", "424B5")
PRIMARY_FORM = "FWP"

# 같은 발행 건이 FWP 와 424B 로 며칠 사이에 두 번 올라온다. 이 안에 들어오면
# 중복으로 보고 FWP 쪽만 남긴다.
DUPLICATE_WINDOW_DAYS = 7

# SEC 공정이용 가이드라인: 초당 10건 이하.
REQUEST_INTERVAL = 0.15
_last_request = 0.0


def _throttle() -> None:
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)
    _last_request = time.monotonic()


# --- 문서 텍스트화 -----------------------------------------------------------
# 표 셀 경계를 살려야 "라벨:" 과 "값" 을 짝지을 수 있어서, 태그를 공백이 아니라
# 파이프로 치환한다.
_TAG = re.compile(r"(?s)<[^>]+>")
_SCRIPT = re.compile(r"(?is)<(script|style)\b.*?</\1>")
_PIPES = re.compile(r"(\s*\|\s*)+")

# 스마트 인용부호·비분리 공백을 평문으로 눕힌다(라벨 매칭이 깨지지 않도록).
_SMART_QUOTES = str.maketrans({
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "\xa0": " ",
})


def to_tokens(document: str) -> list[str]:
    text = _SCRIPT.sub(" ", document)
    text = _TAG.sub("|", text)
    text = html.unescape(text)
    text = text.translate(_SMART_QUOTES)
    text = _PIPES.sub("|", text)
    # 셀 안의 줄바꿈은 단어를 갈라놓을 뿐이라("Floating\nRate Notes") 공백으로 눕힌다.
    return [re.sub(r"\s+", " ", token).strip() for token in text.split("|") if token.strip()]


# --- 값 파서 -----------------------------------------------------------------
_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(billion|million|thousand)?", re.I)
_MULTIPLIER = {"billion": 1e9, "million": 1e6, "thousand": 1e3}
_PERCENT = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_SPREAD = re.compile(r"([+-]?\s*\d+(?:\.\d+)?)\s*(?:basis points|bps|bp)\b", re.I)
_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),?\s+(\d{4})\b",
    re.I,
)
_MONTHS = {
    name: number
    for number, name in enumerate(
        [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ],
        start=1,
    )
}


def parse_money(text: str) -> float | None:
    match = _MONEY.search(text or "")
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return value * _MULTIPLIER.get((match.group(2) or "").lower(), 1.0)


def parse_percent(text: str) -> float | None:
    match = _PERCENT.search(text or "")
    return float(match.group(1)) if match else None


def parse_spread_bp(text: str) -> float | None:
    match = _SPREAD.search(text or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(" ", ""))
    except ValueError:
        return None


def parse_date(text: str) -> str | None:
    match = _DATE.search(text or "")
    if not match:
        return None
    month = _MONTHS.get(match.group(1).lower())
    if not month:
        return None
    return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(2)):02d}"


# --- 라벨 정규화 -------------------------------------------------------------
# 발행사마다 표현이 달라 별칭을 하나의 필드로 모은다.
FIELD_ALIASES = {
    "principal_amount": ("principal amount", "aggregate principal amount", "size", "offering size"),
    "maturity_date": ("maturity", "maturity date", "stated maturity"),
    "coupon": ("coupon", "interest rate", "coupon rate"),
    "price_to_public": ("price to public", "issue price", "public offering price"),
    "benchmark": ("benchmark treasury", "benchmark", "benchmark security"),
    "benchmark_yield": ("benchmark treasury yield", "benchmark yield"),
    "spread_bp": (
        "spread to benchmark treasury",
        "spread to benchmark",
        "re-offer spread",
        "reoffer spread",
    ),
    "yield_to_maturity": ("yield to maturity", "re-offer yield", "reoffer yield", "yield"),
    "ratings": ("expected ratings", "ratings", "expected security ratings"),
    "cusip": ("cusip / isin numbers", "cusip/isin", "cusip", "cusip numbers"),
    # Broadcom 형: "$750,000,000 aggregate principal amount of 4.300% Senior
    # Notes due 2031" 처럼 금액·쿠폰·만기가 한 줄에 함께 온다.
    "securities_offered": ("securities offered", "notes offered", "securities"),
}

_LABEL_LOOKUP = {alias: field for field, aliases in FIELD_ALIASES.items() for alias in aliases}


_LABEL_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")


def normalize_label(token: str) -> str | None:
    """``"Expected Ratings (Moody's / S&P / Fitch):*"`` -> ``"ratings"``.

    각주 표시(``*``)는 콜론 앞뒤 어디에 붙어도 무시하고, 라벨 뒤의 괄호 주석
    (평가사 목록 등)도 떼어낸 뒤 별칭 표를 찾는다.
    """
    key = token.strip().strip("*").strip().rstrip(":").strip().strip("*").strip()
    key = _LABEL_PARENTHETICAL.sub("", key).lower()
    return _LABEL_LOOKUP.get(re.sub(r"\s+", " ", key))


# 트랜치 제목: "4.550% Notes due 2029", "Floating Rate Notes due 2029",
# "5.700% Senior Notes due 2036" 등.
_TRANCHE_HEADING = re.compile(
    r"^(?:(\d+\.\d+)\s*%\s+)?(?:(?:Floating Rate|Fixed Rate|Senior|Global)\s+)*Notes?\s+due\s+(\d{4})",
    re.I,
)


# 제목 뒤에 붙는 정의 별칭(예: ``("2029 Fixed Rate Notes")``)은 표시에 불필요하다.
_HEADING_ALIAS = re.compile(r"\s*\(.*$")

# 행렬형 term sheet 의 값 토큰은 자기 트랜치를 앞에 달고 있다:
#   "2031 Notes: $3,500,000,000" / "2028 Floating Rate Notes: August 10, 2028"
_VALUE_PREFIX = re.compile(r"^(\d{4})\s+((?:Floating Rate\s+)?)Notes?\s*:\s*(.+)$", re.I)

# Meta 형은 트랜치 키와 값이 아예 다른 셀에 있다:
#   "Principal Amount:" / "2031 Notes:" / "$3,000,000,000"
# 콜론으로 끝나지만 라벨이 아니라 **다음 값이 어느 트랜치 것인지 가리키는 선택자**다.
_TRANCHE_SELECTOR = re.compile(r"^(\d{4})\s+((?:Floating Rate\s+)?)Notes?\s*:\s*$", re.I)

# 금액·쿠폰·만기를 한 줄에 담은 표지/‘Securities Offered’ 줄.
#   "$750,000,000 aggregate principal amount of 4.300% Senior Notes due 2031"
#   "$3,000,000,000 of 4.550% Notes Due 2029"
_COMBINED_FIXED = re.compile(
    r"^\$\s?([\d,]+(?:\.\d+)?)\b.*?(\d+\.\d+)\s*%.*?\bNotes?\s+due\s+(\d{4})", re.I
)
_COMBINED_FLOATING = re.compile(
    r"^\$\s?([\d,]+(?:\.\d+)?)\b.*?\bFloating Rate Notes?\s+due\s+(\d{4})", re.I
)

# 발행 건 전체에 걸리는 항목(트랜치별로 다르지 않다).
OFFERING_FIELDS = {"ratings"}


def _tranche_key(maturity_year: int, floating: bool) -> tuple[int, bool]:
    """같은 해에 고정·변동이 같이 나오므로 둘을 함께 키로 쓴다."""
    return (maturity_year, floating)


def _security_label(heading: str | None, maturity_year: int, floating: bool, coupon: float | None) -> str:
    """표시용 종목명. 제목 토큰이 없으면(행렬형) 만기·쿠폰으로 만들어 준다."""
    if heading:
        return _HEADING_ALIAS.sub("", heading).strip()
    if floating:
        return f"Floating Rate Notes due {maturity_year}"
    if coupon is not None:
        return f"{coupon:.3f}% Notes due {maturity_year}"
    return f"Notes due {maturity_year}"


def _blank_tranche(heading: str, coupon_pct: float | None, maturity_year: int, floating: bool) -> dict:
    return {
        "security": heading,
        "maturity_year": maturity_year,
        "coupon_pct": coupon_pct,
        "floating": floating,
        "principal_amount": None,
        "maturity_date": None,
        "price_to_public": None,
        "benchmark": None,
        "benchmark_yield_pct": None,
        "spread_bp": None,
        "yield_to_maturity_pct": None,
        "ratings": None,
        "cusip": None,
    }


def _is_label(token: str) -> bool:
    """콜론으로 끝나면 라벨이다 — 단, 트랜치 선택자는 값 구간의 일부다."""
    return token.rstrip("*").rstrip().endswith(":") and not _TRANCHE_SELECTOR.match(token)


def parse_pricing_term_sheet(document: str) -> list[dict]:
    """FWP/424B 문서에서 트랜치별 발행조건을 뽑는다.

    term sheet 은 발행사에 따라 두 가지 배치를 쓴다. 둘 다 지원한다.

    **순차형** (Oracle) — 트랜치마다 제목이 나오고 그 아래 조건이 붙는다::

        4.550% Notes due 2029
        Principal Amount: | $3,000,000,000
        Yield to Maturity: | 4.596%

    **행렬형** (Alphabet) — 라벨 하나에 트랜치별 값이 줄줄이 붙고, 각 값이
    자기 트랜치를 접두사로 달고 있다::

        Aggregate Principal Amount:
        2031 Notes: $3,500,000,000
        2033 Notes: $2,500,000,000

    그래서 값을 배정할 때 **접두사가 있으면 그 트랜치로, 없으면 직전 제목의
    트랜치로** 보낸다. 한 필드는 먼저 채워진 값을 지키므로(선착순) 문서 뒤쪽의
    요약표나 각주가 앞서 읽은 정확한 값을 덮어쓰지 못한다.
    """
    tokens = to_tokens(document)

    tranches: dict[tuple[int, bool], dict] = {}
    offering: dict[str, str] = {}
    current: dict | None = None

    def ensure(
        maturity_year: int,
        floating: bool,
        *,
        heading: str | None = None,
        coupon: float | None = None,
    ) -> dict:
        key = _tranche_key(maturity_year, floating)
        tranche = tranches.get(key)
        if tranche is None:
            tranche = _blank_tranche(
                _security_label(heading, maturity_year, floating, coupon),
                coupon,
                maturity_year,
                floating,
            )
            tranches[key] = tranche
            return tranche
        if tranche["coupon_pct"] is None and coupon is not None:
            tranche["coupon_pct"] = coupon
            # 쿠폰을 뒤늦게 알았으면 합성 라벨도 함께 정확해진다.
            if tranche["security"] == f"Notes due {maturity_year}":
                tranche["security"] = _security_label(None, maturity_year, floating, coupon)
        if heading and tranche["security"].startswith(("Notes due", "Floating Rate Notes due")):
            tranche["security"] = _security_label(heading, maturity_year, floating, coupon)
        return tranche

    def absorb_combined(token: str) -> bool:
        """금액·쿠폰·만기가 한 줄에 있는 표지 줄을 트랜치로 흡수한다."""
        fixed = _COMBINED_FIXED.match(token)
        if fixed:
            tranche = ensure(int(fixed.group(3)), False, coupon=float(fixed.group(2)))
            _assign(tranche, "principal_amount", f"${fixed.group(1)}")
            return True
        floating = _COMBINED_FLOATING.match(token)
        if floating:
            tranche = ensure(int(floating.group(2)), True)
            _assign(tranche, "principal_amount", f"${floating.group(1)}")
            return True
        return False

    index = 0
    while index < len(tokens):
        token = tokens[index]

        # 표지의 "$3,000,000,000 of 4.550% Notes Due 2029" 요약줄은 제목이 아니라
        # 그 자체로 금액·쿠폰을 담은 한 줄짜리 트랜치 정의다.
        if token.startswith("$"):
            absorb_combined(token)
            index += 1
            continue

        heading = _TRANCHE_HEADING.match(token)
        if heading:
            coupon = float(heading.group(1)) if heading.group(1) else None
            current = ensure(
                int(heading.group(2)), "floating" in token.lower(), heading=token, coupon=coupon
            )
            index += 1
            continue

        field = normalize_label(token) if _is_label(token) else None
        if not field:
            index += 1
            continue

        if field in OFFERING_FIELDS:
            if index + 1 < len(tokens) and not _is_label(tokens[index + 1]):
                offering.setdefault(field, tokens[index + 1][:80])
            index += 1
            continue

        # 다음 라벨(또는 제목)이 나올 때까지가 이 라벨의 값 구간이다.
        cursor = index + 1
        unprefixed_used = False
        selected: dict | None = None      # 선택자가 가리킨 트랜치(Meta 형)
        while cursor < len(tokens) and not _is_label(tokens[cursor]):
            value = tokens[cursor]
            if not value.startswith("$") and _TRANCHE_HEADING.match(value):
                break

            selector = _TRANCHE_SELECTOR.match(value)
            if selector:
                selected = ensure(int(selector.group(1)), bool(selector.group(2).strip()))
                cursor += 1
                continue

            if field == "securities_offered":
                # 금액·쿠폰·만기가 한 줄에 온다 — 값 배정이 아니라 트랜치 정의다.
                absorb_combined(value)
                cursor += 1
                continue

            prefixed = _VALUE_PREFIX.match(value)
            if prefixed:
                target = ensure(int(prefixed.group(1)), bool(prefixed.group(2).strip()))
                _assign(target, field, prefixed.group(3))
            elif selected is not None:
                _assign(selected, field, value)
                selected = None
            elif current is not None and not unprefixed_used:
                # 순차형: 라벨 바로 뒤 한 토큰만 값으로 본다(뒤따르는 주석 배제).
                _assign(current, field, value)
                unprefixed_used = True
            cursor += 1

        index = cursor

    for tranche in tranches.values():
        if offering.get("ratings"):
            tranche["ratings"] = offering["ratings"]
        # 선택자로 만들어진 트랜치는 처음엔 쿠폰을 몰라 이름이 밋밋하다.
        if tranche["security"].startswith("Notes due") and tranche["coupon_pct"] is not None:
            tranche["security"] = _security_label(
                None, tranche["maturity_year"], tranche["floating"], tranche["coupon_pct"]
            )

    # 발행 규모나 국채 대비 스프레드 중 하나도 못 읽었으면 채권 트랜치로 보지
    # 않는다 — 목차·상호참조나 전환우선주 같은 비채권 공시를 걸러낸다.
    kept = [t for t in tranches.values() if t["principal_amount"] or t["spread_bp"]]
    return sorted(kept, key=lambda t: (t["maturity_year"], t["floating"]))


def _assign(tranche: dict, field: str, value: str) -> None:
    """필드 하나를 채운다. 이미 값이 있으면 건드리지 않는다(선착순)."""

    def put(key: str, parsed) -> None:
        if parsed is not None and tranche.get(key) is None:
            tranche[key] = parsed

    if field == "principal_amount":
        put("principal_amount", parse_money(value))
    elif field == "maturity_date":
        put("maturity_date", parse_date(value))
    elif field == "coupon":
        percent = parse_percent(value)
        if "sofr" in value.lower() or "floating" in value.lower():
            # 변동금리채의 "Compounded SOFR, plus 1.11%" 는 쿠폰이 아니라 가산금리다.
            tranche["floating"] = True
            put("floating_spread_pct", percent)
            put("coupon_note", value[:120])
        else:
            put("coupon_pct", percent)
    elif field == "price_to_public":
        put("price_to_public", parse_percent(value))
    elif field == "benchmark":
        put("benchmark", value[:120])
    elif field == "benchmark_yield":
        put("benchmark_yield_pct", parse_percent(value))
    elif field == "spread_bp":
        put("spread_bp", parse_spread_bp(value))
    elif field == "yield_to_maturity":
        put("yield_to_maturity_pct", parse_percent(value))
    elif field == "ratings":
        put("ratings", value[:80])
    elif field == "cusip":
        put("cusip", value[:60])


# --- EDGAR 조회 --------------------------------------------------------------
def list_filings(cik: str, *, forms: tuple[str, ...] = BOND_FORMS, limit: int = 40) -> list[dict]:
    """최근 채권 관련 공시 목록(최신순)."""
    _throttle()
    resp = fetch(SUBMISSIONS_URL.format(cik=cik))
    try:
        recent = resp.json()["filings"]["recent"]
    except (ValueError, KeyError) as exc:
        raise SourceError(f"EDGAR {cik}: submissions 파싱 실패") from exc

    out = []
    for index, form in enumerate(recent.get("form", [])):
        if not form.startswith(forms):
            continue
        out.append(
            {
                "form": form,
                "filing_date": recent["filingDate"][index],
                "accession": recent["accessionNumber"][index].replace("-", ""),
                "document": recent["primaryDocument"][index],
            }
        )
        if len(out) >= limit:
            break
    return out


def document_url(cik: str, filing: dict) -> str:
    return ARCHIVE_URL.format(
        cik_int=int(cik), accession=filing["accession"], document=filing["document"]
    )


def fetch_document(cik: str, filing: dict) -> str:
    _throttle()
    return fetch(document_url(cik, filing)).text


def _parse_filing(ticker: str, cik: str, filing: dict) -> dict | None:
    try:
        document = fetch_document(cik, filing)
    except SourceError as exc:
        logger.warning("EDGAR %s %s 문서 실패 — %s", ticker, filing["accession"], exc)
        return None

    tranches = parse_pricing_term_sheet(document)
    if not tranches:
        return None

    return {
        "issuer": ticker,
        "form": filing["form"],
        "filing_date": filing["filing_date"],
        "accession": filing["accession"],
        "url": document_url(cik, filing),
        "total_amount": sum(t["principal_amount"] or 0 for t in tranches) or None,
        "tranches": tranches,
    }


def _near(day_a: str, day_b: str, days: int) -> bool:
    try:
        a = date.fromisoformat(day_a)
        b = date.fromisoformat(day_b)
    except ValueError:
        return False
    return abs((a - b).days) <= days


def collect_issuer(ticker: str, cik: str, *, max_filings: int = 12) -> list[dict]:
    """한 발행사의 채권 발행 이력(최신순).

    같은 발행 건이 FWP 와 424B 로 며칠 간격을 두고 두 번 올라오므로, 정제도가
    높은 FWP 를 먼저 읽고 424B 는 **FWP 로 못 잡은 발행 건**만 메운다. 공시
    하나가 실패해도 나머지는 살린다.
    """
    try:
        filings = list_filings(cik)
    except SourceError as exc:
        logger.warning("EDGAR %s 공시목록 실패 — %s", ticker, exc)
        return []

    primary = [f for f in filings if f["form"] == PRIMARY_FORM][:max_filings]
    offerings = [o for o in (_parse_filing(ticker, cik, f) for f in primary) if o]

    covered = [o["filing_date"] for o in offerings]
    budget = max_filings - len(primary)
    for filing in filings:
        if budget <= 0:
            break
        if filing["form"] == PRIMARY_FORM:
            continue
        if any(_near(filing["filing_date"], day, DUPLICATE_WINDOW_DAYS) for day in covered):
            continue
        budget -= 1
        parsed = _parse_filing(ticker, cik, filing)
        if parsed:
            offerings.append(parsed)
            covered.append(parsed["filing_date"])

    return sorted(offerings, key=lambda o: o["filing_date"], reverse=True)
