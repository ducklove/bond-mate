const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function context() {
  const ctx = vm.createContext({ window: new EventTarget(), AbortController, Intl, Date,
    document: { documentElement: {} }, getComputedStyle: () => ({ getPropertyValue: () => '' }),
    queryParam: () => null });
  for (const file of ['util.js', 'store.js', 'views-common.js', 'views-fx.js']) {
    vm.runInContext(readFileSync(path.join(__dirname, '../static/js', file), 'utf8'), ctx);
  }
  return vm.runInContext('({ views: BMViews, store: BMStore })', ctx);
}

const entry = (key, points) => ({ target: { key, seriesId: key, kind: 'rates' }, points });
const plain = (value) => JSON.parse(JSON.stringify(value));

test('indexed comparison aligns the common interval and preserves each observation date', () => {
  const { views } = context();
  const entries = [
    entry('A', [['2024-01-01', 1], ['2024-02-01', 2], ['2024-03-01', 3], ['2024-04-01', 4]]),
    entry('B', [['2024-02-01', 1000], ['2024-03-01', 900]]),
  ];
  const result = views.comparisonSeries(entries, 'max', 'index');
  assert.deepEqual(plain(result.series[0].points), [['2024-02-01', 100], ['2024-03-01', 150]]);
  assert.deepEqual(plain(result.series[1].points), [['2024-02-01', 100], ['2024-03-01', 90]]);
  assert.equal(result.series[0].baseDate, '2024-02-01');
  assert.equal(entries[0].points[0][1], 1, 'source observations must stay intact');
});

test('indexed comparison handles disjoint dates, missing observations and nonpositive baselines', () => {
  const { views } = context();
  assert.match(views.comparisonSeries([
    entry('A', [['2024-01-01', 2]]), entry('B', [['2025-01-01', 3]]),
  ], 'max', 'index').error, /겹치는 기간/);
  assert.match(views.comparisonSeries([entry('A', []), entry('B', [['2025-01-01', 3]])], 'max', 'index').error, /관측값/);
  for (const baseline of [0, -1]) {
    assert.match(views.comparisonSeries([
      entry('A', [['2025-01-01', baseline]]), entry('B', [['2025-01-01', 3]]),
    ], 'max', 'index').error, /0 이하/);
  }
});

test('actual comparison supports negative interest rates and single surviving histories', () => {
  const { views } = context();
  const result = views.comparisonSeries([
    entry('A', [['2025-01-01', -0.5], ['2025-02-01', 0]]), entry('B', []),
  ], 'max', 'value');
  assert.equal(result.error, undefined);
  assert.deepEqual(plain(result.series[0].points), [['2025-01-01', -0.5], ['2025-02-01', 0]]);
});

test('a period with no observations does not fall back to the complete history', () => {
  const { store } = context();
  const points = [['1980-01-01', 1], ['1981-01-01', 2]];
  assert.deepEqual(plain(store.withinRange(points, '1y')), []);
  assert.deepEqual(plain(store.withinRange(points, 'max')), points);
});

test('catalog separates government maturities from policy rates and keeps FX precision and units', () => {
  const { views } = context();
  const catalog = views.comparisonCatalog({ countries: { KR: { name: '한국' } },
    curves: { KR: [
      { series_id: 'KR_BASE', maturity: -1, tenor: '기준금리' },
      { series_id: 'KR_ON', maturity: 0, tenor: '익일물' },
      { series_id: 'KR10Y', maturity: 10, tenor: '10년' },
    ] }, rates: { KR_BASE: { value: 3 }, KR_ON: { value: 3.1 }, KR10Y: { value: 3.2 } },
    fx: { EUR_USD: { label: '유로/달러', value: 1.1234 }, USD_KRW: { value: 1400 }, USD_IDX: { value: 120 } },
  });
  assert.equal(catalog.filter((s) => s.group.startsWith('국채')).length, 1);
  assert.equal(new Set(catalog.map((s) => s.key)).size, catalog.length);
  assert.equal(catalog.find((s) => s.key === 'fx:EUR_USD').digits, 4);
  assert.equal(catalog.find((s) => s.key === 'fx:EUR_USD').unit, '달러');
  assert.equal(catalog.find((s) => s.key === 'fx:USD_KRW').unit, '원');
  assert.equal(catalog.find((s) => s.key === 'fx:USD_IDX').unit, 'pt');
});
