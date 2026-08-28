/* 환율 화면.
 *
 * 원화 크로스를 먼저, 그 밖의 주요 통화쌍을 뒤에 둔다. value-invest 가 이
 * 화면을 임베드하므로(?embed=fx) 원화 중심 구성이 그대로 쓰인다.
 */

'use strict';

const BMFx = (function () {
  const KRW_ORDER = ['USD_KRW', 'EUR_KRW', 'JPY_KRW', 'CNY_KRW', 'GBP_KRW', 'AUD_KRW', 'CAD_KRW', 'CHF_KRW'];
  const CROSS_ORDER = ['USD_JPY', 'EUR_USD', 'GBP_USD', 'USD_CNY', 'USD_INR', 'USD_BRL', 'USD_MXN', 'USD_IDX'];

  // 통화마다 읽는 자릿수가 다르다 — 달러/원은 소수 2자리, 유로/달러는 4자리.
  function digitsFor(pair) {
    if (pair === 'EUR_USD' || pair === 'GBP_USD' || pair === 'USD_CNY' ||
        pair === 'USD_BRL' || pair === 'USD_MXN') return 4;
    if (pair === 'USD_INR') return 3;
    return 2;
  }

  function tilesHtml(snapshot, pairs) {
    return pairs.map((pair) => {
      const quote = snapshot.fx?.[pair];
      if (!quote || quote.value == null) return '';
      const digits = digitsFor(pair);
      return BMViews.tileHtml({
        seriesId: pair,
        kind: 'fx',
        label: quote.label || pair,
        valueText: fmtNum(quote.value, digits),
        unit: '',
        change: quote.change,
        changeDigits: digits,
        date: quote.date,
        digits,
      });
    }).join('');
  }

  function render(root, snapshot) {
    const krw = KRW_ORDER.filter((p) => snapshot.fx?.[p]);
    const cross = CROSS_ORDER.filter((p) => snapshot.fx?.[p]);

    root.innerHTML =
      BMViews.sectionHtml(
        '원화 환율',
        '타일을 누르면 아래에 히스토리가 나옵니다',
        '<div class="grid grid-auto">' + tilesHtml(snapshot, krw) + '</div>'
      ) +
      (cross.length
        ? BMViews.sectionHtml('주요 통화쌍', '달러 기준', '<div class="grid grid-auto">' + tilesHtml(snapshot, cross) + '</div>')
        : '') +
      BMViews.sectionHtml('히스토리', '', BMViews.historyPanelHtml('fxHistory', '통화쌍을 선택하세요', '')) +
      BMViews.embedNoteHtml('fx');

    let activeDigits = 2;
    const panel = BMViews.bindHistoryPanel(
      root, 'fxHistory',
      async (target) => {
        activeDigits = target.digits;
        await BMStore.loadHistory('fx');
        return BMStore.fxSeries(target.seriesId);
      },
      (v) => fmtNum(v, activeDigits)
    );

    const first = root.querySelector('.tile[data-series]');
    if (panel && first) {
      panel.select({
        seriesId: first.dataset.series, kind: 'fx',
        label: first.dataset.label, digits: Number(first.dataset.digits || 2),
      });
    }
  }

  return { render, digitsFor };
})();
