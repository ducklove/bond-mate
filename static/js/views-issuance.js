/* 사채 발행 화면 — 대형 발행사의 채권 발행과 조달금리.
 *
 * 여기 숫자는 SEC 공시(FWP pricing term sheet)에서 그대로 온 것이다.
 * 시장 호가가 아니라 **발행 시점에 그 회사가 실제로 확정한 조달 조건**이라
 * 회사 간 신용도 차이가 같은 만기·같은 날짜 기준으로 비교된다.
 */

'use strict';

const BMIssuance = (function () {
  let filterIssuer = '';

  function issuerName(snapshot, ticker) {
    return snapshot.issuers?.[ticker]?.name_ko || ticker;
  }

  /** 발행 규모 상위 발행사 요약 — 누가 얼마나 조달했는지. */
  function summaryHtml(snapshot) {
    const totals = new Map();
    (snapshot.offerings || []).forEach((offering) => {
      const current = totals.get(offering.issuer) || { amount: 0, deals: 0 };
      current.amount += offering.total_amount || 0;
      current.deals += 1;
      totals.set(offering.issuer, current);
    });

    const rows = [...totals.entries()]
      .sort((a, b) => b[1].amount - a[1].amount)
      .map(([ticker, stat]) =>
        '<tr><td class="text">' + escapeHtml(issuerName(snapshot, ticker)) +
        ' <span style="color:var(--text-faint)">' + escapeHtml(ticker) + '</span></td>' +
        '<td class="num">' + escapeHtml(fmtMoney(stat.amount)) + '</td>' +
        '<td class="num">' + stat.deals + '</td></tr>'
      ).join('');

    return '<div class="card"><div class="table-wrap"><table class="data"><thead><tr>' +
      '<th class="text">발행사</th><th>수집 구간 합계</th><th>건수</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table></div></div>';
  }

  /** 같은 만기대의 조달금리를 발행사끼리 비교 — 신용도 차이가 바로 보인다. */
  function comparisonHtml(snapshot) {
    const rows = [];
    (snapshot.offerings || []).forEach((offering) => {
      (offering.tranches || []).forEach((tranche) => {
        if (tranche.spread_bp == null || tranche.yield_to_maturity_pct == null) return;
        const years = tranche.maturity_year - Number(offering.filing_date.slice(0, 4));
        if (years < 8 || years > 12) return;      // 10년물 언저리로 한정
        rows.push({ offering, tranche });
      });
    });
    rows.sort((a, b) => a.tranche.spread_bp - b.tranche.spread_bp);

    if (!rows.length) return '';

    const body = rows.slice(0, 14).map(({ offering, tranche }) =>
      '<tr>' +
      '<td class="text">' + escapeHtml(issuerName(snapshot, offering.issuer)) + '</td>' +
      '<td class="text" style="color:var(--text-faint)">' + escapeHtml(fmtDate(offering.filing_date)) + '</td>' +
      '<td class="num">' + escapeHtml(fmtMoney(tranche.principal_amount)) + '</td>' +
      '<td class="num">' + escapeHtml(fmtPct(tranche.coupon_pct, 3)) + '</td>' +
      '<td class="num">' + escapeHtml(fmtPct(tranche.yield_to_maturity_pct, 3)) + '</td>' +
      '<td class="num">' + escapeHtml(fmtBp(tranche.spread_bp)) + '</td>' +
      '<td class="text" style="color:var(--text-faint);max-width:230px;overflow:hidden;text-overflow:ellipsis">' +
      escapeHtml(tranche.ratings || '—') + '</td>' +
      '</tr>'
    ).join('');

    return '<div class="card"><div class="table-wrap"><table class="data"><thead><tr>' +
      '<th class="text">발행사</th><th class="text">발행일</th><th>규모</th>' +
      '<th>표면금리</th><th>조달금리(YTM)</th><th>국채 대비</th><th class="text">신용등급</th>' +
      '</tr></thead><tbody>' + body + '</tbody></table></div></div>';
  }

  function trancheTableHtml(offering) {
    const body = (offering.tranches || []).map((tranche) => {
      const coupon = tranche.floating
        ? '<span style="color:var(--text-faint)">변동' +
          (tranche.floating_spread_pct != null ? ' +' + tranche.floating_spread_pct.toFixed(2) + '%p' : '') + '</span>'
        : escapeHtml(fmtPct(tranche.coupon_pct, 3));
      return '<tr>' +
        '<td class="text">' + escapeHtml(tranche.security) + '</td>' +
        '<td class="num">' + escapeHtml(fmtMoney(tranche.principal_amount)) + '</td>' +
        '<td class="num">' + coupon + '</td>' +
        '<td class="num">' + escapeHtml(fmtPct(tranche.yield_to_maturity_pct, 3)) + '</td>' +
        '<td class="num">' + escapeHtml(fmtBp(tranche.spread_bp)) + '</td>' +
        '<td class="num">' + escapeHtml(tranche.price_to_public != null ? tranche.price_to_public.toFixed(3) : '—') + '</td>' +
        '<td class="text" style="color:var(--text-faint)">' + escapeHtml(tranche.maturity_date || tranche.maturity_year) + '</td>' +
        '</tr>';
    }).join('');

    return '<div class="table-wrap"><table class="data"><thead><tr>' +
      '<th class="text">종목</th><th>규모</th><th>표면금리</th><th>조달금리</th>' +
      '<th>국채 대비</th><th>발행가</th><th class="text">만기</th>' +
      '</tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  function offeringsHtml(snapshot) {
    const list = (snapshot.offerings || []).filter((o) => !filterIssuer || o.issuer === filterIssuer);
    if (!list.length) return '<div class="empty">표시할 발행 건이 없습니다.</div>';

    return list.map((offering, index) =>
      '<div class="offering" data-open="' + (index === 0 ? 'true' : 'false') + '">' +
      '<button class="offering-head" type="button">' +
      '<span class="caret">▶</span>' +
      '<span class="offering-issuer">' + escapeHtml(issuerName(snapshot, offering.issuer)) + '</span>' +
      '<span class="offering-meta">' + escapeHtml(fmtDate(offering.filing_date)) + ' · ' +
      escapeHtml(offering.form) + ' · ' + (offering.tranches || []).length + '개 트랜치</span>' +
      '<span class="offering-amount">' + escapeHtml(fmtMoney(offering.total_amount)) + '</span>' +
      '</button>' +
      '<div class="offering-body">' + trancheTableHtml(offering) +
      '<div style="padding:8px 14px;font-size:12px">' +
      '<a href="' + escapeHtml(offering.url) + '" target="_blank" rel="noopener">SEC 원문 공시 보기 ↗</a>' +
      '</div></div></div>'
    ).join('');
  }

  function render(root, snapshot) {
    const issuers = [...new Set((snapshot.offerings || []).map((o) => o.issuer))];

    root.innerHTML =
      BMViews.sectionHtml(
        '발행사별 조달 규모',
        '수집된 최근 공시 기준',
        summaryHtml(snapshot)
      ) +
      BMViews.sectionHtml(
        '10년물 언저리 조달금리 비교',
        '국채 대비 스프레드가 좁은 순 — 신용도가 좋을수록 싸게 조달한다',
        comparisonHtml(snapshot)
      ) +
      BMViews.sectionHtml(
        '발행 이력',
        '누르면 트랜치별 조건이 펼쳐집니다',
        '<div id="isList">' + offeringsHtml(snapshot) + '</div>',
        '<span class="chip-row" id="isFilter">' +
        '<button class="chip" type="button" data-issuer="" aria-pressed="true">전체</button>' +
        issuers.map((ticker) =>
          '<button class="chip" type="button" data-issuer="' + escapeHtml(ticker) + '" aria-pressed="false">' +
          escapeHtml(issuerName(snapshot, ticker)) + '</button>'
        ).join('') + '</span>'
      ) +
      BMViews.embedNoteHtml('issuance');

    root.querySelector('#isFilter').addEventListener('click', (event) => {
      const chip = event.target.closest('.chip[data-issuer]');
      if (!chip) return;
      filterIssuer = chip.dataset.issuer;
      root.querySelectorAll('#isFilter .chip').forEach((c) =>
        c.setAttribute('aria-pressed', c === chip ? 'true' : 'false'));
      root.querySelector('#isList').innerHTML = offeringsHtml(snapshot);
    });

    root.querySelector('#isList').addEventListener('click', (event) => {
      const head = event.target.closest('.offering-head');
      if (!head) return;
      const card = head.parentElement;
      card.dataset.open = card.dataset.open === 'true' ? 'false' : 'true';
    });
  }

  return { render };
})();
