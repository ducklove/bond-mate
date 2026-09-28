/* 앱 셸 — 탭 라우팅, 테마, 임베드 모드.
 *
 * 임베드 계약 (value-invest 등 부모 앱이 iframe 으로 부를 때)
 *   ?embed=<탭>      헤더·탭·푸터를 걷어내고 그 화면 하나만 그린다
 *   ?tab=<탭>        독립 실행에서 초기 탭 지정 (딥링크용)
 *   ?theme=light|dark 부모 테마에 맞춘다 (생략 시 시스템 설정)
 *   ?data=<경로>     스냅샷/히스토리 위치 재지정
 *
 * 탭 키는 부모가 URL 에 박아 쓰므로 **이름을 바꾸지 않는다**.
 */

'use strict';

(function () {
  const TABS = [
    { key: 'overview', label: '개요', render: (root, snap) => BMRates.renderOverview(root, snap) },
    { key: 'government', label: '국채', render: (root, snap) => BMRates.renderGovernment(root, snap) },
    { key: 'policy', label: '기준금리', render: (root, snap) => BMRates.renderPolicy(root, snap) },
    { key: 'fx', label: '환율', render: (root, snap) => BMFx.render(root, snap) },
    { key: 'credit', label: '사채', render: (root, snap) => BMCredit.render(root, snap) },
    { key: 'issuance', label: '발행', render: (root, snap) => BMIssuance.render(root, snap) },
  ];

  const app = document.getElementById('app');
  const tabsBox = document.getElementById('tabs');
  const embedTab = queryParam('embed');
  const isEmbed = !!embedTab;
  let activeKey = null;
  let refreshing = false;

  /* ── 테마 ───────────────────────────────────────────────────────────── */
  function applyTheme(theme) {
    // 'auto' 는 속성을 비워 시스템 설정(prefers-color-scheme)에 맡긴다.
    if (theme === 'light' || theme === 'dark') {
      document.documentElement.setAttribute('data-theme', theme);
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
  }

  function initTheme() {
    const fromUrl = queryParam('theme');
    if (fromUrl) { applyTheme(fromUrl); return; }
    let saved = null;
    try { saved = localStorage.getItem('bondmate.theme'); } catch (e) { /* 시크릿 모드 */ }
    applyTheme(saved || 'auto');
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : current === 'light' ? 'auto' : 'dark';
    applyTheme(next);
    try { localStorage.setItem('bondmate.theme', next); } catch (e) { /* 저장 불가면 이번 세션만 */ }
    // 차트는 CSS 변수 색을 그릴 때 읽어가므로 다시 그려야 색이 따라온다.
    if (activeKey) show(activeKey, { force: true });
  }

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
      const stamps = snapshot.updated_at || {};
      const elapsed = Date.now() - Date.parse(snapshot.generated_at);
      stamp.textContent = '환율 수집 ' + fmtStamp(stamps.fx || snapshot.generated_at) +
        ' · 금리 수집 ' + fmtStamp(stamps.rates || snapshot.generated_at) +
        (elapsed > 60 * 60 * 1000 ? ' · 수집 지연' : '');
    }

    const sources = document.getElementById('sourceList');
    if (sources) {
      const names = new Set();
      Object.values(snapshot.sources || {}).forEach((list) => (list || []).forEach((n) => names.add(n)));
      sources.textContent = names.size ? [...names].join(', ') : '—';
    }
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
      // 자동 갱신으로 사용자가 보고 있던 통화·국가·기간이 초기화되지 않게 한다.
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
    show(queryParam('tab') || 'overview');
  }

  /** 부모 창에 콘텐츠 높이를 알린다. 부모는 받아서 iframe.height 를 맞춘다. */
  function notifyHeight() {
    if (window.parent === window) return;
    try {
      window.parent.postMessage(
        { source: 'bond-mate', type: 'height', height: document.body.scrollHeight },
        '*'
      );
    } catch (e) { /* 부모가 다른 오리진이면 무시 */ }
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
