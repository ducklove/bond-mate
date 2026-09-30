// app.js 의 Value Compass 연동 행위 — 테마 토글, vc:themechange 재렌더, iframe 메시지.
// jsdom 없이 vm 과 최소한의 가짜 DOM 으로 돌린다(빌드·npm 의존성 없음).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const script = (name) => readFileSync(path.join(__dirname, '../static/js', name), 'utf8');
const HUB = 'https://ducklove.duckdns.org:3691';

function element(extra) {
  const el = new EventTarget();
  Object.assign(el, {
    innerHTML: '',
    textContent: '',
    title: '',
    dataset: {},
    attrs: {},
    classList: { names: new Set(), add(n) { this.names.add(n); }, contains(n) { return this.names.has(n); } },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    removeAttribute(k) { delete this.attrs[k]; },
    querySelector: () => null,
    querySelectorAll: () => [],
  }, extra);
  return el;
}

/** app.js 를 가짜 브라우저에 올린다. 반환값으로 상태를 들여다본다. */
function boot({ search = '', framed = false, ancestors = [HUB], shell = null, stored = {}, referrer = '' } = {}) {
  const storage = new Map(Object.entries(stored));
  const posted = [];
  const renders = [];
  const nodes = {
    app: element(),
    tabs: element(),
    generatedAt: element(),
    sourceList: element(),
    themeToggle: element(),
  };
  const documentElement = element();
  documentElement.setAttribute('data-theme', 'light');     // theme-boot 가 이미 칠했다
  const document = Object.assign(new EventTarget(), {
    hidden: false,
    referrer,
    documentElement,
    body: element({ scrollHeight: 777 }),
    getElementById: (id) => nodes[id] || null,
  });
  const window = new EventTarget();
  // vm 안에서 만든 객체는 프로토타입이 달라 JSON 으로 옮겨 비교한다.
  const parent = framed
    ? { postMessage: (message, origin) => posted.push({ message: JSON.parse(JSON.stringify(message)), origin }) }
    : window;
  Object.assign(window, {
    parent,
    location: { search, href: 'https://ducklove.github.io/bond-mate/' + search, ancestorOrigins: framed ? ancestors : [] },
    matchMedia: () => ({ matches: false }),
    VCShell: shell,
  });
  const snapshot = { generated_at: '2026-09-30T00:00:00Z', updated_at: {}, sources: {} };
  const ctx = vm.createContext({
    window, document, location: window.location, URL, URLSearchParams, CustomEvent, Intl,
    console, Date,
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, String(v)),
      removeItem: (k) => storage.delete(k),
    },
    history: { replaceState: () => {} },
    setInterval: () => 0,
    setTimeout: (fn) => fn(),
    clearTimeout: () => {},
    ResizeObserver: class { observe() {} },
    BMStore: { snapshot: null, loadSnapshot: async () => { ctx.BMStore.snapshot = snapshot; return snapshot; } },
    BMViews: { beginRender: () => {} },
    BMRates: {
      renderOverview: () => renders.push('overview'),
      renderGovernment: () => renders.push('government'),
      renderPolicy: () => renders.push('policy'),
    },
    BMFx: { render: () => renders.push('fx') },
    BMCredit: { render: () => renders.push('credit') },
    BMIssuance: { render: () => renders.push('issuance') },
  });
  vm.runInContext(script('util.js') + script('app.js'), ctx);
  document.dispatchEvent(new Event('DOMContentLoaded'));
  return { ctx, window, document, storage, posted, renders, nodes };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

test('embed in the hub sends vc:ready and vc:height to the hub origin, legacy height to *', async () => {
  const env = boot({ search: '?embed=credit', framed: true });
  await settle();
  const types = env.posted.map(({ message }) => message.type);
  assert.deepEqual(types, ['vc:ready', 'height', 'vc:height']);
  const [ready, legacy, height] = env.posted;
  assert.equal(ready.origin, HUB);
  assert.deepEqual(ready.message, { source: 'vc', type: 'vc:ready', tool: 'bond-mate' });
  assert.equal(legacy.origin, '*');
  assert.deepEqual(legacy.message, { source: 'bond-mate', type: 'height', height: 777 });
  assert.equal(height.origin, HUB);
  assert.deepEqual(height.message, { source: 'vc', type: 'vc:height', tool: 'bond-mate', height: 777 });
  assert.deepEqual(env.renders, ['credit']);
});

