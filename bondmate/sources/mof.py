"""일본 재무성(MOF) JGB 금리 CSV — 일본 국채 **전 만기** 커브.

CNBC 에도 일부 만기가 있지만, MOF 는 1년~40년 전 만기를 하나의 CSV 로 주고
과거 히스토리도 함께 담고 있어 일본 커브의 기준 소스로 쓴다. 인코딩은 cp932,
날짜는 일본 연호(``R8.8.28`` = 레이와 8년)라 둘 다 변환이 필요하다.
"""

from __future__ import annotations

import csv
import io
import logging
import re

from bondmate.http import SourceError, fetch

logger = logging.getLogger(__name__)

CURRENT_URL = "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"

# CSV 헤더의 일본어 만기 라벨 → bond-mate 시리즈 ID
COLUMNS = {
    "1年": "JP1Y", "2年": "JP2Y", "3年": "JP3Y", "5年": "JP5Y", "7年": "JP7Y",
    "10年": "JP10Y", "15年": "JP15Y", "20年": "JP20Y", "30年": "JP30Y", "40年": "JP40Y",
}

# 레이와(令和)는 2019년이 원년 — 서기 = 2018 + 연호년.
REIWA_EPOCH = 2018
_JP_DATE = re.compile(r"^R(\d+)\.(\d+)\.(\d+)$")


def _to_iso(japanese_date: str) -> str | None:
    m = _JP_DATE.match(japanese_date.strip())
    if not m:
        return None
    era_year, month, day = (int(g) for g in m.groups())
    return f"{REIWA_EPOCH + era_year:04d}-{month:02d}-{day:02d}"


def parse_csv(blob: bytes) -> dict[str, dict[str, float]]:
    rows = list(csv.reader(io.StringIO(blob.decode("cp932", errors="ignore"))))
    if len(rows) < 3:
        raise SourceError("MOF JGB: CSV 행이 부족함")

    header = rows[1]
    index_by_series = {
        series: header.index(label) for label, series in COLUMNS.items() if label in header
    }
    if not index_by_series:
        raise SourceError(f"MOF JGB: 만기 컬럼을 찾지 못함 — {header[:6]}")

    out: dict[str, dict[str, float]] = {series: {} for series in index_by_series}
    for row in rows[2:]:
        if not row:
            continue
        day = _to_iso(row[0])
        if not day:
            continue
        for series, idx in index_by_series.items():
            if idx >= len(row):
                continue
            try:
                out[series][day] = float(row[idx])
            except ValueError:
                continue        # 미발행 만기는 빈칸이거나 '-'

    return {series: points for series, points in out.items() if points}


def collect() -> dict[str, dict[str, float]]:
    return parse_csv(fetch(CURRENT_URL).content)
