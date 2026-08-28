/* 데이터 로딩·공유 상태.
 *
 * 스냅샷(current.json)은 항상 먼저 받고, 히스토리 파일은 **해당 탭을 열 때
 * 처음 한 번만** 받는다. 히스토리는 합쳐서 1.6MB 대라 첫 화면을 막으면 안 된다.
 *
 * 데이터 위치는 ?data= 로 바꿀 수 있다. value-invest 가 임베드할 때나 로컬에서
 * 다른 스냅샷을 붙여볼 때 쓴다.
 */

'use strict';

const BMStore = (function () {
  const state = {
    snapshot: null,
    history: {},          // {rates|fx|credit: 파싱된 payload}
    pending: {},          // 같은 파일을 두 번 받지 않도록 진행 중 Promise 보관
    error: null,
  };

  function dataBase() {
    const override = queryParam('data');
    if (override) return override.replace(/\/+$/, '');
    return 'data';
  }

  async function fetchJson(path) {
    const response = await fetch(dataBase() + '/' + path, { cache: 'no-cache' });
    if (!response.ok) throw new Error(path + ' — HTTP ' + response.status);
    return response.json();
  }

  async function loadSnapshot() {
    if (state.snapshot) return state.snapshot;
    state.snapshot = await fetchJson('current.json');
    return state.snapshot;
  }

  /** 히스토리 파일 하나를 지연 로딩한다. 같은 이름의 동시 호출은 합쳐진다. */
  function loadHistory(name) {
    if (state.history[name]) return Promise.resolve(state.history[name]);
    if (state.pending[name]) return state.pending[name];

    state.pending[name] = fetchJson(name + '.json')
      .then((payload) => {
        state.history[name] = payload;
        delete state.pending[name];
        return payload;
      })
      .catch((error) => {
        delete state.pending[name];
        throw error;
      });
    return state.pending[name];
  }

  /** 병렬 배열({d,v})을 차트가 쓰는 [[날짜, 값]] 로. */
  function toPoints(encoded) {
    if (!encoded || !encoded.d || !encoded.v) return [];
    const points = [];
    for (let i = 0; i < encoded.d.length; i += 1) {
      if (encoded.v[i] != null) points.push([encoded.d[i], encoded.v[i]]);
    }
    return points;
  }

  /** 기간 필터. '1y' | '5y' | 'max' */
  function withinRange(points, range) {
    if (!points.length || range === 'max') return points;
    const years = { '1y': 1, '3y': 3, '5y': 5, '10y': 10 }[range];
    if (!years) return points;
    const cutoff = new Date();
    cutoff.setFullYear(cutoff.getFullYear() - years);
    const iso = cutoff.toISOString().slice(0, 10);
    const from = points.findIndex((p) => p[0] >= iso);
    return from <= 0 ? points : points.slice(from);
  }

  function ratesSeries(seriesId) {
    return toPoints((state.history.rates?.series || {})[seriesId]);
  }

  function fxSeries(pair) {
    return toPoints((state.history.fx?.series || {})[pair]);
  }

  /** kind: 'yield' | 'oas' | 'kr_yield' */
  function creditSeries(kind, rating) {
    return toPoints((state.history.credit?.[kind] || {})[rating]);
  }

  return {
    state,
    loadSnapshot,
    loadHistory,
    toPoints,
    withinRange,
    ratesSeries,
    fxSeries,
    creditSeries,
    get snapshot() { return state.snapshot; },
  };
})();
