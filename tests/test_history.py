"""히스토리 저장 포맷 — 해상도 축소와 병합 규칙."""

from datetime import date, timedelta

from bondmate import history

TODAY = date(2026, 8, 29)


def _days(start: date, count: int) -> dict[str, float]:
    return {(start + timedelta(days=i)).isoformat(): float(i) for i in range(count)}


def test_최근_3년은_일간_해상도를_유지한다():
    points = _days(TODAY - timedelta(days=30), 31)
    assert history.downsample(points, today=TODAY) == points


def test_10년_이전은_월당_한_점으로_줄인다():
    old = {f"2000-01-{day:02d}": float(day) for day in range(1, 29)}
    kept = history.downsample(old, today=TODAY)
    assert list(kept) == ["2000-01-28"]          # 그 달의 마지막 관측치


def test_3에서_10년_구간은_주당_한_점으로_줄인다():
    start = TODAY - timedelta(days=365 * 5)
    points = _days(start, 21)                     # 3주치 일간
    kept = history.downsample(points, today=TODAY)
    assert 3 <= len(kept) <= 4


def test_최신_관측치는_어떤_구간이든_보존된다():
    # 전부 10년보다 오래됐지만 마지막 점은 남아야 스냅샷과 어긋나지 않는다.
    old = {"1990-03-01": 1.0, "1990-03-15": 2.0, "1990-03-31": 3.0}
    kept = history.downsample(old, today=TODAY)
    assert "1990-03-31" in kept


def test_같은_날짜는_새_값이_이긴다():
    """FRED 는 과거값을 사후 정정한다 — append 가 아니라 upsert 여야 한다."""
    existing = history.encode({"2026-08-27": 4.0, "2026-08-28": 4.1})
    merged = history.merge(existing, {"2026-08-28": 4.25, "2026-08-29": 4.3})
    assert merged == {"2026-08-27": 4.0, "2026-08-28": 4.25, "2026-08-29": 4.3}


def test_None_값은_병합에서_제외된다():
    merged = history.merge(None, {"2026-08-28": 4.1, "2026-08-29": None})
    assert merged == {"2026-08-28": 4.1}


def test_인코딩은_날짜순_병렬배열이다():
    encoded = history.encode({"2026-08-29": 2.0, "2026-08-27": 1.0})
    assert encoded == {"d": ["2026-08-27", "2026-08-29"], "v": [1.0, 2.0]}


def test_디코딩은_레코드_배열도_받아준다():
    rows = [{"date": "2026-08-27", "value": 1.0}, {"date": "2026-08-28", "value": None}]
    assert history.decode(rows) == {"2026-08-27": 1.0}


def test_인코딩_디코딩_왕복():
    points = _days(TODAY - timedelta(days=10), 11)
    assert history.decode(history.encode(points)) == points


def test_최신_두_점으로_전일대비를_만든다():
    last, prev = history.latest_two({"2026-08-27": 1.0, "2026-08-28": 2.0, "2026-08-26": 0.5})
    assert last == ("2026-08-28", 2.0)
    assert prev == ("2026-08-27", 1.0)


def test_관측치가_없으면_None():
    assert history.latest_two({}) == (None, None)
