/* 공용 헬퍼.
 *
 * 빌드 시스템이 없어 classic <script defer> 전역 함수 방식이다(ES 모듈 아님).
 * index.html 의 script 순서가 곧 의존성 계약이고, 이 파일이 가장 먼저 온다.
 */

'use strict';

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** 금리·수익률 표기. 값이 없으면 대시. */
function fmtPct(value, digits) {
  if (value == null || !isFinite(value)) return '—';
  return value.toFixed(digits == null ? 2 : digits) + '%';
}

/** 환율처럼 자릿수가 통화마다 다른 값. */
function fmtNum(value, digits) {
  if (value == null || !isFinite(value)) return '—';
  return value.toLocaleString('ko-KR', {
    minimumFractionDigits: digits == null ? 2 : digits,
    maximumFractionDigits: digits == null ? 2 : digits,
  });
}

/** 발행 규모 — 조 단위가 넘는 숫자를 사람이 읽는 단위로. */
function fmtMoney(value) {
  if (value == null || !isFinite(value)) return '—';
  if (value >= 1e9) return '$' + (value / 1e9).toFixed(value >= 1e10 ? 0 : 1) + 'B';
  if (value >= 1e6) return '$' + Math.round(value / 1e6) + 'M';
  return '$' + Math.round(value).toLocaleString('en-US');
}

/** 전일대비 — 금리는 %p, 환율은 원 단위로 부호와 함께. */
function fmtChange(change, digits) {
  if (change == null || !isFinite(change) || change === 0) return '보합';
  const sign = change > 0 ? '+' : '−';
  return sign + Math.abs(change).toFixed(digits == null ? 3 : digits);
}

/** 상승/하락 색상 클래스. 금리는 상승이 붉은색(국내 관행). */
function changeClass(change) {
  if (change == null || !isFinite(change) || change === 0) return 'flat';
  return change > 0 ? 'up' : 'down';
}

/** 퍼센트포인트를 bp 로. 스프레드는 bp 로 읽는 게 관행이다. */
function toBp(percentPoints) {
  if (percentPoints == null || !isFinite(percentPoints)) return null;
  return Math.round(percentPoints * 100);
}

function fmtBp(value) {
  if (value == null || !isFinite(value)) return '—';
  return (value > 0 ? '+' : '') + Math.round(value) + 'bp';
}

/** '2026-08-28' → '8/28'. 차트 축과 좁은 칸에서 쓴다. */
function shortDate(iso) {
  if (!iso || iso.length < 10) return iso || '';
  return Number(iso.slice(5, 7)) + '/' + Number(iso.slice(8, 10));
}

function fmtDate(iso) {
  if (!iso || iso.length < 10) return iso || '';
  return iso.slice(0, 4) + '.' + iso.slice(5, 7) + '.' + iso.slice(8, 10);
}

/** ISO 타임스탬프를 '2026.08.29 08:15 (UTC)' 로. */
function fmtStamp(iso) {
  if (!iso) return '—';
  const parsed = new Date(iso);
  if (isNaN(parsed)) return iso;
  const pad = (n) => String(n).padStart(2, '0');
  return (
    parsed.getFullYear() + '.' + pad(parsed.getMonth() + 1) + '.' + pad(parsed.getDate()) +
    ' ' + pad(parsed.getHours()) + ':' + pad(parsed.getMinutes())
  );
}

/** 만기(년)를 축 라벨로. 0.25 → 3M, 10 → 10Y, -1 → 기준. */
function maturityLabel(maturity) {
  if (maturity == null) return '';
  if (maturity < 0) return '기준';
  if (maturity === 0) return 'O/N';
  if (maturity < 1) return Math.round(maturity * 12) + 'M';
  return maturity + 'Y';
}

/** 문자열 배열을 안전하게 이어 붙인 HTML. */
function html(strings) {
  return Array.isArray(strings) ? strings.join('') : String(strings || '');
}

/** CSS 변수 값을 읽는다. 차트가 테마 색을 쓰려면 필요하다. */
function cssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name);
  return (value || '').trim() || fallback;
}

/** 짧은 시간 안의 반복 호출을 마지막 한 번으로 모은다(리사이즈용). */
function debounce(fn, waitMs) {
  let timer = null;
  return function debounced() {
    const args = arguments;
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(null, args), waitMs == null ? 150 : waitMs);
  };
}

/** URL 쿼리 파라미터. 임베드 모드·초기 탭 결정에 쓴다. */
function queryParam(name) {
  return new URLSearchParams(location.search).get(name);
}
