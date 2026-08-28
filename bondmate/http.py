"""공유 HTTP 세션 — 재시도·백오프·User-Agent 를 한 곳에서 관리한다.

수집기는 GitHub Actions 러너에서 돌기 때문에 개별 소스의 일시적 실패로 전체
잡이 죽으면 안 된다. 여기서 재시도를 흡수하고, 그래도 실패하면 호출부가
``SourceError`` 를 잡아 해당 소스만 건너뛴다.
"""

from __future__ import annotations

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

# SEC 는 연락처 이메일이 담긴 User-Agent 를 요구한다(없으면 403). 주의: SEC 의
# WAF 는 User-Agent 에 "github" 이나 URL 이 들어가면 연락처가 유효해도 403 을
# 돌려준다 — 그래서 이메일 하나만 괄호로 넣는 최소 형식을 쓴다.
# 공개 저장소에 개인 메일을 박지 않도록 기본값은 중립 주소이고, 운영 워크플로는
# ``SEC_CONTACT_EMAIL`` 로 실제 연락처를 주입한다.
DEFAULT_CONTACT_EMAIL = "noreply@bondmate.dev"


def contact_email() -> str:
    return (os.getenv("SEC_CONTACT_EMAIL") or DEFAULT_CONTACT_EMAIL).strip()


def user_agent() -> str:
    return f"bond-mate/1.0 ({contact_email()})"

DEFAULT_TIMEOUT = 20
DEFAULT_RETRIES = 3
BACKOFF_SECONDS = 1.5


class SourceError(RuntimeError):
    """한 소스의 수집 실패. 호출부는 이걸 잡고 다음 소스로 넘어간다."""


_session: requests.Session | None = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"})
        _session = s
    return _session


def fetch(
    url: str,
    *,
    params: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    headers: dict | None = None,
) -> requests.Response:
    """GET 한 번. 5xx/네트워크 오류는 재시도, 4xx 는 즉시 실패로 본다."""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = get_session().get(url, params=params, timeout=timeout, headers=headers)
        except requests.RequestException as exc:
            last_error = exc
        else:
            if resp.status_code < 400:
                return resp
            # 4xx 는 재시도해도 같은 결과 — 바로 포기한다.
            if resp.status_code < 500:
                raise SourceError(f"{url} → HTTP {resp.status_code}")
            last_error = SourceError(f"{url} → HTTP {resp.status_code}")

        if attempt < retries:
            sleep_for = BACKOFF_SECONDS * attempt
            logger.warning("fetch 실패(%s/%s) %s — %ss 후 재시도", attempt, retries, url, sleep_for)
            time.sleep(sleep_for)

    raise SourceError(f"{url} 요청 실패: {last_error}")
