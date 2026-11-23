"""중국 인민은행의 공개시장 익일 역레포 고정금리 공고."""

from __future__ import annotations

import re
import unicodedata
from html import unescape

from bondmate.http import SourceError, fetch

SOURCE = "pboc:overnight-reverse-repo"
SERIES = "CN_BASE"
START_DATE = "2026-11-02"
ORIGIN = "https://www.pbc.gov.cn"
NOTICE_PATH = "/zhengcehuobisi/125207/125213/125431/125475/"

_NOTICE_LINK = re.compile(
    rf'href="({NOTICE_PATH}\d+/index\.html)"[^>]*>\s*公开市场业务交易公告[^<]*</a>'
    r'\s*</font>\s*<span[^>]*>(\d{4}-\d{2}-\d{2})</span>'
)
_NEXT_PAGE = re.compile(rf'tagname="({NOTICE_PATH}\d+-\d+\.html)"[^>]*>\s*下一页</a>')
_DESCRIPTION = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"', re.IGNORECASE)
_FIXED_OVERNIGHT = re.compile(
    r"固定利率、数量招标(?:方式)?开展(?:了)?(?:\d+(?:\.\d+)?亿元)?隔夜(?:期)?逆回购操作"
)
_OVERNIGHT_RATE = re.compile(r"隔夜逆回购操作情况期限操作利率投标量中标量隔夜(\d+(?:\.\d+)?)%")


def parse_rate(html: str) -> float | None:
    """혼합 공고에서도 익일 역레포의 고정금리만 읽는다."""
    description = _DESCRIPTION.search(html)
    if not description:
        raise SourceError("PBOC 공고 설명을 찾을 수 없습니다")
    content = unicodedata.normalize("NFKC", unescape(description[1]))
    content = re.sub(r"\s+", "", content)
    if not _FIXED_OVERNIGHT.search(content):
        return None
    rate = _OVERNIGHT_RATE.search(content)
    if not rate:
        raise SourceError("PBOC 익일 역레포 공고에서 고정금리를 찾을 수 없습니다")
    return float(rate[1])


def _notice_html(path: str) -> str:
    response = fetch(ORIGIN + path, timeout=10, retries=2)
    return response.content.decode("utf-8-sig", errors="replace")


def collect(since: str = START_DATE) -> dict[str, float]:
    """전환일 또는 마지막 저장일부터 공식 관측치를 수집한다."""
    since = max(since, START_DATE)
    path = NOTICE_PATH + "index.html"
    visited: set[str] = set()
    points: dict[str, float] = {}
    while path and path not in visited:
        visited.add(path)
        page = _notice_html(path)
        notices = _NOTICE_LINK.findall(page)
        if not notices:
            raise SourceError("PBOC 공개시장 공고 목록을 찾을 수 없습니다")
        for notice, day in notices:
            if day < since or day in points:
                continue
            rate = parse_rate(_notice_html(notice))
            if rate is not None:
                points[day] = rate
        if min(day for _, day in notices) < since:
            break
        next_page = _NEXT_PAGE.search(page)
        path = next_page[1] if next_page else ""
    if not points:
        raise SourceError("PBOC 익일 역레포 관측치가 없습니다")
    return points
