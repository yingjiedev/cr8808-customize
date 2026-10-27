const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');

function load(start, status, nodes = {}) {
  const calls = [], notifications = [], delays = [], pageEvents = {};
  const context = vm.createContext({
    rpc: { declare(spec) { return (...args) => {
      calls.push([spec.method, ...args]);
      return spec.method === 'node_test_start' ? start(...args) : status(...args);
    }; } },
    ui: { addNotification(_title, message) { notifications.push(message); } },
    uci: { get(_config, id, key) { return nodes[id]?.[key]; } },
    E(tag, attributes, children) {
      if (typeof attributes === 'string' && children === undefined) return attributes;
      return { tag, attributes, children, disabled: !!attributes?.disabled,
        textContent: typeof children === 'string' ? children : '', events: {},
        addEventListener(type, callback) { this.events[type] = callback; } };
    },
    window: { setTimeout(fn, ms) { delays.push(ms); return setTimeout(fn, 0); }, clearTimeout,
      addEventListener(type, callback) { pageEvents[type] = callback; } },
    Date, Promise, Error, String
  });
  vm.runInContext(fs.readFileSync('scripts/homeproxy-low-memory/ui.js', 'utf8'), context);
  return { run: context.cr8808TestNode, runQueue: context.cr8808RunQueue,
    stop: context.cr8808StopQueue, collect: context.cr8808CollectNodes, tools: context.cr8808NodeTools,
    calls, notifications, delays, pageEvents };
}

test('opening the node page does not initiate any test or polling', () => {
  const page = load(() => assert.fail('unexpected start'), () => assert.fail('unexpected poll'));
  assert.equal(page.calls.length, 0);
});

test('only one clicked node runs and a successful result updates that button', async () => {
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const page = load(() => pending, () => Promise.resolve({ status: 'success', delay: 321 }));
  const first = { textContent: '测试延迟', disabled: false };
  const second = { textContent: '测试延迟', disabled: false };
  const running = page.run({ currentTarget: first }, 'node_a');
  assert.equal(first.disabled, true);
  await page.run({ currentTarget: second }, 'node_b');
  assert.equal(page.calls.filter(c => c[0] === 'node_test_start').length, 1);
  release({ id: 'test_job' });
  await running;
  assert.equal(first.textContent, '321 ms · 重测');
  assert.equal(first.disabled, false);
  assert.equal(second.textContent, '测试延迟');
});

test('low memory rejects the test without polling and releases the page gate', async () => {
  const page = load(() => Promise.resolve({ error: 'low_memory' }), () => assert.fail('unexpected poll'));
  const button = { textContent: '测试延迟', disabled: false };
  await page.run({ currentTarget: button }, 'node_a');
  assert.match(page.notifications[0], /10 MiB/);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, '测试延迟');
  await page.run({ currentTarget: button }, 'node_a');
  assert.equal(page.calls.length, 2);
});

test('one failed sample is shown as this test failing and can be retried', async () => {
  const page = load(() => Promise.resolve({ id: 'test_job' }), () => Promise.resolve({ status: 'failed' }));
  const button = { textContent: '测试延迟', disabled: false };
  await page.run({ currentTarget: button }, 'node_a');
  assert.equal(button.textContent, '本次未通过 · 重测');
  assert.equal(button.disabled, false);
});

function entries(...ids) {
  return ids.map(id => ({ id, label: id, button: { textContent: '测试延迟', disabled: false } }));
}
function controls() {
  return { start: { disabled: false }, stop: { disabled: true }, status: { textContent: '' } };
}

test('test-all runs one probe at a time, waits one second between nodes, and aggregates results', async () => {
  let active = 0, maximum = 0;
  const page = load(id => {
    maximum = Math.max(maximum, ++active);
    return Promise.resolve({ id });
  }, id => { active--; return Promise.resolve(id === 'b' ? { status: 'failed' } : { status: 'success', delay: 400 }); });
  const items = entries('a', 'b', 'c'), bar = controls();
  const result = await page.runQueue(items, bar, () => true);
  assert.equal(maximum, 1);
  assert.equal(result.done, 3);
  assert.equal(result.success, 2);
  assert.equal(result.failed, 1);
  assert.deepEqual(page.delays, [700, 1000, 700, 1000, 700]);
  assert.match(bar.status.textContent, /已完成 3\/3/);
  assert.equal(bar.start.disabled, false);
  assert.equal(bar.stop.disabled, true);
});

