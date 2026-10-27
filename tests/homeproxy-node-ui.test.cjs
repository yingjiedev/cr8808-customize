const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');

function load(start, status) {
  const calls = [], notifications = [];
  const context = vm.createContext({
    rpc: { declare(spec) { return (...args) => {
      calls.push([spec.method, ...args]);
      return spec.method === 'node_test_start' ? start(...args) : status(...args);
    }; } },
    ui: { addNotification(_title, message) { notifications.push(message); } },
    E(_tag, message) { return message; },
    window: { setTimeout(fn) { return setTimeout(fn, 0); }, clearTimeout },
    Date, Promise, Error, String
  });
  vm.runInContext(fs.readFileSync('scripts/homeproxy-low-memory/ui.js', 'utf8'), context);
  return { run: context.cr8808TestNode, calls, notifications };
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
