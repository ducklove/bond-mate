"""EDGAR pricing term sheet 파서.

실제 FWP 는 발행사마다 배치가 달라 네 가지 레이아웃을 모두 지원해야 한다.
각 레이아웃은 실제 공시에서 관찰된 형태를 최소 재현한 것이다.
"""

from bondmate.sources import edgar

# --- 값 파서 -----------------------------------------------------------------


def test_금액은_콤마와_단위를_읽는다():
    assert edgar.parse_money("$3,000,000,000") == 3_000_000_000
    assert edgar.parse_money("$1.5 billion") == 1_500_000_000
    assert edgar.parse_money("$750 million") == 750_000_000
    assert edgar.parse_money("금액 없음") is None


def test_스프레드는_여러_표기를_읽는다():
    assert edgar.parse_spread_bp("+95 basis points") == 95
    assert edgar.parse_spread_bp("T + 33 bps") == 33
    assert edgar.parse_spread_bp("+ 130 bp") == 130
    assert edgar.parse_spread_bp("해당 없음") is None


def test_날짜는_ISO로_정규화된다():
    assert edgar.parse_date("February 4, 2029") == "2029-02-04"
    assert edgar.parse_date("August 10 2028") == "2028-08-10"
    assert edgar.parse_date("미정") is None


def test_라벨은_각주와_괄호주석을_무시한다():
    assert edgar.normalize_label("Spread to Benchmark Treasury:") == "spread_bp"
    assert edgar.normalize_label("Expected Ratings (Moody's / S&P / Fitch):*") == "ratings"
    assert edgar.normalize_label("Coupon (Interest Rate):") == "coupon"
    assert edgar.normalize_label("Joint Book-Running Managers:") is None


# --- 레이아웃별 파싱 ---------------------------------------------------------


def _html(cells: list[str]) -> str:
    return "".join(f"<td>{cell}</td>" for cell in cells)


def test_순차형_트랜치마다_제목과_조건이_붙는다():
    """Oracle 형: 제목 → 라벨/값 쌍이 그 트랜치에 속한다."""
    document = _html([
        "4.550% Notes due 2029",
        "Principal Amount:", "$3,000,000,000",
        "Coupon:", "4.550%",
        "Spread to Benchmark Treasury:", "+95 basis points",
        "Yield to Maturity:", "4.596%",
        "5.700% Notes due 2036",
        "Principal Amount:", "$5,000,000,000",
        "Yield to Maturity:", "5.729%",
    ])
    tranches = edgar.parse_pricing_term_sheet(document)

    assert [t["maturity_year"] for t in tranches] == [2029, 2036]
    assert tranches[0]["principal_amount"] == 3_000_000_000
    assert tranches[0]["spread_bp"] == 95
    assert tranches[0]["yield_to_maturity_pct"] == 4.596
    assert tranches[1]["principal_amount"] == 5_000_000_000


def test_행렬형_값이_자기_트랜치를_접두사로_단다():
    """Alphabet 형: 라벨 하나에 트랜치별 값이 줄줄이 붙는다."""
    document = _html([
        "4.500% Notes due 2028",
        "4.625% Notes due 2029",
        "Aggregate Principal Amount:",
        "2028 Notes: $1,250,000,000",
        "2029 Notes: $2,000,000,000",
        "Yield to Maturity:",
        "2028 Notes: 4.575%",
        "2029 Notes: 4.734%",
    ])
    by_year = {t["maturity_year"]: t for t in edgar.parse_pricing_term_sheet(document)}

    assert by_year[2028]["principal_amount"] == 1_250_000_000
    assert by_year[2028]["yield_to_maturity_pct"] == 4.575
    assert by_year[2029]["yield_to_maturity_pct"] == 4.734


