"""시계열 히스토리 저장 포맷과 병합 규칙.

published JSON 은 GitHub Pages 로 서빙되므로 **파일 크기가 곧 로딩 속도**다.
전체 일간 히스토리를 그대로 실으면 미국 국채만 1962년부터 1만6천 포인트라
수십 MB 가 된다. 그래서 저장할 때 해상도를 낮춘다:

    최근 3년   일간 그대로
    3~10년     주간(각 주의 마지막 관측치)
    10년 이전  월간(각 달의 마지막 관측치)

시리즈당 1,500 포인트 안쪽으로 떨어져 차트 렌더링에도 충분하다. 최근 구간은
원본 해상도를 유지하므로 단기 분석은 손실이 없다.

직렬화는 병렬 배열(``{"d": [...], "v": [...]}``)이다. 레코드 배열보다 키 반복이
없어 gzip 전 기준으로도 40% 작고, 프론트에서 그대로 차트에 넘길 수 있다.
"""

from __future__ import annotations

from datetime import date, timedelta

DAILY_WINDOW_DAYS = 365 * 3
WEEKLY_WINDOW_DAYS = 365 * 10


def _parse(day: str) -> date:
    return date.fromisoformat(day)


def downsample(points: dict[str, float], *, today: date | None = None) -> dict[str, float]:
    """구간별 해상도를 적용해 관측치를 솎아낸다.

    각 버킷에서 **가장 늦은 날짜**를 남긴다(주/월의 마지막 영업일). 최신 관측치는
    어떤 경우에도 보존한다 — 스냅샷과 히스토리 끝값이 어긋나면 안 되기 때문.
    """
    if not points:
        return {}

    today = today or date.today()
    daily_from = today - timedelta(days=DAILY_WINDOW_DAYS)
    weekly_from = today - timedelta(days=WEEKLY_WINDOW_DAYS)

    kept: dict[str, str] = {}  # 버킷키 → 채택한 날짜
    for day in points:
        try:
            d = _parse(day)
        except ValueError:
            continue

        if d >= daily_from:
            bucket = day                                    # 일간: 솎지 않음
        elif d >= weekly_from:
            iso = d.isocalendar()
            bucket = f"W{iso[0]}-{iso[1]:02d}"              # 주간
        else:
            bucket = f"M{d.year}-{d.month:02d}"             # 월간

        if bucket not in kept or day > kept[bucket]:
            kept[bucket] = day

    latest = max(points)
    chosen = set(kept.values()) | {latest}
    return {day: points[day] for day in sorted(chosen)}


def merge(existing: dict | None, incoming: dict[str, float]) -> dict[str, float]:
    """기존 히스토리에 새 관측치를 덮어쓴다(같은 날짜는 새 값 우선).

    소스가 과거값을 사후 정정(FRED 의 revision)하는 일이 있어 append 가 아니라
    upsert 여야 한다.
    """
    merged: dict[str, float] = {}
    if existing:
        merged.update(decode(existing))
    merged.update({d: v for d, v in incoming.items() if v is not None})
    return merged


def encode(points: dict[str, float]) -> dict:
    """{날짜: 값} → 병렬 배열 형태."""
    days = sorted(points)
    return {"d": days, "v": [points[day] for day in days]}


def decode(payload: dict | None) -> dict[str, float]:
    """병렬 배열 → {날짜: 값}. 레코드 배열 형태도 관대하게 받아준다."""
    if not payload:
        return {}
    if isinstance(payload, dict) and "d" in payload and "v" in payload:
        days, values = payload.get("d") or [], payload.get("v") or []
        return {d: v for d, v in zip(days, values) if v is not None}
    if isinstance(payload, list):
        out = {}
        for row in payload:
            if isinstance(row, dict) and row.get("date") is not None and row.get("value") is not None:
                out[str(row["date"])] = row["value"]
        return out
    return {}


def store(existing: dict | None, incoming: dict[str, float], *, today: date | None = None) -> dict:
    """merge → downsample → encode 파이프라인."""
    return encode(downsample(merge(existing, incoming), today=today))


def latest_two(points: dict[str, float]) -> tuple[tuple[str, float] | None, tuple[str, float] | None]:
    """최신 관측치와 그 직전 관측치. 전일대비 변동 계산용."""
    if not points:
        return None, None
    days = sorted(points)
    last = (days[-1], points[days[-1]])
    prev = (days[-2], points[days[-2]]) if len(days) >= 2 else None
    return last, prev