test('vc:* messages are not sent to a non-hub embedder, the legacy one still is', async () => {
  const env = boot({ search: '?embed=fx', framed: true, ancestors: ['https://example.com'] });
  await settle();
  assert.deepEqual(env.posted.map(({ message }) => message.type), ['height']);
});

test('hub vc:theme message applies the theme without reload when the shell is absent', async () => {
  const env = boot({ search: '?embed=overview', framed: true });
  await settle();
  const before = env.renders.length;
  env.window.dispatchEvent(Object.assign(new Event('message'), {
    origin: 'https://evil.example', data: { source: 'vc', type: 'vc:theme', theme: 'dark' },
  }));
  assert.equal(env.document.documentElement.getAttribute('data-theme'), 'light');
  env.window.dispatchEvent(Object.assign(new Event('message'), {
    origin: HUB, data: { source: 'vc', type: 'vc:theme', theme: 'dark' },
  }));
  assert.equal(env.document.documentElement.getAttribute('data-theme'), 'dark');
  assert.equal(env.renders.length, before + 1, 'charts redraw once for the new CSS variables');
  assert.equal(env.storage.has('theme'), false, 'a pushed theme is not persisted');
});

test('toggle goes through VCShell.setTheme with the 3-state cycle on the shared key', async () => {
  const calls = [];
  const env = boot({ shell: { setTheme: (t) => calls.push(t) }, stored: { 'bondmate.theme': 'dark', theme: 'dark' } });
  await settle();
  assert.equal(env.storage.has('bondmate.theme'), false, 'migrated legacy key is removed');
  env.nodes.themeToggle.dispatchEvent(new Event('click'));
  assert.deepEqual(calls, ['light']);
  env.storage.set('theme', 'light');
  env.nodes.themeToggle.dispatchEvent(new Event('click'));
  env.storage.delete('theme');
  env.nodes.themeToggle.dispatchEvent(new Event('click'));
  assert.deepEqual(calls, ['light', 'auto', 'dark']);
});

test('fallback toggle writes the shared theme key and auto removes it', async () => {
  const env = boot();
  await settle();
  env.nodes.themeToggle.dispatchEvent(new Event('click'));
  assert.equal(env.storage.get('theme'), 'dark');
  assert.equal(env.document.documentElement.getAttribute('data-theme'), 'dark');
  env.nodes.themeToggle.dispatchEvent(new Event('click'));
  assert.equal(env.storage.get('theme'), 'light');
  env.nodes.themeToggle.dispatchEvent(new Event('click'));
  assert.equal(env.storage.has('theme'), false);
  assert.equal(env.document.documentElement.getAttribute('data-theme'), 'light'); // 시스템 = light
  assert.equal(env.storage.has('bondmate.theme'), false);
});

test('vc:themechange from the shell redraws the active tab', async () => {
  const env = boot({ search: '?tab=policy' });
  await settle();
  assert.deepEqual(env.renders, ['policy']);
  env.document.dispatchEvent(new CustomEvent('vc:themechange', { detail: { theme: 'dark' } }));
  assert.deepEqual(env.renders, ['policy', 'policy']);
});

test('credit tab label matches the hub registry view label', async () => {
  const env = boot();
  await settle();
  assert.match(env.nodes.tabs.innerHTML, /data-tab="credit"[^>]*>신용</);
  assert.doesNotMatch(env.nodes.tabs.innerHTML, /사채/);
});

test('stamp shows the last-change times and flags delay from checked_at', async () => {
  const env = boot();
  await settle();
  const recent = new Date(Date.now() - 5 * 60 * 1000).toISOString();
  env.ctx.BMStore.snapshot.generated_at = '2026-09-01T00:00:00Z';
  env.ctx.BMStore.loadSnapshot = async () => ({
    generated_at: '2026-09-01T00:00:00Z', checked_at: recent,
    updated_at: { fx: '2026-09-01T00:00:00Z', rates: '2026-09-01T00:00:00Z' }, sources: {},
  });
  env.document.dispatchEvent(new Event('visibilitychange'));
  await settle();
  assert.match(env.nodes.generatedAt.textContent, /환율 갱신 .* · 금리 갱신 .* · 확인 /);
  assert.doesNotMatch(env.nodes.generatedAt.textContent, /수집 지연/);
});