def test_선택자분리형_트랜치키와_값이_다른_셀에_있다():
    """Meta 형: "2031 Notes:" 는 라벨이 아니라 다음 값의 귀속처를 가리킨다."""
    document = _html([
        "Principal Amount:",
        "2031 Notes:", "$3,000,000,000",
        "2033 Notes:", "$2,000,000,000",
        "Spread to Benchmark Treasury:",
        "2031 Notes:", "T + 53 bps",
        "2033 Notes:", "T + 68 bps",
    ])
    by_year = {t["maturity_year"]: t for t in edgar.parse_pricing_term_sheet(document)}

    assert by_year[2031]["principal_amount"] == 3_000_000_000
    assert by_year[2031]["spread_bp"] == 53
    assert by_year[2033]["spread_bp"] == 68


def test_한줄결합형_금액_쿠폰_만기가_한_셀에_온다():
    """Broadcom 형: 'Securities Offered' 아래 한 줄이 트랜치 하나를 정의한다."""
    document = _html([
        "Securities Offered:",
        '$750,000,000 aggregate principal amount of 4.300% Senior Notes due 2031 (the "2031 Notes")',
        '$1,250,000,000 aggregate principal amount of 4.600% Senior Notes due 2033 (the "2033 Notes")',
    ])
    by_year = {t["maturity_year"]: t for t in edgar.parse_pricing_term_sheet(document)}

    assert by_year[2031]["principal_amount"] == 750_000_000
    assert by_year[2031]["coupon_pct"] == 4.3
    assert by_year[2033]["coupon_pct"] == 4.6


# --- 분류·필터 ---------------------------------------------------------------


def test_같은_해_고정과_변동은_다른_트랜치다():
    document = _html([
        "Floating Rate Notes due 2029",
        "Principal Amount:", "$500,000,000",
        "Coupon:", "Compounded SOFR, plus 1.11% per year",
        "4.550% Notes due 2029",
        "Principal Amount:", "$3,000,000,000",
        "Coupon:", "4.550%",
    ])
    tranches = edgar.parse_pricing_term_sheet(document)

    assert len(tranches) == 2
    floating = next(t for t in tranches if t["floating"])
    fixed = next(t for t in tranches if not t["floating"])
    # 변동금리채의 "plus 1.11%" 는 쿠폰이 아니라 가산금리다.
    assert floating["coupon_pct"] is None
    assert floating["floating_spread_pct"] == 1.11
    assert fixed["coupon_pct"] == 4.55


def test_등급은_발행_건_전체에_적용된다():
    document = _html([
        "Expected Ratings (Moody's / S&P):*", "Baa2 / BBB",
        "4.550% Notes due 2029",
        "Principal Amount:", "$3,000,000,000",
        "5.700% Notes due 2036",
        "Principal Amount:", "$5,000,000,000",
    ])
    tranches = edgar.parse_pricing_term_sheet(document)

    assert len(tranches) == 2
    assert all(t["ratings"] == "Baa2 / BBB" for t in tranches)


def test_발행규모도_스프레드도_없으면_트랜치가_아니다():
    """목차·상호참조나 전환우선주 공시가 채권으로 잡히지 않도록."""
    document = _html([
        "4.550% Notes due 2029",
        "Interest Payment Dates:", "February 4 and August 4",
    ])
    assert edgar.parse_pricing_term_sheet(document) == []


def test_먼저_읽은_값이_유지된다():
    """문서 뒤쪽 요약표가 앞서 읽은 정확한 값을 덮어쓰지 않아야 한다."""
    document = _html([
        "4.550% Notes due 2029",
        "Yield to Maturity:", "4.596%",
        "Yield to Maturity:", "0.000%",
        "Principal Amount:", "$3,000,000,000",
    ])
    assert edgar.parse_pricing_term_sheet(document)[0]["yield_to_maturity_pct"] == 4.596


def test_합성_종목명은_쿠폰과_만기로_만든다():
    """행렬형은 제목 토큰이 없을 수 있다 — 그래도 이름이 읽을 만해야 한다."""
    document = _html([
        "Principal Amount:", "2031 Notes:", "$3,000,000,000",
        "Coupon:", "2031 Notes:", "4.550%",
    ])
    assert edgar.parse_pricing_term_sheet(document)[0]["security"] == "4.550% Notes due 2031"
