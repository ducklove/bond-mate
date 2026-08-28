/* 화면들이 공유하는 조각 — 지표 타일, 기간 선택이 붙은 히스토리 패널.
 *
 * 히스토리 패널은 이 서비스의 핵심 상호작용이다(모든 지표에 "히스토리를 볼 수
 * 있게" 가 요구사항). 어느 화면에서 열든 같은 방식으로 동작하도록 여기 한 곳에
 * 둔다: 타일을 누르면 아래 패널이 그 지표로 바뀌고, 기간 칩으로 구간을 좁힌다.
 */

'use strict';

const BMViews = (function () {
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
      '<span class="tile-label">' + escapeHtml(opts.label) + '</span>' +
      '<span class="tile-value">' + escapeHtml(opts.valueText) +
      (unit ? '<span class="tile-unit">' + escapeHtml(unit) + '</span>' : '') + '</span>' +
      '<span class="tile-change ' + changeClass(change) + '">' +
      escapeHtml(fmtChange(change, opts.changeDigits == null ? 3 : opts.changeDigits)) + '</span>' +
      (opts.date ? '<span class="tile-date">' + escapeHtml(fmtDate(opts.date)) + '</span>' : '') +
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

  /**
   * 히스토리 패널을 활성화한다.
   *
   * @param root       패널을 감싸는 요소(타일도 이 안에 있어야 한다)
   * @param panelId    historyPanelHtml 에 준 id
   * @param loader     ({seriesId, kind}) => Promise<[[날짜,값]]>
   * @param formatter  (value) => 표시 문자열
   */
  function bindHistoryPanel(root, panelId, loader, formatter) {
    const panel = root.querySelector('#' + panelId);
    if (!panel) return null;

    const box = panel.querySelector('[data-role="box"]');
    const titleEl = panel.querySelector('[data-role="title"]');
    const subEl = panel.querySelector('[data-role="sub"]');
    let current = null;
    let range = '5y';
    let points = [];

    function draw() {
      if (!current) return;
      BMChart.line(box, {
        series: [{ key: current.seriesId, label: current.label, points: BMStore.withinRange(points, range) }],
        yFormat: formatter,
        height: 250,
      });
    }

    async function select(target) {
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
        points = await loader(target);
      } catch (error) {
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
    });

    window.addEventListener('resize', debounce(draw, 200));
    return { select, redraw: draw };
  }

  /** 상승/하락을 색으로 표시한 전일대비 셀. */
  function changeCellHtml(change, digits) {
    return '<td class="num ' + changeClass(change) + '">' + escapeHtml(fmtChange(change, digits)) + '</td>';
  }

  function embedNoteHtml(view) {
    const href = 'https://ducklove.github.io/bond-mate/?tab=' + encodeURIComponent(view || 'overview');
    return '<p class="embed-note">출처: <a href="' + href + '" target="_blank" rel="noopener">bond-mate</a></p>';
  }

  return {
    RANGES,
    sectionHtml,
    tileHtml,
    rangeChipsHtml,
    historyPanelHtml,
    bindHistoryPanel,
    changeCellHtml,
    embedNoteHtml,
  };
})();
