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


# --- Value Compass 에코시스템 (value-invest 에서 벤더링) ---------------------------
WORKFLOWS = ROOT / ".github" / "workflows"
BOOT_BLOCK = re.compile(r"<!-- vc:theme-boot -->(.*?)<!-- /vc:theme-boot -->", re.S)


def _head() -> str:
    return _index_html().split("</head>", 1)[0]


def test_theme_boot_블록이_스타일시트보다_먼저_인라인으로_있다():
    head = _head()
    blocks = BOOT_BLOCK.findall(head)
    assert len(blocks) == 1, "theme-boot 마커는 head 에 정확히 하나"
    body = blocks[0]
    assert "<script>" in body and "localStorage.getItem('theme')" in body
    assert "'bondmate.theme'" in body, "옛 키를 공용 'theme' 키로 옮긴다"
    assert head.index("<!-- vc:theme-boot -->") < head.index('rel="stylesheet"')


def test_공용_토큰은_자체_CSS보다_먼저_읽는다():
    head = _head()
    tokens = head.index('href="./static/vc-tokens.css')
    assert tokens < head.index('href="static/css/bondmate.css"')


def test_vc_shell_스크립트는_defer로_불린다():
    tags = re.findall(r"<script[^>]*vc-shell\.js[^>]*>", _head())
    assert len(tags) == 1 and "defer" in tags[0] and 'src="./static/vc-shell.js' in tags[0]


def test_벤더링된_파일이_있고_직접_고치지_않는다는_표시가_있다():
    shell = (ROOT / "static/vc-shell.js").read_text(encoding="utf-8")
    tokens = (ROOT / "static/vc-tokens.css").read_text(encoding="utf-8")
    helper = (ROOT / "bondmate/vc_publish.py").read_text(encoding="utf-8")
    assert "do not edit copies" in shell and '"id":"bond-mate"' in shell
    assert "--vc-up" in tokens and "--vc-font-sans" in tokens
    assert helper.startswith("# vendored from value-invest")


def test_body_맨_위에_에코시스템_바와_허브_링크_폴백이_있다():
    body = _index_html().split("<body>", 1)[1].lstrip()
    assert body.startswith("<!--") or body.startswith("<vc-shell")
    first_tag = re.search(r"<(?!!--)[a-z-]+[^>]*>", body).group(0)
    assert first_tag == '<vc-shell tool="bond-mate">'
    shell = re.search(r'<vc-shell tool="bond-mate">(.*?)</vc-shell>', body, re.S).group(1)
    assert 'href="https://ducklove.duckdns.org:3691"' in shell and "Value Compass" in shell


def test_테마는_공용_키와_VCShell을_쓴다():
    app_js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "VCShell.setTheme(" in app_js
    assert "'vc:themechange'" in app_js
    assert "THEME_KEY = 'theme'" in app_js
    assert "setItem('bondmate.theme'" not in app_js and "getItem('bondmate.theme'" not in app_js


def test_iframe_메시지는_vc_형식과_구_형식을_함께_보낸다():
    app_js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    for needle in ("type: 'vc:ready'", "type: 'vc:height'", "source: 'bond-mate', type: 'height'",
                   "type !== 'vc:theme'"):
        assert needle in app_js, needle


def test_탭_라벨은_허브_레지스트리_뷰_라벨과_같다():
    """value-invest 채권·금리 화면(BM_VIEW_LABELS)과 같은 이름 — '사채'가 아니라 '신용'."""
    app_js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    labels = dict(re.findall(r"key: '(\w+)', label: '([^']+)'", app_js))
    assert labels == {
        "overview": "개요", "government": "국채", "policy": "기준금리",
        "fx": "환율", "credit": "신용", "issuance": "발행",
    }


def test_방향색과_글꼴은_공용_토큰을_alias_한다():
    css = (ROOT / "static/css/bondmate.css").read_text(encoding="utf-8")
    assert "--up: var(--vc-up" in css and "--down: var(--vc-down" in css
    assert "font-family: var(--vc-font-sans" in css
    # 다크 방향색은 vc-tokens.css 가 정한다 — 자체 다크 블록에서 덮어쓰면 alias 가 깨진다.
    assert css.count("--up:") == 1 and css.count("--down:") == 1


def test_배포_산출물에_벤더링_파일과_summary가_실린다():
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    assert "cp -r static _site/static" in deploy          # static/vc-shell.js·vc-tokens.css 포함
    assert "_site/" in deploy and "summary.json" in deploy and "version.json" in deploy
    assert "python3 -m bondmate.summary --data data --out _site" in deploy
    update = (WORKFLOWS / "update-data.yml").read_text(encoding="utf-8")
    assert "current rates fx credit issuers summary version" in update
    assert "steps.generate.outputs.publish" in update
