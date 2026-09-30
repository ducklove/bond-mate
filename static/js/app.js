/* 앱 셸 — 탭 라우팅, 테마, 임베드 모드.
 *
 * 임베드 계약 (value-invest 등 부모 앱이 iframe 으로 부를 때)
 *   ?embed=<탭>      헤더·탭·푸터를 걷어내고 그 화면 하나만 그린다
 *   ?tab=<탭>        독립 실행에서 초기 탭 지정 (딥링크용)
 *   ?theme=light|dark 부모 테마에 맞춘다 (생략 시 시스템 설정, 저장하지 않음)
 *   ?data=<경로>     스냅샷/히스토리 위치 재지정
 *
 * 탭 키는 부모가 URL 에 박아 쓰므로 **이름을 바꾸지 않는다**. 탭 라벨은
 * value-invest 의 채권·금리 화면(레지스트리 views)과 같은 이름을 쓴다.
 *
 * 테마는 Value Compass 공용 규약을 따른다 — head 의 theme-boot 가 칠하기 전에
 * ?theme → localStorage 'theme'(없으면 auto) → 시스템 설정 순으로 정하고,
 * 토글은 VCShell.setTheme 에 맡긴다. 테마가 바뀌면(토글·다른 탭·시스템 설정·
 * 부모 허브의 vc:theme 메시지) 'vc:themechange' 이벤트가 오고 차트를 다시 그린다.
 *
 * iframe 메시지 (부모 = value-invest 허브)
 *   자식 → 부모  {source:'vc', type:'vc:ready',  tool:'bond-mate'}
 *               {source:'vc', type:'vc:height', tool:'bond-mate', height}
 *               {source:'bond-mate', type:'height', height}   ← 구 형식, 병행 송신
 *   부모 → 자식  {source:'vc', type:'vc:theme', theme:'light'|'dark'} — 리로드 없이 적용
 */

'use strict';

