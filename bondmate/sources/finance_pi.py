"""finance-pi 데이터레이크 소스 — **1순위 원본**.

finance-pi(``../finance-pi``, 라즈베리파이 :8400)는 이미 FRED·ECOS 를 정규화해
``macro.rates`` / ``macro.fx`` 테이블로 적재하고 있다. 같은 값을 bond-mate 가
따로 긁으면 두 서비스의 숫자가 갈리므로, 접근 가능하면 여기서 먼저 읽는다.

다만 이 백엔드는 가정용 회선 위의 단일 인스턴스라 응답하지 않는 시간이 있다
(요청 슬롯 고갈 시 503 "server overloaded"). 그래서 이 모듈은 **가용하면 쓰고
아니면 조용히 비켜서는** 소스로 설계했다 — 실패 시 build 가 FRED 로 폴백한다.

현재 상태(2026-08-29 확인)
    공개 엔드포인트는 관리자 토큰을 요구하고(401), LAN(200)에서도 ``macro.rates``
    가 2026-07-17 에서 멈춰 있다 — ``ingest macro`` 배치가 돌지 않고 있다.
    그래서 지금은 공개 소스가 실질 기본값이고, 아래 두 조건이 갖춰지면 이 소스가
    자동으로 우선한다: ``FINANCE_PI_API_TOKEN`` 제공 + macro 적재 재개.

환경변수
    ``FINANCE_PI_BASE_URL``   기본 ``http://cantabile.tplinkdns.com:8400``
    ``FINANCE_PI_ENABLED``    ``0`` 이면 시도조차 하지 않음
    ``FINANCE_PI_TIMEOUT``    초 단위, 기본 20
    ``FINANCE_PI_API_TOKEN``  공개 접근용 관리자 토큰 (``X-Admin-Token`` 헤더)
    ``FINANCE_PI_MAX_STALE_DAYS``  최신 관측이 이보다 오래되면 소스를 쓰지 않음
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from bondmate.http import SourceError, fetch

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://cantabile.tplinkdns.com:8400"

# finance-pi series_id → bond-mate 시리즈 ID.
# ECOS 계열(``*_ECOS``)은 한국은행 원본이라 한국물의 우선 소스가 된다.
RATE_SERIES = {
    "US_TREASURY_2Y": "US2Y",
    "US_TREASURY_10Y": "US10Y",
    "US_TREASURY_30Y": "US30Y",
    "US_FED_FUNDS": "US_ON",
    "DGS2": "US2Y",
    "DGS5": "US5Y",
    "DGS30": "US30Y",
    "SOFR": "US_ON",
    "KR_BASE_RATE_ECOS": "KR_BASE",
    "KR_KOFR_ECOS": "KR_ON",
    "KR_CD_91D_ECOS": "KR3M",
    "KR_GOVT_2Y_ECOS": "KR2Y",
    "KR_GOVT_3Y_ECOS": "KR3Y",
    "KR_GOVT_5Y_ECOS": "KR5Y",
    "KR_GOVT_10Y_ECOS": "KR10Y",
    "KR_GOVT_3Y": "KR3Y",
    "KR_GOVT_5Y": "KR5Y",
    "KR_GOVT_10Y_DAILY": "KR10Y",
    "JP_GOVT_10Y": "JP10Y",
    "DE_GOVT_10Y": "DE10Y",
    "FR_GOVT_10Y": "FR10Y",
    "GB_GOVT_10Y": "GB10Y",
}

# 한국 회사채(무보증 AA- 3년)는 ECOS 가 유일한 공개 일간 소스다.
KR_CREDIT_SERIES = {"KR_CORP_AA_3Y_ECOS": "KR_CORP_AA3Y"}

FX_SERIES = {
    "USD_KRW": "USD_KRW",
    "USD_KRW_ECOS": "USD_KRW",
    "EUR_KRW": "EUR_KRW",
    "EUR_KRW_ECOS": "EUR_KRW",
    "JPY_KRW": "JPY_KRW",
    "JPY100_KRW_ECOS": "JPY_KRW",
    "CNY_KRW": "CNY_KRW",
    "CNY_KRW_ECOS": "CNY_KRW",
    "AUD_KRW": "AUD_KRW",
    "USD_JPY": "USD_JPY",
}


def _env(name: str, default: str) -> str:
    """설정되지 않은 것과 **빈 값으로 설정된 것**을 같게 본다.

    GitHub Actions 는 정의되지 않은 ``vars.X`` 를 빈 문자열로 치환한다. 그걸
    그대로 쓰면 base_url 이 "" 가 돼 ``/api/macro/rates`` 같은 스킴 없는 URL 로
    요청이 나간다 — 기본값이 있으나 마나가 된다.
    """
    return (os.getenv(name) or "").strip() or default


def base_url() -> str:
    return _env("FINANCE_PI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def enabled() -> bool:
    return _env("FINANCE_PI_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def _timeout() -> int:
    try:
        return max(1, int(_env("FINANCE_PI_TIMEOUT", "20")))
    except ValueError:
        return 20


def _max_stale_days() -> int:
    try:
        return max(1, int(_env("FINANCE_PI_MAX_STALE_DAYS", "10")))
    except ValueError:
        return 10


def _headers() -> dict[str, str] | None:
    # value-invest 의 close_price_client 와 같은 헤더 이름을 쓴다.
    token = (os.getenv("FINANCE_PI_API_TOKEN") or os.getenv("CLOSE_PRICE_API_TOKEN") or "").strip()
    return {"X-Admin-Token": token} if token else None


def _query(table: str, since: str | None = None) -> list[dict]:
    params = {"since": since} if since else None
    resp = fetch(
        f"{base_url()}/api/macro/{table}",
        params=params,
        timeout=_timeout(),
        retries=2,
        headers=_headers(),
    )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise SourceError(f"finance-pi /{table}: JSON 아님") from exc
    if not isinstance(payload, dict):
        raise SourceError(f"finance-pi /{table}: 예상치 못한 응답")
    # 웨지 상태에서는 {"error": "server overloaded"} 가 온다.
    if payload.get("error"):
        raise SourceError(f"finance-pi /{table}: {payload['error']}")
    rows = payload.get(table)
    if not isinstance(rows, list):
        raise SourceError(f"finance-pi /{table}: '{table}' 배열 없음")
    return rows


def _group(rows: list[dict], mapping: dict[str, str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        series = mapping.get(str(row.get("series_id") or ""))
        day, value = row.get("date"), row.get("value")
        if not series or not day or value is None:
            continue
        try:
            out.setdefault(series, {})[str(day)[:10]] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def collect_rates(since: str | None = None) -> dict[str, dict[str, float]]:
    """국채·정책금리. 한국 회사채 AA- 3년은 ``KR_CORP_AA3Y`` 로 함께 담긴다."""
    return _group(_query("rates", since), {**RATE_SERIES, **KR_CREDIT_SERIES})


def collect_fx(since: str | None = None) -> dict[str, dict[str, float]]:
    return _group(_query("fx", since), FX_SERIES)


def probe() -> bool:
    """수집 전에 한 번 찔러본다. 실패하면 build 가 곧장 폴백으로 간다.

    닿기만 해서는 부족하다 — macro 적재가 멈춰 오래된 값만 남아 있으면 그걸
    1순위로 얹는 순간 최신 소스의 값을 밀어낸다. 그래서 **최신 관측이 충분히
    가까울 때만** 사용 가능으로 본다.
    """
    if not enabled():
        logger.info("finance-pi 비활성화(FINANCE_PI_ENABLED=0) — 공개 소스 사용")
        return False

    recent = (date.today() - timedelta(days=_max_stale_days())).isoformat()
    try:
        rows = _query("rates", since=recent)
    except SourceError as exc:
        logger.warning("finance-pi 사용 불가 — 공개 소스로 폴백 (%s)", exc)
        return False

    if not rows:
        logger.warning(
            "finance-pi 응답은 정상이나 최근 %d일 관측이 없음(macro 적재 중단?) — 공개 소스 사용",
            _max_stale_days(),
        )
        return False
    return True
