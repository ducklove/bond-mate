/* 화면들이 공유하는 조각 — 지표 타일, 기간 선택이 붙은 히스토리 패널.
 *
 * 히스토리 패널은 이 서비스의 핵심 상호작용이다(모든 지표에 "히스토리를 볼 수
 * 있게" 가 요구사항). 어느 화면에서 열든 같은 방식으로 동작하도록 여기 한 곳에
 * 둔다: 기준/비교 항목을 고르고, 기간과 표시 방식을 바꿔 함께 살펴본다.
 */

'use strict';

const BMViews = (function () {
  let viewController = new AbortController();
  const comparisonStates = new Map();

  function beginRender() {
    viewController.abort();
    viewController = new AbortController();
  }

  function onResize(callback) {
    const signal = viewController.signal;
    window.addEventListener('resize', debounce(() => {
      if (!signal.aborted) callback();
    }, 200), { signal });
  }
  const RANGES = [
    { key: '1y', label: '1년' },
    { key: '3y', label: '3년' },
    { key: '5y', label: '5년' },
    { key: '10y', label: '10년' },
    { key: 'max', label: '전체' },
  ];

  function sectionHtml(title, hint, body, extraHeadHtml) {
    return (
      '<section class="section">' +
      '<div class="section-head"><h2>' + escapeHtml(title) + '</h2>' +
      (hint ? '<span class="hint">' + escapeHtml(hint) + '</span>' : '') +
      (extraHeadHtml ? '<span class="spacer"></span>' + extraHeadHtml : '') +
      '</div>' + body + '</section>'
    );
  }

  /** 값 하나짜리 타일. 누르면 히스토리 패널이 이 지표로 바뀐다. */
  function tileHtml(opts) {
    const change = opts.change;
    const unit = opts.unit == null ? '%' : opts.unit;
    return (
      '<button class="tile" type="button" data-series="' + escapeHtml(opts.seriesId) + '"' +
      ' data-kind="' + escapeHtml(opts.kind || 'rates') + '"' +
      ' data-label="' + escapeHtml(opts.label) + '"' +
      ' data-digits="' + (opts.digits == null ? 2 : opts.digits) + '"' +
      ' aria-pressed="false">' +
      '<span class="tile-label">' + escapeHtml(opts.displayLabel || opts.label) + '</span>' +
      '<span class="tile-value">' + escapeHtml(opts.valueText) +
      (unit ? '<span class="tile-unit">' + escapeHtml(unit) + '</span>' : '') + '</span>' +
      '<span class="tile-change ' + changeClass(change) + '">' +
      escapeHtml(unit === '%' ? fmtChangeBp(change)
        : fmtChange(change, opts.changeDigits == null ? 3 : opts.changeDigits)) + '</span>' +
      (opts.date ? '<span class="tile-date">' + escapeHtml(fmtQuoteDate(opts)) + '</span>' : '') +
      '</button>'
    );
  }

  function rangeChipsHtml(active) {
    return '<span class="chip-row" data-role="range">' + RANGES.map((r) =>
      '<button class="chip" type="button" data-range="' + r.key + '"' +
      ' aria-pressed="' + (r.key === active ? 'true' : 'false') + '">' +
      r.label + '</button>'
    ).join('') + '</span>';
  }

  function historyPanelHtml(id, title, sub) {
    return (
      '<div class="card chart-card" id="' + id + '">' +
      '<div class="chart-head">' +
      '<span class="chart-title" data-role="title">' + escapeHtml(title || '') + '</span>' +
      '<span class="chart-sub" data-role="sub">' + escapeHtml(sub || '') + '</span>' +
      '<span class="spacer"></span>' + rangeChipsHtml('5y') +
      '</div>' +
      '<div class="chart-box" data-role="box"></div>' +
      '</div>'
    );
  }

  /** 세 화면의 모든 지표를 선택기에 제공해 탭을 옮기지 않고도 비교한다. */
  function comparisonCatalog(snapshot) {
    const catalog = [];
    Object.entries(snapshot.countries || {}).forEach(([code, country]) => {
      const name = (country.flag || '') + ' ' + country.name;
      (snapshot.curves?.[code] || []).filter((p) => p.maturity > 0)
        .sort((a, b) => a.maturity - b.maturity).forEach((point) => {
          if (snapshot.rates?.[point.series_id]?.value == null) return;
          catalog.push({ seriesId: point.series_id, kind: 'rates', label: name + ' ' + point.tenor,
            group: '국채 · ' + country.name, unit: '%', digits: 2 });
        });
      ['_BASE', '_ON'].forEach((suffix) => {
        if (snapshot.rates?.[code + suffix]?.value == null) return;
        catalog.push({ seriesId: code + suffix, kind: 'rates',
          label: name + (suffix === '_BASE' ? ' 기준금리' : ' 익일물'),
          group: '기준금리 · ' + country.name, unit: '%', digits: 2 });
      });
    });
    const fxUnits = { KRW: '원', USD: '달러', JPY: '엔', CNY: '위안', INR: '루피', BRL: '헤알', MXN: '페소', IDX: 'pt' };
    Object.entries(snapshot.fx || {}).forEach(([pair, quote]) => {
      if (quote.value == null) return;
      catalog.push({ seriesId: pair, kind: 'fx', label: quote.label || pair,
        group: pair.endsWith('_KRW') ? '환율 · 원화' : '환율 · 주요 통화쌍',
        unit: fxUnits[pair.split('_')[1]] || pair.split('_')[1], digits: BMFx.digitsFor(pair) });
    });
    return catalog.map((item) => ({ ...item, key: item.kind + ':' + item.seriesId }));
  }

  function comparisonPanelHtml(id, selectorHtml) {
    return '<div class="card history-explorer" id="' + id + '" data-comparison-panel>' +
      '<div class="comparison-slots">' + ['primary', 'comparison'].map((slot, index) =>
        '<div class="comparison-slot" data-slot-card="' + slot + '">' +
        '<button type="button" class="slot-button" data-slot="' + slot + '" aria-pressed="' + (!index) + '">' +
        '<span class="selection-badge">' + (index ? 'B' : 'A') + '</span> ' + (index ? '비교 항목' : '기준 항목') + '</button>' +
        '<label class="sr-only" for="' + id + '-' + slot + '">' + (index ? '비교 항목 선택' : '기준 항목 선택') + '</label>' +
        '<select class="series-select" id="' + id + '-' + slot + '" data-series-slot="' + slot + '"></select>' +
        (index ? '<button type="button" class="ghost-btn comparison-remove" data-role="remove-comparison" aria-label="비교 항목 해제" hidden>×</button>' : '') +
        '</div>'
      ).join('') + '</div>' +
      '<p class="selection-hint" data-role="selection-hint" aria-live="polite"></p>' +
      '<div class="history-browser">' + selectorHtml + '</div>' +
      '<div class="chart-head"><span class="chart-title" data-role="title">히스토리</span>' +
      '<span class="spacer"></span>' + rangeChipsHtml('5y') + '</div>' +
      '<div class="comparison-display"><span class="chip-row" data-role="display-mode">' +
      '<button type="button" class="chip" data-mode="value" aria-pressed="true">실제 값</button>' +
      '<button type="button" class="chip" data-mode="index" aria-pressed="false">시작값 100</button>' +
      '</span><span class="chart-sub" data-role="scale-note"></span></div>' +
      '<div class="legend comparison-legend" data-role="legend"></div>' +
      '<div class="chart-box" data-role="box"></div>' +
      '<p class="chart-sub history-status" data-role="sub" aria-live="polite"></p></div>';
  }

  /** 같은 기간으로 자른 뒤 필요하면 공통 구간의 첫 관측값을 100으로 맞춘다. */
  function comparisonSeries(entries, range, mode) {
    let series = entries.map((entry, index) => ({ ...entry.target,
      points: BMStore.withinRange(entry.points, range),
      color: cssVar(index ? '--compare-ink' : '--chart-ink', index ? '#b45309' : '#2563eb'),
      badge: index ? 'B' : 'A',
    }));
    if (mode !== 'index') return { series };
    if (series.some((s) => !s.points.length)) return { series: [], error: '선택한 기간에 두 항목의 관측값이 있어야 시작값을 100으로 맞출 수 있습니다.' };
    const start = series.reduce((date, s) => s.points[0][0] > date ? s.points[0][0] : date, '');
    const end = series.reduce((date, s) => s.points[s.points.length - 1][0] < date ? s.points[s.points.length - 1][0] : date, '9999');
    series = series.map((s) => ({ ...s, points: s.points.filter((p) => p[0] >= start && p[0] <= end) }));
    if (series.some((s) => !s.points.length)) return { series: [], error: '두 항목의 히스토리에 겹치는 기간이 없습니다.' };
    if (series.some((s) => s.points[0][1] <= 0)) return { series: [], error: '시작값이 0 이하인 항목은 100 기준으로 비교할 수 없습니다. 실제 값을 보거나 다른 항목을 선택하세요.' };
    return { series: series.map((s) => ({ ...s, baseDate: s.points[0][0], baseValue: s.points[0][1],
      points: s.points.map(([date, value]) => [date, value / s.points[0][1] * 100]),
    })) };
  }

  function bindComparisonPanel(root, panelId, snapshot, initialKey) {
    const signal = viewController.signal;
    const panel = root.querySelector('#' + panelId);
    if (!panel) return null;
    const catalog = comparisonCatalog(snapshot);
    const byKey = new Map(catalog.map((target) => [target.key, target]));
    const saved = comparisonStates.get(panelId) || {};
    let primary = byKey.get(saved.primary) || byKey.get(initialKey) || catalog[0];
    let comparison = byKey.get(saved.comparison) || null;
    let activeSlot = comparison && saved.activeSlot === 'comparison' ? 'comparison' : 'primary';
    let range = saved.range || '5y';
    let mode = saved.mode || 'value';
    let entries = [];
    let requestId = 0;
    const box = panel.querySelector('[data-role="box"]');
    const sub = panel.querySelector('[data-role="sub"]');
    const hint = panel.querySelector('[data-role="selection-hint"]');
    const selects = [...panel.querySelectorAll('[data-series-slot]')];
    const groups = new Map();
    catalog.forEach((target) => {
      if (!groups.has(target.group)) groups.set(target.group, []);
      groups.get(target.group).push(target);
    });
    const options = [...groups].map(([group, targets]) => '<optgroup label="' + escapeHtml(group) + '">' +
      targets.map((t) => '<option value="' + escapeHtml(t.key) + '">' + escapeHtml(t.label) + '</option>').join('') + '</optgroup>').join('');
    selects.forEach((select, index) => {
      select.innerHTML = '<option value=""' + (index ? '' : ' disabled') + '>' + (index ? '비교할 항목 추가' : '항목 선택') + '</option>' + options;
    });

    function save() {
      comparisonStates.set(panelId, { primary: primary?.key, comparison: comparison?.key, activeSlot, range, mode });
    }

    function syncSelection() {
      if (primary && comparison && primary.unit !== comparison.unit) mode = 'index';
      selects[0].value = primary?.key || '';
      selects[1].value = comparison?.key || '';
      panel.querySelectorAll('[data-slot]').forEach((button) => {
        const active = button.dataset.slot === activeSlot;
        button.setAttribute('aria-pressed', String(active));
        button.closest('[data-slot-card]').classList.toggle('is-active', active);
      });
      panel.querySelector('[data-role="remove-comparison"]').hidden = !comparison;
      hint.textContent = (activeSlot === 'primary' ? 'A 기준 항목' : 'B 비교 항목') +
        '을 아래에서 선택하세요. 선택기의 목록에서 국채·기준금리·환율을 서로 비교할 수 있습니다.';
      panel.querySelectorAll('.tile[data-series]').forEach((tile) => {
        const key = tile.dataset.kind + ':' + tile.dataset.series;
        const slot = key === primary?.key ? 'primary' : key === comparison?.key ? 'comparison' : '';
        tile.setAttribute('aria-pressed', String(!!slot));
        if (slot) tile.dataset.selection = slot; else delete tile.dataset.selection;
      });
      panel.querySelectorAll('[data-range]').forEach((chip) => chip.setAttribute('aria-pressed', String(chip.dataset.range === range)));
      panel.querySelectorAll('[data-mode]').forEach((chip) => {
        chip.setAttribute('aria-pressed', String(chip.dataset.mode === mode));
        chip.disabled = chip.dataset.mode === 'value' && !!comparison && primary.unit !== comparison.unit;
        chip.title = chip.disabled ? '단위가 다른 항목은 시작값 100으로 비교합니다.' : '';
      });
      save();
    }

    function draw() {
      if (signal.aborted || !entries.length) return;
      const result = comparisonSeries(entries, range, mode);
      panel.querySelector('[data-role="title"]').textContent = comparison ? '두 항목 비교' : primary.label + ' 히스토리';
      panel.querySelector('[data-role="scale-note"]').textContent = mode === 'index'
        ? '공통 기간의 각 항목 첫 관측값 = 100' : '단위: ' + primary.unit;
      panel.querySelector('[data-role="legend"]').innerHTML = entries.map((entry, index) => {
        const series = result.series[index];
        const latest = entry.points[entry.points.length - 1];
        const value = latest ? fmtNum(latest[1], entry.target.digits) + entry.target.unit : '관측값 없음';
        return '<span class="legend-item"><span class="legend-swatch" style="background:' +
          cssVar(index ? '--compare-ink' : '--chart-ink', index ? '#b45309' : '#2563eb') + '"></span>' +
          '<span>' + (index ? 'B ' : 'A ') + escapeHtml(entry.target.label) + ' · ' + escapeHtml(value) +
          (latest ? ' <span class="legend-date">' + fmtDate(latest[0]) + '</span>' : '') +
          (series?.baseDate ? ' <span class="legend-date">(100 기준: ' + fmtDate(series.baseDate) + ')</span>' : '') + '</span></span>';
      }).join('');
      if (result.error) box.innerHTML = '<div class="empty">' + escapeHtml(result.error) + '</div>';
      else BMChart.line(box, { series: result.series.map((s) => ({ ...s,
        valueFormat: mode === 'index' ? (v) => fmtNum(v, 2) : (v) => fmtNum(v, s.digits) + s.unit,
      })), yFormat: mode === 'index' ? (v) => fmtNum(v, 1) : (v) => fmtNum(v, primary.digits) + primary.unit,
        height: 280, label: entries.map((e) => e.target.label).join(' · '), area: !comparison });
      sub.textContent = entries.map((entry, index) => {
        const count = BMStore.withinRange(entry.points, range).length;
        return (index ? 'B' : 'A') + ' · ' + (entry.error ? '불러오기 실패: ' + entry.error : count.toLocaleString('ko-KR') + '개 관측');
      }).join(' / ');
    }

    async function load() {
      const currentRequest = ++requestId;
      syncSelection();
      const targets = [primary, comparison].filter(Boolean);
      entries = [];
      if (!targets.length) { box.innerHTML = '<div class="empty">선택할 지표가 없습니다.</div>'; return; }
      box.innerHTML = '<div class="loading">히스토리를 불러오는 중…</div>';
      panel.querySelector('[data-role="legend"]').innerHTML = '';
      sub.textContent = '불러오는 중…';
      const loaded = await Promise.allSettled(targets.map(async (target) => {
        await BMStore.loadHistory(target.kind);
        return target.kind === 'fx' ? BMStore.fxSeries(target.seriesId) : BMStore.ratesSeries(target.seriesId);
      }));
      if (signal.aborted || currentRequest !== requestId) return;
      entries = loaded.map((result, index) => ({ target: targets[index],
        points: result.status === 'fulfilled' ? result.value : [],
        error: result.status === 'rejected' ? result.reason.message : null,
      }));
      draw();
    }

    function select(key, slot = activeSlot) {
      const target = byKey.get(key);
      if (!target) return;
      if (target.key === (slot === 'primary' ? comparison : primary)?.key) {
        syncSelection();
        hint.textContent = '이미 선택한 항목입니다. 비교할 다른 항목을 선택하세요.';
        return;
      }
      if (slot === 'primary') primary = target; else comparison = target;
      activeSlot = slot;
      load();
    }

    panel.addEventListener('click', (event) => {
      const slot = event.target.closest('[data-slot]');
      if (slot) { activeSlot = slot.dataset.slot; syncSelection(); return; }
      if (event.target.closest('[data-role="remove-comparison"]')) {
        comparison = null; activeSlot = 'primary'; load(); return;
      }
      const tile = event.target.closest('.tile[data-series]');
      if (tile) { select(tile.dataset.kind + ':' + tile.dataset.series); return; }
      const chip = event.target.closest('[data-range], [data-mode]');
      if (chip) {
        if (chip.dataset.range) range = chip.dataset.range; else mode = chip.dataset.mode;
        syncSelection(); draw();
      }
    }, { signal });
    panel.addEventListener('change', (event) => {
      const selectEl = event.target.closest('[data-series-slot]');
      if (!selectEl) return;
      if (!selectEl.value && selectEl.dataset.seriesSlot === 'comparison') {
        comparison = null; activeSlot = 'primary'; load();
      } else select(selectEl.value, selectEl.dataset.seriesSlot);
    }, { signal });
    onResize(draw);
    load();
    return { select, syncSelection, redraw: draw };
  }

  /**
   * 히스토리 패널을 활성화한다.
   *
   * @param root       패널을 감싸는 요소(타일도 이 안에 있어야 한다)
   * @param panelId    historyPanelHtml 에 준 id
   * @param loader     ({seriesId, kind}) => Promise<[[날짜,값]]>
   * @param formatter  (value) => 표시 문자열
   */
  function bindHistoryPanel(root, panelId, loader, formatter) {
    const signal = viewController.signal;
    let selectionId = 0;
    const panel = root.querySelector('#' + panelId);
    if (!panel) return null;

    const box = panel.querySelector('[data-role="box"]');
    const titleEl = panel.querySelector('[data-role="title"]');
    const subEl = panel.querySelector('[data-role="sub"]');
    let current = null;
    let range = '5y';
    let points = [];

    function draw() {
      if (!current || signal.aborted) return;
      BMChart.line(box, {
        series: [{ key: current.seriesId, label: current.label, points: BMStore.withinRange(points, range) }],
        yFormat: formatter,
        height: 250,
      });
    }

    async function select(target) {
      const requestId = ++selectionId;
      current = target;
      titleEl.textContent = target.label;
      subEl.textContent = '불러오는 중…';
      box.innerHTML = '<div class="loading">히스토리를 불러오는 중…</div>';

      root.querySelectorAll('.tile[data-series]').forEach((tile) => {
        tile.setAttribute(
          'aria-pressed',
          tile.dataset.series === target.seriesId && tile.dataset.kind === target.kind ? 'true' : 'false'
        );
      });

      try {
        const loaded = await loader(target);
        if (signal.aborted || requestId !== selectionId) return;
        points = loaded;
      } catch (error) {
        if (signal.aborted || requestId !== selectionId) return;
        box.innerHTML = '<div class="empty">히스토리를 불러오지 못했습니다 — ' + escapeHtml(error.message) + '</div>';
        subEl.textContent = '';
        return;
      }
      subEl.textContent = points.length
        ? points.length.toLocaleString('ko-KR') + '개 관측 · ' + fmtDate(points[0][0]) + ' ~ ' + fmtDate(points[points.length - 1][0])
        : '히스토리 없음';
      draw();
    }

    root.addEventListener('click', (event) => {
      const tile = event.target.closest('.tile[data-series]');
      if (tile && root.contains(tile)) {
        select({
          seriesId: tile.dataset.series,
          kind: tile.dataset.kind,
          label: tile.dataset.label,
          digits: Number(tile.dataset.digits || 2),
        });
        return;
      }
      const chip = event.target.closest('[data-role="range"] .chip');
      if (chip && panel.contains(chip)) {
        range = chip.dataset.range;
        panel.querySelectorAll('[data-role="range"] .chip').forEach((c) =>
          c.setAttribute('aria-pressed', c === chip ? 'true' : 'false'));
        draw();
      }
    }, { signal });

    onResize(draw);
    return { select, redraw: draw };
  }

  /** 상승/하락을 색으로 표시한 금리·스프레드 전일대비 셀(bp). */
  function changeCellHtml(change) {
    return '<td class="num ' + changeClass(change) + '">' + escapeHtml(fmtChangeBp(change)) + '</td>';
  }

  function embedNoteHtml(view) {
    const href = 'https://ducklove.github.io/bond-mate/?tab=' + encodeURIComponent(view || 'overview');
    return '<p class="embed-note">출처: <a href="' + href + '" target="_blank" rel="noopener">bond-mate</a></p>';
  }

  return {
    beginRender,
    onResize,
    RANGES,
    sectionHtml,
    tileHtml,
    rangeChipsHtml,
    historyPanelHtml,
    bindHistoryPanel,
    comparisonCatalog,
    comparisonPanelHtml,
    comparisonSeries,
    bindComparisonPanel,
    changeCellHtml,
    embedNoteHtml,
  };
})();
