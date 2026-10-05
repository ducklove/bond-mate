/* 개요 · 국채 · 기준금리 화면. */

'use strict';

const BMRates = (function () {
  // 커브를 겹쳐 그릴 기본 국가 — 성격이 다른 셋(고금리·중간·초저금리)이라
  // 한 그림에서 수준 차이가 바로 읽힌다.
  const DEFAULT_CURVE_COUNTRIES = ['US', 'KR', 'JP'];
  const COUNTRY_COLORS = {
    US: '#e11d48', KR: '#2563eb', JP: '#16a34a', DE: '#f59e0b', GB: '#7c3aed',
    CN: '#dc2626', FR: '#0891b2', IT: '#65a30d', ES: '#c026d3', CH: '#64748b',
    CA: '#ea580c', AU: '#0d9488', IN: '#a16207', BR: '#15803d', MX: '#9333ea', ID: '#0369a1',
  };
  let historyCountry = 'KR';

  function countryColor(code) {
    return COUNTRY_COLORS[code] || cssVar('--chart-ink', '#2563eb');
  }

  /* ── 개요 ───────────────────────────────────────────────────────────── */
  function heroHtml(snapshot) {
    const h = snapshot.highlights || {};
    const usd = snapshot.fx?.USD_KRW;
    const kr10 = snapshot.rates?.KR10Y;
    const us10 = snapshot.rates?.US10Y;
    const bbb = snapshot.credit?.BBB?.oas;

    const stats = [
      {
        k: '미국 10년물',
        v: fmtPct(us10?.value, 2),
        n: us10 ? fmtChangeBp(us10.change) + ' · ' + fmtDate(us10.date) : '—',
        cls: changeClass(us10?.change),
      },
      {
        k: '한국 10년물',
        v: fmtPct(kr10?.value, 2),
        n: kr10 ? fmtChangeBp(kr10.change) + ' · ' + fmtDate(kr10.date) : '—',
        cls: changeClass(kr10?.change),
      },
      {
        k: '달러/원',
        v: fmtNum(usd?.value, 2),
        n: usd ? fmtChange(usd.change, 2) + '원 · ' + fmtQuoteDate(usd) : '—',
        cls: changeClass(usd?.change),
      },
      {
        k: '미국 10Y−2Y',
        v: h.us_curve_spread_bp == null ? '—' : fmtBp(h.us_curve_spread_bp),
        n: h.us_curve_inverted == null ? '—' : (h.us_curve_inverted ? '장단기 역전' : '정상 우상향'),
        cls: h.us_curve_inverted ? 'up' : '',
      },
      {
        k: 'BBB 스프레드',
        v: bbb?.value == null ? '—' : fmtBp(toBp(bbb.value)),
        n: '국채 대비 · ' + (bbb?.date ? fmtDate(bbb.date) : '—'),
        cls: '',
      },
    ];

    return '<div class="overview-hero">' + stats.map((s) =>
      '<div class="hero-stat"><div class="k">' + escapeHtml(s.k) + '</div>' +
      '<div class="v ' + (s.cls || '') + '">' + escapeHtml(s.v) + '</div>' +
      '<div class="n">' + escapeHtml(s.n) + '</div></div>'
    ).join('') + '</div>';
  }

  function renderOverview(root, snapshot) {
    const curveCountries = DEFAULT_CURVE_COUNTRIES.filter((c) => (snapshot.curves || {})[c]);

    root.innerHTML =
      heroHtml(snapshot) +
      BMViews.sectionHtml(
        '주요국 수익률 곡선',
        '기준금리부터 최장 만기까지 · 연 %',
        '<div class="card chart-card"><div class="chart-box" id="ovCurve"></div>' +
        '<div class="legend" id="ovCurveLegend"></div></div>'
      ) +
      BMViews.sectionHtml(
        '국가별 10년물',
        '높은 순',
        '<div class="card chart-card"><div class="chart-box" id="ovTen"></div></div>'
      ) +
      BMViews.sectionHtml(
        '신용등급별 회사채 수익률',
        '미국 ICE BofA 지수 · 연 %',
        '<div class="card chart-card"><div class="chart-box" id="ovCredit"></div></div>'
      ) +
      BMViews.embedNoteHtml('overview');

    drawCurves(root.querySelector('#ovCurve'), root.querySelector('#ovCurveLegend'), snapshot, curveCountries);
    drawTenYear(root.querySelector('#ovTen'), snapshot);
    drawCreditBars(root.querySelector('#ovCredit'), snapshot);

    BMViews.onResize(() => {
      drawCurves(root.querySelector('#ovCurve'), root.querySelector('#ovCurveLegend'), snapshot, curveCountries);
      drawTenYear(root.querySelector('#ovTen'), snapshot);
      drawCreditBars(root.querySelector('#ovCredit'), snapshot);
    });
  }

  function drawCurves(box, legendBox, snapshot, countries) {
    if (!box) return;
    const series = countries.map((code) => ({
      key: code,
      label: (snapshot.countries?.[code]?.name) || code,
      color: countryColor(code),
      points: (snapshot.curves[code] || [])
        .filter((p) => p.value != null)
        .map((p) => [p.maturity, p.value, p.tenor]),
    })).filter((s) => s.points.length > 1);

    BMChart.curve(box, { series, yFormat: (v) => v.toFixed(2) + '%', height: 260 });

    if (legendBox) {
      legendBox.innerHTML = series.map((s) =>
        '<span class="legend-item"><span class="legend-swatch" style="background:' + s.color + '"></span>' +
        escapeHtml(s.label) + '</span>'
      ).join('');
    }
  }

  function drawTenYear(box, snapshot) {
    if (!box) return;
    const items = Object.keys(snapshot.countries || {})
      .map((code) => {
        const quote = snapshot.rates?.[code + '10Y'];
        return quote && quote.value != null
          ? { label: (snapshot.countries[code].name || code), value: quote.value, color: countryColor(code) }
          : null;
      })
      .filter(Boolean)
      .sort((a, b) => b.value - a.value);

    BMChart.bars(box, { items, yFormat: (v) => v.toFixed(2) + '%' });
  }

  function drawCreditBars(box, snapshot) {
    if (!box) return;
    const items = Object.entries(snapshot.credit || {})
      .sort((a, b) => a[1].order - b[1].order)
      .map(([rating, meta]) => ({
        label: meta.label || rating,
        value: meta.yield?.value,
        color: meta.color,
      }))
      .filter((i) => i.value != null);

    BMChart.bars(box, { items, yFormat: (v) => v.toFixed(2) + '%' });
  }

  /* ── 국채 ───────────────────────────────────────────────────────────── */
  function renderGovernment(root, snapshot) {
    const curves = snapshot.curves || {};
    const countries = Object.keys(snapshot.countries || {}).filter((c) => (curves[c] || []).length);
    const deep = countries.filter((c) => snapshot.countries[c].has_curve);
    const selected = deep.length ? deep.slice(0, 3) : countries.slice(0, 3);
    const historyCountries = countries.filter((code) => (curves[code] || [])
      .some((p) => p.maturity > 0 && snapshot.rates?.[p.series_id]?.value != null));
    if (!historyCountries.includes(historyCountry)) historyCountry = historyCountries[0];

    const curveSection = BMViews.sectionHtml(
        '수익률 곡선 비교',
        '국가를 눌러 겹쳐 보세요',
        '<div class="curve-layout">' +
        '<div class="card chart-card"><div class="chart-box" id="gvCurve"></div>' +
        '<div class="legend" id="gvLegend"></div></div>' +
        '<div class="card"><div class="table-wrap" id="gvTable"></div></div>' +
        '</div>',
        '<span class="chip-row" id="gvCountries">' + countries.map((code) =>
          '<button class="chip" type="button" data-country="' + code + '"' +
          ' aria-pressed="' + (selected.includes(code) ? 'true' : 'false') + '">' +
          escapeHtml((snapshot.countries[code].flag || '') + ' ' + snapshot.countries[code].name) +
          '</button>'
        ).join('') + '</span>'
      );
    root.innerHTML = BMViews.sectionHtml(
        '국채 히스토리',
        '국가를 고른 뒤 만기를 선택하세요',
        BMViews.comparisonPanelHtml('gvHistory',
          '<div class="selector-head"><span class="selector-label">국가</span>' +
          '<div class="chip-row" id="gvHistoryCountries">' + historyCountries.map((code) =>
            '<button class="chip" type="button" data-history-country="' + code + '" aria-pressed="' +
            (code === historyCountry) + '">' + escapeHtml((snapshot.countries[code].flag || '') + ' ' + snapshot.countries[code].name) + '</button>'
          ).join('') + '</div></div><div class="tenor-groups" id="gvTiles">' +
          tilesHtml(snapshot, historyCountry) + '</div>')
      ) + curveSection +
      BMViews.embedNoteHtml('government');

    const chosen = new Set(selected);
    const curveBox = root.querySelector('#gvCurve');
    const legendBox = root.querySelector('#gvLegend');
    const tableBox = root.querySelector('#gvTable');

    function refresh() {
      const list = countries.filter((c) => chosen.has(c));
      drawCurves(curveBox, legendBox, snapshot, list);
      tableBox.innerHTML = curveTableHtml(snapshot, list);
    }

    root.querySelector('#gvCountries').addEventListener('click', (event) => {
      const chip = event.target.closest('.chip[data-country]');
      if (!chip) return;
      const code = chip.dataset.country;
      if (chosen.has(code)) {
        if (chosen.size === 1) return;      // 최소 하나는 남긴다
        chosen.delete(code);
      } else {
        chosen.add(code);
      }
      chip.setAttribute('aria-pressed', chosen.has(code) ? 'true' : 'false');
      refresh();
    });

    refresh();

    const initial = snapshot.rates?.[historyCountry + '10Y']?.value != null
      ? historyCountry + '10Y' : root.querySelector('#gvTiles .tile')?.dataset.series;
    const panel = BMViews.bindComparisonPanel(root, 'gvHistory', snapshot, 'rates:' + initial);
    root.querySelector('#gvHistoryCountries').addEventListener('click', (event) => {
      const chip = event.target.closest('[data-history-country]');
      if (!chip) return;
      historyCountry = chip.dataset.historyCountry;
      root.querySelectorAll('[data-history-country]').forEach((button) =>
        button.setAttribute('aria-pressed', String(button === chip)));
      root.querySelector('#gvTiles').innerHTML = tilesHtml(snapshot, historyCountry);
      panel?.syncSelection();
    });

    BMViews.onResize(refresh);
  }

  function curveTableHtml(snapshot, countries) {
    const axis = [];
    countries.forEach((code) => (snapshot.curves[code] || []).forEach((p) => {
      if (!axis.some((a) => a.maturity === p.maturity)) axis.push({ maturity: p.maturity, tenor: p.tenor });
    }));
    axis.sort((a, b) => a.maturity - b.maturity);

    const head = '<tr><th class="text">만기</th>' + countries.map((code) =>
      '<th>' + escapeHtml(snapshot.countries[code].name) + '</th>').join('') + '</tr>';

    const body = axis.map((slot) => {
      const cells = countries.map((code) => {
        const point = (snapshot.curves[code] || []).find((p) => p.maturity === slot.maturity);
        if (!point || point.value == null) return '<td class="num flat">—</td>';
        return '<td class="num">' + point.value.toFixed(2) +
          ' <span class="' + changeClass(point.change) + '" style="font-size:11px">' +
          escapeHtml(fmtChangeBp(point.change)) + '</span></td>';
      }).join('');
      return '<tr><td class="text">' + escapeHtml(slot.tenor || maturityLabel(slot.maturity)) + '</td>' + cells + '</tr>';
    }).join('');

    return '<table class="data"><thead>' + head + '</thead><tbody>' + body + '</tbody></table>';
  }

  function tilesHtml(snapshot, code) {
    const groups = [
      { label: '단기', hint: '1년 이하', accepts: (m) => m <= 1 },
      { label: '중기', hint: '1년 초과 ~ 7년', accepts: (m) => m > 1 && m <= 7 },
      { label: '장기', hint: '7년 초과', accepts: (m) => m > 7 },
    ];
    const points = (snapshot.curves?.[code] || []).filter((p) => p.maturity > 0)
      .sort((a, b) => a.maturity - b.maturity);
    return groups.map((group) => {
      const tiles = points.filter((point) => group.accepts(point.maturity)).map((point) => {
        const quote = snapshot.rates?.[point.series_id];
        if (!quote || quote.value == null) return '';
        return BMViews.tileHtml({
          seriesId: point.series_id,
          kind: 'rates',
          label: (snapshot.countries[code].flag || '') + ' ' + snapshot.countries[code].name + ' ' + (point.tenor || ''),
          displayLabel: point.tenor || maturityLabel(point.maturity),
          valueText: quote.value.toFixed(2),
          change: quote.change,
          date: quote.date,
          digits: 2,
        });
      }).join('');
      return tiles ? '<div class="tenor-group"><h3>' + group.label + ' <span>' + group.hint + '</span></h3>' +
        '<div class="tenor-grid">' + tiles + '</div></div>' : '';
    }).join('') || '<div class="empty">표시할 만기가 없습니다.</div>';
  }

  /* ── 기준금리 ───────────────────────────────────────────────────────── */
  function renderPolicy(root, snapshot) {
    const rows = Object.keys(snapshot.countries || {})
      .map((code) => {
        const base = snapshot.rates?.[code + '_BASE'];
        const overnight = snapshot.rates?.[code + '_ON'];
        const ten = snapshot.rates?.[code + '10Y'];
        return base || overnight ? { code, meta: snapshot.countries[code], base, overnight, ten } : null;
      })
      .filter(Boolean)
      .sort((a, b) => (b.base?.value ?? -99) - (a.base?.value ?? -99));

    const table =
      '<div class="card"><div class="table-wrap"><table class="data"><thead><tr>' +
      '<th class="text">국가</th><th>기준금리</th><th>익일물</th><th>10년물</th>' +
      '<th>10년−기준</th><th class="text">기준일</th></tr></thead><tbody>' +
      rows.map((row) => {
        const spread = row.ten?.value != null && row.base?.value != null
          ? toBp(row.ten.value - row.base.value) : null;
        return '<tr>' +
          '<td class="text">' + escapeHtml((row.meta.flag || '') + ' ' + row.meta.name) + '</td>' +
          '<td class="num">' + escapeHtml(fmtPct(row.base?.value, 2)) + '</td>' +
          '<td class="num">' + escapeHtml(fmtPct(row.overnight?.value, 2)) + '</td>' +
          '<td class="num">' + escapeHtml(fmtPct(row.ten?.value, 2)) + '</td>' +
          '<td class="num ' + (spread != null && spread < 0 ? 'up' : '') + '">' + escapeHtml(fmtBp(spread)) + '</td>' +
          '<td class="text" style="color:var(--text-faint)">' + escapeHtml(fmtDate(row.base?.date || row.ten?.date)) + '</td>' +
          '</tr>';
      }).join('') +
      '</tbody></table></div></div>';

    const tiles = rows.map((row) => {
      const base = row.base;
      if (!base || base.value == null) return '';
      return BMViews.tileHtml({
        seriesId: row.code + '_BASE',
        kind: 'rates',
        label: (row.meta.flag || '') + ' ' + row.meta.name,
        valueText: base.value.toFixed(2),
        change: base.change,
        date: base.date,
        digits: 2,
      });
    }).join('');

    root.innerHTML = BMViews.sectionHtml(
        '기준금리 히스토리',
        '기준 항목과 비교 항목을 선택하세요',
        BMViews.comparisonPanelHtml('plHistory', '<div class="grid grid-auto">' + tiles + '</div>')
      ) + BMViews.sectionHtml('각국 정책금리', '기준금리 높은 순', table) +
      BMViews.embedNoteHtml('policy');

    const initial = snapshot.rates?.KR_BASE?.value != null ? 'KR_BASE' : root.querySelector('.tile')?.dataset.series;
    BMViews.bindComparisonPanel(root, 'plHistory', snapshot, 'rates:' + initial);
  }

  return { renderOverview, renderGovernment, renderPolicy, countryColor };
})();