(function () {
  const TABS = [
    { key: 'overview', label: '개요', render: (root, snap) => BMRates.renderOverview(root, snap) },
    { key: 'government', label: '국채', render: (root, snap) => BMRates.renderGovernment(root, snap) },
    { key: 'policy', label: '기준금리', render: (root, snap) => BMRates.renderPolicy(root, snap) },
    { key: 'fx', label: '환율', render: (root, snap) => BMFx.render(root, snap) },
    { key: 'credit', label: '신용', render: (root, snap) => BMCredit.render(root, snap) },
    { key: 'issuance', label: '발행', render: (root, snap) => BMIssuance.render(root, snap) },
  ];

  const app = document.getElementById('app');
  const tabsBox = document.getElementById('tabs');
  const embedTab = queryParam('embed');
  const isEmbed = !!embedTab;
  const TOOL_ID = 'bond-mate';
  const THEME_KEY = 'theme';               // ducklove.github.io 공용 키 (없음 = auto)
  const LEGACY_THEME_KEY = 'bondmate.theme';
  const HUB_ORIGIN_FALLBACK = 'https://ducklove.duckdns.org:3691';
  let activeKey = null;
  let refreshing = false;

  /* ── 테마 ───────────────────────────────────────────────────────────── */
  function validTheme(theme) {
    return theme === 'light' || theme === 'dark' ? theme : null;
  }

  function storedTheme() {
    try { return validTheme(localStorage.getItem(THEME_KEY)); } catch (e) { return null; }
  }

  function systemTheme() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  /** 문서에 테마를 칠하고 'vc:themechange' 를 알린다(VCShell 이 없을 때의 폴백 경로). */
  function paintTheme(theme) {
    const effective = validTheme(theme) || validTheme(queryParam('theme')) || storedTheme() || systemTheme();
    document.documentElement.setAttribute('data-theme', effective);
    document.dispatchEvent(new CustomEvent('vc:themechange', { detail: { theme: effective } }));
  }

  function initTheme() {
    // 칠하기는 head 의 theme-boot 가 이미 했다(옛 'bondmate.theme' 도 'theme' 으로 옮김).
    // 옮겨진 옛 키만 치운다 — 남아 있으면 다음에 'theme' 을 지워도(auto) 되살아난다.
    try { localStorage.removeItem(LEGACY_THEME_KEY); } catch (e) { /* 시크릿 모드 */ }
    if (!validTheme(document.documentElement.getAttribute('data-theme'))) paintTheme(null);
  }

  /** 🌗 3상태 토글: auto → dark → light → auto. auto 는 저장 키를 지운다. */
  function toggleTheme() {
    const current = storedTheme() || 'auto';
    const next = current === 'dark' ? 'light' : current === 'light' ? 'auto' : 'dark';
    if (window.VCShell && typeof window.VCShell.setTheme === 'function') {
      window.VCShell.setTheme(next);        // 저장·적용·vc:themechange 까지 한 번에
    } else {
      try {
        if (next === 'auto') localStorage.removeItem(THEME_KEY);
        else localStorage.setItem(THEME_KEY, next);
      } catch (e) { /* 저장 불가면 이번 세션만 */ }
      paintTheme(next === 'auto' ? systemTheme() : next);
    }
    updateThemeButton();
  }

  function updateThemeButton() {
    const button = document.getElementById('themeToggle');
    if (!button) return;
    const mode = storedTheme() || 'auto';
    button.title = '테마 전환 (현재: ' + ({ dark: '다크', light: '라이트', auto: '시스템' })[mode] + ')';
  }

  /** 허브 origin — 레지스트리(VCShell) 값, 없으면 운영 주소. */
  function hubOrigin() {
    try {
      const hub = window.VCShell && window.VCShell.registry && window.VCShell.registry.hub;
      return new URL(hub || HUB_ORIGIN_FALLBACK).origin;
    } catch (e) {
      return HUB_ORIGIN_FALLBACK;
    }
  }

  // 부모 허브의 테마 푸시. vc-shell.js 가 떠 있으면 셸이 받아 처리하므로 폴백만 둔다.
  window.addEventListener('message', (event) => {
    if (window.VCShell) return;
    const data = event.data;
    if (!data || data.source !== 'vc' || data.type !== 'vc:theme' || !validTheme(data.theme)) return;
    if (event.origin !== hubOrigin()) return;
    paintTheme(data.theme);
  });

  // 차트는 CSS 변수 색을 그릴 때 읽어가므로 테마가 바뀌면 다시 그려야 색이 따라온다.
  document.addEventListener('vc:themechange', () => {
    updateThemeButton();
    if (activeKey && BMStore.snapshot) rerender();
  });

  /* ── 라우팅 ─────────────────────────────────────────────────────────── */
  function show(key, opts) {
    const tab = TABS.find((t) => t.key === key) || TABS[0];
    if (activeKey === tab.key && !(opts && opts.force)) return;
    activeKey = tab.key;

    tabsBox.querySelectorAll('.tab').forEach((button) =>
      button.setAttribute('aria-selected', button.dataset.tab === tab.key ? 'true' : 'false'));

    BMViews.beginRender();
    app.innerHTML = '';
    try {
      tab.render(app, BMStore.snapshot);
    } catch (error) {
      app.innerHTML = '<div class="error-note">화면을 그리지 못했습니다 — ' + escapeHtml(error.message) + '</div>';
      // eslint-disable-next-line no-console
      console.error(error);
    }

    if (!isEmbed) {
      const url = new URL(location.href);
      url.searchParams.set('tab', tab.key);
      history.replaceState(null, '', url);
    }
  }

  function buildTabs() {
    tabsBox.innerHTML = TABS.map((tab) =>
      '<button class="tab" type="button" role="tab" data-tab="' + tab.key + '"' +
      ' aria-selected="false">' + escapeHtml(tab.label) + '</button>'
    ).join('');
    tabsBox.addEventListener('click', (event) => {
      const button = event.target.closest('.tab');
      if (button) show(button.dataset.tab);
    });
  }

  /* ── 부팅 ───────────────────────────────────────────────────────────── */
  function renderStamp(snapshot) {
    const stamp = document.getElementById('generatedAt');
    if (stamp) {
      // updated_at 은 값이 마지막으로 바뀐 시각, checked_at 은 수집기가 마지막으로
      // 확인한 시각이다(값이 그대로면 generated_at/updated_at 은 유지된다).
      const stamps = snapshot.updated_at || {};
      const checked = snapshot.checked_at || snapshot.generated_at;
      const elapsed = Date.now() - Date.parse(checked);
      stamp.textContent = '환율 갱신 ' + fmtStamp(stamps.fx || snapshot.generated_at) +
        ' · 금리 갱신 ' + fmtStamp(stamps.rates || snapshot.generated_at) +
        (snapshot.checked_at && snapshot.checked_at !== snapshot.generated_at
          ? ' · 확인 ' + fmtStamp(snapshot.checked_at) : '') +
        (elapsed > 60 * 60 * 1000 ? ' · 수집 지연' : '');
    }

    const sources = document.getElementById('sourceList');
    if (sources) {
      const names = new Set();
      Object.values(snapshot.sources || {}).forEach((list) => (list || []).forEach((n) => names.add(n)));
      sources.textContent = names.size ? [...names].join(', ') : '—';
    }
  }

  /** 현재 화면을 다시 그리되 사용자가 고른 통화·국가·기간은 되살린다
   *  (자동 갱신·테마 전환이 보던 화면을 초기화하지 않게). */
  function rerender() {
    const tile = app.querySelector('.tile[aria-pressed="true"]');
    const selected = tile ? { series: tile.dataset.series, kind: tile.dataset.kind } : null;
    const ranges = [...app.querySelectorAll('[data-role="range"] [aria-pressed="true"]')]
      .map((el) => el.dataset.range);
    const countries = [...app.querySelectorAll('[data-country][aria-pressed="true"]')]
      .map((el) => el.dataset.country);
    show(activeKey || embedTab || queryParam('tab') || 'overview', { force: true });
    if (countries.length) {
      const chips = [...app.querySelectorAll('[data-country]')];
      // 선택할 국가를 먼저 켜서 최소 한 국가 조건을 보존한다.
      for (const desired of [true, false]) chips.forEach((el) => {
        if (countries.includes(el.dataset.country) === desired &&
            (el.getAttribute('aria-pressed') === 'true') !== desired) el.click();
      });
    }
    if (selected) [...app.querySelectorAll('.tile')].find((el) =>
      el.dataset.series === selected.series && el.dataset.kind === selected.kind)?.click();
    app.querySelectorAll('[data-role="range"]').forEach((row, index) => {
      [...row.querySelectorAll('[data-range]')].find((el) => el.dataset.range === ranges[index])?.click();
    });
  }

  async function refreshSnapshot() {
    if (document.hidden || refreshing) return;
    refreshing = true;
    const before = BMStore.snapshot;
    try {
      const snapshot = await BMStore.loadSnapshot(true);
      renderStamp(snapshot);
      if (before?.generated_at === snapshot.generated_at) return;
      const market = activeKey === 'fx' ? 'fx' : activeKey === 'credit' ? 'credit'
        : ['government', 'policy'].includes(activeKey) ? 'rates' : null;
      if (market && before?.updated_at?.[market] &&
          before.updated_at[market] === snapshot.updated_at?.[market]) return;
      rerender();
    } catch (error) {
      const stamp = document.getElementById('generatedAt');
      if (stamp) stamp.textContent = '새 데이터 확인 실패 · 기존 값 표시 중 · 1분 후 재시도';
    } finally {
      refreshing = false;
    }
  }

  async function boot() {
    initTheme();
    if (isEmbed) {
      document.body.classList.add('is-embed');
      if (queryParam('bg') === 'transparent') document.body.classList.add('bg-transparent');
      // 테마 메시지를 받을 준비가 됐다 — 허브는 이걸 받은 뒤에만 리로드 대신 vc:theme 을 보낸다.
      postToParent({ source: 'vc', type: 'vc:ready', tool: TOOL_ID }, hubOrigin());
    }

    try {
      await BMStore.loadSnapshot();
    } catch (error) {
      app.innerHTML =
        '<div class="error-note">데이터를 불러오지 못했습니다 — ' + escapeHtml(error.message) +
        '<br>잠시 후 새로고침해 주세요.</div>';
      return;
    }

    renderStamp(BMStore.snapshot);
    setInterval(refreshSnapshot, 60 * 1000);
    document.addEventListener('visibilitychange', refreshSnapshot);
    window.addEventListener('online', refreshSnapshot);

    if (isEmbed) {
      show(embedTab);
      // 임베드 높이를 부모가 iframe 에 맞출 수 있도록 알려준다.
      notifyHeight();
      new ResizeObserver(debounce(notifyHeight, 120)).observe(document.body);
      return;
    }

    buildTabs();
    document.getElementById('themeToggle')?.addEventListener('click', toggleTheme);
    updateThemeButton();
    show(queryParam('tab') || 'overview');
  }

  /** 부모가 허브인지 — 알 수 없으면(ancestorOrigins·referrer 없음) 보내 본다.
   *  origin 을 지정한 postMessage 는 다른 부모에게 전달되지 않으므로 안전하지만,
   *  다른 임베더의 콘솔에 origin 불일치 경고를 남기지 않으려고 미리 거른다. */
  function parentIsHub() {
    const hub = hubOrigin();
    try {
      const ancestors = window.location.ancestorOrigins;
      if (ancestors && ancestors.length) return ancestors[0] === hub;
      if (document.referrer) return new URL(document.referrer).origin === hub;
    } catch (e) { /* 판단 불가 */ }
    return true;
  }

  function postToParent(message, targetOrigin) {
    if (window.parent === window) return;
    if (targetOrigin !== '*' && !parentIsHub()) return;
    try {
      window.parent.postMessage(message, targetOrigin);
    } catch (e) { /* 부모가 사라졌거나 거부하면 무시 */ }
  }

  /** 부모 창에 콘텐츠 높이를 알린다. 부모는 받아서 iframe.height 를 맞춘다. */
  function notifyHeight() {
    const height = document.body.scrollHeight;
    // 구 형식 — 허브 외의 임베더도 쓸 수 있게 origin 을 가리지 않는다(높이만 담는다).
    postToParent({ source: 'bond-mate', type: 'height', height }, '*');
    postToParent({ source: 'vc', type: 'vc:height', tool: TOOL_ID, height }, hubOrigin());
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