test('stop waits for the current result and never starts the next queued node', async () => {
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const page = load(() => pending, () => Promise.resolve({ status: 'success', delay: 400 }));
  const bar = controls(), items = entries('a', 'b', 'c');
  const task = page.runQueue(items, bar, () => true);
  page.stop();
  assert.match(bar.status.textContent, /当前节点测完/);
  release({ id: 'a' });
  const result = await task;
  assert.equal(result.done, 1);
  assert.match(bar.status.textContent, /已停止 1\/3.*未测 2/);
  assert.equal(page.calls.filter(c => c[0] === 'node_test_start').length, 1);
  assert.equal(items[1].button.textContent, '测试延迟');
});

test('low memory aborts the rest of the queue without labelling untested nodes as failed', async () => {
  const page = load(id => Promise.resolve(id === 'b' ? { error: 'low_memory' } : { id }),
    () => Promise.resolve({ status: 'success', delay: 400 }));
  const bar = controls(), result = await page.runQueue(entries('a', 'b', 'c'), bar, () => true);
  assert.equal(result.done, 1);
  assert.equal(result.failed, 0);
  assert.match(bar.status.textContent, /已中止 1\/3.*未测 2.*10 MiB/);
  assert.equal(page.calls.filter(c => c[0] === 'node_test_start').length, 2);
});

test('a node needing apply is skipped while the remaining queue still runs', async () => {
  const page = load(id => Promise.resolve(id === 'a' ? { error: 'apply_first' } : { id }),
    () => Promise.resolve({ status: 'success', delay: 400 }));
  const items = entries('a', 'b'), bar = controls();
  const result = await page.runQueue(items, bar, () => true);
  assert.equal(result.skipped, 1);
  assert.equal(result.success, 1);
  assert.equal(result.failed, 0);
  assert.equal(items[0].button.textContent, '需先保存应用');
});

test('leaving the rendered page stops the remaining queue', async () => {
  let connected = true;
  const page = load(id => Promise.resolve({ id }), () => {
    connected = false;
    return Promise.resolve({ status: 'success', delay: 400 });
  });
  const bar = controls();
  await page.runQueue(entries('a', 'b'), bar, () => connected);
  assert.equal(page.calls.filter(c => c[0] === 'node_test_start').length, 1);
  assert.match(bar.status.textContent, /已停止 1\/2/);
});

test('expired results and busy responses stop the queue as infrastructure errors', async () => {
  for (const mode of ['busy', 'expired']) {
    const page = load(id => Promise.resolve(mode === 'busy' ? { error: 'busy' } : { id }),
      () => Promise.resolve({ status: 'failed', error: 'expired' }));
    const bar = controls(), result = await page.runQueue(entries('a', 'b'), bar, () => true);
    assert.equal(result.done, 0);
    assert.equal(result.failed, 0);
    assert.match(bar.status.textContent, /已中止 0\/2.*未测 2/);
  }
});

test('collector includes hidden subscription tabs, deduplicates fields, and skips unsupported types', () => {
  const page = load(() => assert.fail('unexpected request'), () => assert.fail('unexpected poll'),
    { a: { type: 'vless', label: 'A' }, b: { type: 'hysteria2', label: 'B' }, c: { type: 'http' } });
  const root = { querySelectorAll: () => ['a', 'b', 'a', 'c'].map(id => ({
    getAttribute: () => 'cbid.homeproxy.' + id + '._cr8808_latency', querySelector: () => ({})
  })) };
  assert.deepEqual(Array.from(page.collect(root), item => item.id), ['a', 'b']);
  assert.equal(page.calls.length, 0);
});

test('toolbar rendering sends no request; the test-all button starts the collected queue', async () => {
  const page = load(id => Promise.resolve({ id }), () => Promise.resolve({ status: 'success', delay: 400 }),
    { a: { type: 'vless', label: 'A' } });
  const root = { isConnected: true, firstChild: null,
    querySelector: () => null,
    querySelectorAll: () => [{ getAttribute: () => 'cbid.homeproxy.a._cr8808_latency', querySelector: () => ({ textContent: '测试延迟' }) }],
    insertBefore(node) { this.toolbar = node; } };
  assert.equal(page.tools(root), root);
  assert.equal(page.calls.length, 0);
  const [start, stop, status] = root.toolbar.children[0].children;
  assert.equal(stop.disabled, true);
  await start.events.click();
  assert.match(status.textContent, /已完成 1\/1/);
  assert.equal(page.calls.filter(c => c[0] === 'node_test_start').length, 1);
  assert.equal(typeof page.pageEvents.pagehide, 'function');
});
