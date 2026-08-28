/* 신용등급별 회사채 화면.
 *
 * 두 가지를 나란히 보여준다:
 *   수익률(effective yield) — 실제로 받는 금리
 *   OAS(옵션조정 스프레드)   — 같은 만기 국채 대비 얹은 값. 신용 위험의 가격.
 *
 * 미국(ICE BofA 지수, AAA~CCC)과 한국(ECOS 무보증 3년 AA-/BBB-)은 등급 체계와
 * 만기가 달라 한 곡선에 섞지 않고 따로 싣는다.
 */

'use strict';

const BMCredit = (function () {
  function orderedRatings(snapshot) {
    return Object.entries(snapshot.credit || {})
      .sort((a, b) => a[1].order - b[1].order);
  }

  function tilesHtml(snapshot, metric) {
    return orderedRatings(snapshot).map(([rating, meta]) => {
      const quote = meta[metric];
      if (!quote || quote.value == null) return '';
      return BMViews.tileHtml({
        seriesId: rating,
        kind: metric === 'oas' ? 'credit_oas' : 'credit_yield',
        label: meta.label + (meta.investment_grade ? '' : ' (하이일드)'),
        valueText: quote.value.toFixed(2),
        change: quote.change,
        date: quote.date,
        digits: 2,
      });
    }).join('');
  }

  function krTilesHtml(snapshot) {
    return Object.entries(snapshot.credit_kr || {}).map(([rating, quote]) => {
      if (quote.value == null) return '';
      return BMViews.tileHtml({
        seriesId: rating,
        kind: 'credit_kr',
        label: quote.label || rating,
        valueText: quote.value.toFixed(2),
        change: quote.change,
        date: quote.date,
        digits: 2,
      });
    }).join('');
  }

  function ladderTableHtml(snapshot) {
    const rows = orderedRatings(snapshot).map(([rating, meta]) => {
      const y = meta.yield?.value;
      const oas = meta.oas?.value;
      return '<tr>' +
        '<td class="text"><span class="pill ' + (meta.investment_grade ? 'ig' : 'hy') + '">' +
        escapeHtml(meta.label) + '</span></td>' +
        '<td class="num">' + escapeHtml(fmtPct(y, 2)) + '</td>' +
        BMViews.changeCellHtml(meta.yield?.change, 3) +
        '<td class="num">' + escapeHtml(fmtBp(toBp(oas))) + '</td>' +
        BMViews.changeCellHtml(meta.oas?.change, 3) +
        '<td class="text" style="color:var(--text-faint)">' +
        escapeHtml(meta.investment_grade ? '투자등급' : '하이일드') + '</td>' +
        '</tr>';
    }).join('');

    return '<div class="card"><div class="table-wrap"><table class="data"><thead><tr>' +
      '<th class="text">등급</th><th>수익률</th><th>전일</th><th>국채 대비</th><th>전일</th>' +
      '<th class="text">구분</th></tr></thead><tbody>' + rows + '</tbody></table></div></div>';
  }

  function render(root, snapshot) {
    const hasKr = Object.keys(snapshot.credit_kr || {}).length > 0;

    root.innerHTML =
      BMViews.sectionHtml(
        '등급별 사다리',
        '미국 ICE BofA 회사채 지수',
        ladderTableHtml(snapshot)
      ) +
      BMViews.sectionHtml(
        '등급별 스프레드 곡선',
        '등급이 내려갈수록 국채 대비 얹는 값이 커진다',
        '<div class="card chart-card"><div class="chart-box" id="crOas"></div></div>'
      ) +
      BMViews.sectionHtml(
        '수익률 히스토리',
        '등급을 누르면 아래 그래프가 바뀝니다',
        '<div class="grid grid-auto">' + tilesHtml(snapshot, 'yield') + '</div>' +
        '<div style="height:12px"></div>' +
        BMViews.historyPanelHtml('crHistory', '등급을 선택하세요', '')
      ) +
      (hasKr
        ? BMViews.sectionHtml(
            '한국 회사채',
            '무보증 3년 · 한국은행 ECOS',
            '<div class="grid grid-auto">' + krTilesHtml(snapshot) + '</div>'
          )
        : '') +
      BMViews.embedNoteHtml('credit');

    drawOas(root.querySelector('#crOas'), snapshot);
    window.addEventListener('resize', debounce(() => drawOas(root.querySelector('#crOas'), snapshot), 200));

    const panel = BMViews.bindHistoryPanel(
      root, 'crHistory',
      async (target) => {
        await BMStore.loadHistory('credit');
        const kind = target.kind === 'credit_oas' ? 'oas'
          : target.kind === 'credit_kr' ? 'kr_yield' : 'yield';
        return BMStore.creditSeries(kind, target.seriesId);
      },
      (v) => v.toFixed(2) + '%'
    );

    const first = root.querySelector('.tile[data-series]');
    if (panel && first) {
      panel.select({
        seriesId: first.dataset.series, kind: first.dataset.kind,
        label: first.dataset.label, digits: 2,
      });
    }
  }

  function drawOas(box, snapshot) {
    if (!box) return;
    const items = orderedRatings(snapshot)
      .map(([, meta]) => ({
        label: meta.label,
        value: toBp(meta.oas?.value),
        color: meta.color,
      }))
      .filter((i) => i.value != null);

    BMChart.bars(box, { items, yFormat: (v) => Math.round(v) + 'bp', labelWidth: 82 });
  }

  return { render };
})();
