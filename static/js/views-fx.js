/* 환율 화면.
 *
 * 원화 크로스를 먼저, 그 밖의 주요 통화쌍을 뒤에 둔다. value-invest 가 이
 * 화면을 임베드하므로(?embed=fx) 원화 중심 구성이 그대로 쓰인다.
 */

'use strict';

const BMFx = (function () {
  const KRW_ORDER = ['USD_KRW', 'EUR_KRW', 'JPY_KRW', 'CNY_KRW', 'GBP_KRW', 'AUD_KRW', 'CAD_KRW', 'CHF_KRW'];
  const CROSS_ORDER = ['USD_JPY', 'EUR_USD', 'GBP_USD', 'USD_CNY', 'USD_INR', 'USD_BRL', 'USD_MXN', 'USD_IDX'];
  let activeGroup = 'krw';

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
        as_of: quote.as_of,
        quote_type: quote.quote_type,
        digits,
      });
    }).join('');
  }

  function render(root, snapshot) {
    const krw = KRW_ORDER.filter((p) => snapshot.fx?.[p]);
    const cross = CROSS_ORDER.filter((p) => snapshot.fx?.[p]);

    if (!krw.length) activeGroup = 'cross';
    if (!cross.length) activeGroup = 'krw';
    root.innerHTML =
      BMViews.sectionHtml('환율 히스토리', '원화 환율 · 주요 통화쌍 비교',
        BMViews.comparisonPanelHtml('fxHistory',
          '<div class="selector-head"><span class="selector-label">통화 구분</span><div class="chip-row">' +
          (krw.length ? '<button type="button" class="chip" data-fx-group="krw" aria-pressed="' + (activeGroup === 'krw') + '">원화 환율</button>' : '') +
          (cross.length ? '<button type="button" class="chip" data-fx-group="cross" aria-pressed="' + (activeGroup === 'cross') + '">주요 통화쌍</button>' : '') +
          '</div><span class="chart-sub" id="fxGroupNote"></span></div>' +
          '<div class="grid grid-auto" id="fxTiles"></div>')) +
      BMViews.embedNoteHtml('fx');

    function refreshTiles() {
      root.querySelector('#fxTiles').innerHTML = tilesHtml(snapshot, activeGroup === 'krw' ? krw : cross);
      root.querySelector('#fxGroupNote').textContent = activeGroup === 'krw'
        ? '하나은행 최신 고시 · 5분 간격 수집' : '시장 환율 · 달러지수는 FRED 공표 기준';
      root.querySelectorAll('[data-fx-group]').forEach((button) =>
        button.setAttribute('aria-pressed', String(button.dataset.fxGroup === activeGroup)));
    }
    refreshTiles();
    const panel = BMViews.bindComparisonPanel(root, 'fxHistory', snapshot, 'fx:' + (krw[0] || cross[0]));
    root.querySelector('#fxHistory').addEventListener('click', (event) => {
      const chip = event.target.closest('[data-fx-group]');
      if (!chip) return;
      activeGroup = chip.dataset.fxGroup;
      refreshTiles();
      panel?.syncSelection();
    });

  }

  return { render, digitsFor };
})();
