const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = (name) => readFileSync(path.join(__dirname, '../static/js', name), 'utf8');

function store(fetcher) {
  const ctx = vm.createContext({ fetch: fetcher, queryParam: () => null });
  vm.runInContext(script('store.js') + '\nthis.store = BMStore;', ctx);
  return ctx.store;
}
const response = (data) => ({ ok: true, json: async () => data });

test('forced refresh replaces snapshot, invalidates history, bypasses cached responses', async () => {
  let revision = 'first';
  const calls = [];
  const s = store(async (url, options) => {
    calls.push({ url, options });
    return response({ generated_at: revision });
  });
  await s.loadSnapshot();
  await s.loadHistory('fx');
  revision = 'second';
  assert.equal((await s.loadSnapshot()).generated_at, 'first');
  assert.equal((await s.loadSnapshot(true)).generated_at, 'second');
  assert.equal(s.state.history.fx, undefined);
  assert.ok(calls.every(({ url, options }) => url.includes('?v=') && options.cache === 'no-store'));
});

test('failed refresh retains usable snapshot and allows retry', async () => {
  let fail = false;
  const s = store(async () => {
    if (fail) throw new Error('offline');
    return response({ generated_at: 'first' });
  });
  await s.loadSnapshot();
  fail = true;
  await assert.rejects(s.loadSnapshot(true), /offline/);
  assert.equal(s.snapshot.generated_at, 'first');
  fail = false;
  assert.equal((await s.loadSnapshot(true)).generated_at, 'first');
});

test('outdated history request cannot overwrite new snapshot history', async () => {
  let release;
  let revision = 'first';
  const s = store(async (url) => url.includes('fx.json')
    ? new Promise(resolve => { release = resolve; }) : response({ generated_at: revision }));
  await s.loadSnapshot();
  const pending = s.loadHistory('fx');
  revision = 'second';
  await s.loadSnapshot(true);
  release(response({ generated_at: 'first' }));
  await pending;
  assert.equal(s.state.history.fx, undefined);
});

test('repeated renders discard old resize listeners and retain bp/FX formatting', () => {
  const window = new EventTarget();
  const ctx = vm.createContext({ window, AbortController, Intl,
    setTimeout: (fn) => fn(), clearTimeout: () => {} });
  vm.runInContext(script('util.js') + script('views-common.js') + '\nthis.views = BMViews;', ctx);
  let calls = 0;
  ctx.views.onResize(() => calls++);
  ctx.views.beginRender();
  ctx.views.onResize(() => calls++);
  window.dispatchEvent(new Event('resize'));
  assert.equal(calls, 1);
  assert.match(ctx.views.tileHtml({ change: 0.025 }), /\+2\.5bp/);
  assert.match(ctx.views.tileHtml({ unit: '', change: 1.1, changeDigits: 2 }), /\+1\.10/);
  assert.match(ctx.fmtQuoteDate({ as_of: '2026-09-28T16:31:00-04:00' }), /05:31 KST/);
});
