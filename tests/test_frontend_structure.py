"""프론트엔드 구조 계약.

빌드 시스템이 없어 ``index.html`` 의 ``<script>`` 순서가 곧 의존성 선언이다.
util → chart → store → views-common → 화면들 → app 순서가 깨지면 전역 함수가
정의되기 전에 참조돼 런타임에야 터진다. 여기서 순서를 고정해 둔다.

임베드 파라미터 이름도 value-invest 가 URL 에 박아 쓰는 계약이라 함께 잠근다.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "templates" / "index.html"

# 의존 순서대로. 앞의 파일이 정의한 전역을 뒤의 파일이 쓴다.
SCRIPT_ORDER = [
    "static/js/util.js",
    "static/js/chart.js",
    "static/js/store.js",
    "static/js/views-common.js",
    "static/js/views-rates.js",
    "static/js/views-fx.js",
    "static/js/views-credit.js",
    "static/js/views-issuance.js",
    "static/js/app.js",
]


def _index_html() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_스크립트가_의존_순서대로_선언된다():
    found = re.findall(r'<script src="([^"]+)"', _index_html())
    assert found == SCRIPT_ORDER


def test_모든_스크립트_파일이_실제로_있다():
    for src in SCRIPT_ORDER:
        assert (ROOT / src).exists(), f"{src} 없음"


def test_스크립트는_defer로_불린다():
    """DOMContentLoaded 에 부팅하므로 파서를 막지 않아야 한다."""
    for tag in re.findall(r"<script src=[^>]+>", _index_html()):
        assert "defer" in tag, tag


def test_스타일시트가_연결돼_있다():
    assert 'href="static/css/bondmate.css"' in _index_html()
    assert (ROOT / "static/css/bondmate.css").exists()


def test_임베드_파라미터_이름이_유지된다():
    """value-invest 가 iframe URL 에 박아 쓰는 이름 — 바꾸면 임베드가 깨진다."""
    app_js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    for param in ("'embed'", "'tab'", "'theme'", "'bg'"):
        assert f"queryParam({param})" in app_js, f"{param} 처리 없음"


def test_임베드_탭_키가_유지된다():
    """부모가 ?embed=<키> 로 지정하는 화면 이름."""
    app_js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    for key in ("overview", "government", "policy", "fx", "credit", "issuance"):
        assert f"key: '{key}'" in app_js, f"탭 {key} 없음"


def test_임베드일_때_헤더와_푸터가_숨는다():
    css = (ROOT / "static/css/bondmate.css").read_text(encoding="utf-8")
    assert "body.is-embed .app-head" in css
    assert "body.is-embed .app-foot" in css


def test_임베드_배경은_투명이_기본이_아니다():
    """투명이 기본이면 다크 테마 임베드가 밝은 부모 위에서 안 보인다."""
    css = (ROOT / "static/css/bondmate.css").read_text(encoding="utf-8")
    assert "body.is-embed { background: var(--bg); }" in css
    assert "body.is-embed.bg-transparent { background: transparent; }" in css
