"""BIS(국제결제은행) CBPOL 소스 — 각국 **중앙은행 정책금리**.

왜 필요한가
    FRED 는 미국(DFEDTARU)과 유로존(ECBDFR)만 정책금리로 바로 쓸 수 있고,
    나머지 나라는 시장금리 대용밖에 없다. 그 상태로는 기준금리 화면에 미국과
    유럽만 남는다. BIS 의 ``WS_CBPOL`` 데이터셋은 주요국 정책금리를 한 정의로
    모아 두고 **한 번의 요청으로 전 국가·전 기간**을 준다.

    영국을 FRED 로 받지 않는 이유도 같다 — ``IUDSOIA`` 는 SONIA(시장 익일물)라
    영란은행 Bank Rate 가 아니다. BIS 가 실제 정책금리를 준다.

미국·유로존은 여기서 받지 않는다
    미국의 관행적 "기준금리" 는 FF 목표범위 상단(FRED ``DFEDTARU``)이고 BIS 는
    실효금리를 준다(3.75 vs 3.62). 유로존도 ECB 예금금리라는 특정 금리를
    쓰는 편이 명확하다. 그래서 두 곳은 FRED 가 맡고 여기서는 제외한다 —
    같은 값을 두 소스가 다투지 않게 하려는 것이다.
"""

from __future__ import annotations

import csv
import io
import logging

from bondmate.http import SourceError, fetch

logger = logging.getLogger(__name__)

BASE_URL = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0"

# BIS REF_AREA → bond-mate 시리즈 ID.
# XM(유로존)·US 는 FRED 가 맡으므로 제외. 한국은 ECOS 가 우선이고 여기는 폴백.
REF_AREAS = {
    "KR": "KR_BASE",
    "JP": "JP_BASE",
    "GB": "GB_BASE",
    "AU": "AU_BASE",
    "CN": "CN_BASE",
    "CH": "CH_BASE",
    "CA": "CA_BASE",
    "IN": "IN_BASE",
    "ID": "ID_BASE",
    "BR": "BR_BASE",
    "MX": "MX_BASE",
}

# 정책금리는 몇 달에 한 번 바뀌므로 일간이어도 데이터가 작다. 전 기간을 받아
# 히스토리 차트가 인하·인상 사이클을 그대로 보여주게 한다.
START_PERIOD = "1990-01"
TIMEOUT_SECONDS = 40


def parse_csv(text: str) -> dict[str, dict[str, float]]:
    """CBPOL CSV → ``{시리즈ID: {날짜: 값}}``. 관심 밖 REF_AREA 는 버린다."""
    out: dict[str, dict[str, float]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        series = REF_AREAS.get((row.get("REF_AREA") or "").strip())
        day = (row.get("TIME_PERIOD") or "").strip()
        raw = (row.get("OBS_VALUE") or "").strip()
        if not series or not day or raw in ("", "."):
            continue
        try:
            out.setdefault(series, {})[day] = float(raw)
        except ValueError:
            continue
    return out


def collect() -> dict[str, dict[str, float]]:
    """전 국가를 한 번에. SDMX 는 ``+`` 로 이어 붙인 다중 키를 받는다."""
    areas = "+".join(REF_AREAS)
    resp = fetch(
        f"{BASE_URL}/D.{areas}",
        params={"startPeriod": START_PERIOD, "format": "csvfile"},
        timeout=TIMEOUT_SECONDS,
        headers={"Accept": "text/csv,*/*"},
    )
    parsed = parse_csv(resp.text)
    if not parsed:
        raise SourceError("BIS CBPOL: 파싱된 정책금리 없음")
    return parsed
