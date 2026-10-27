const test = require('node:test');
const assert = require('node:assert/strict');
const keys = require('../english_overlap/static/shortcuts.js');

function fakeDocument() {
  const listeners = {};
  return {
    activeElement: { tagName: 'BODY' },
    defaultView: { addEventListener() {}, removeEventListener() {} },
    addEventListener(name, callback) { listeners[name] = callback; },
    removeEventListener(name) { delete listeners[name]; },
    fire(name, event) {
      let prevented = false;
      listeners[name]?.({ preventDefault() { prevented = true; }, ...event });
      return prevented;
    }
  };
}

test('A/U and S/I map to state-specific actions without conflicting', () => {
  assert.deepEqual(keys.validateBindings(keys.DEFAULT_BINDINGS), []);
  for (const key of ['a', 'u', 's', 'i']) assert.equal(keys.resolveAction(key, 'question', keys.DEFAULT_BINDINGS), 'reveal_answer');
  for (const key of ['a', 'u']) assert.equal(keys.resolveAction(key, 'answer', keys.DEFAULT_BINDINGS), 'rate_again');
  for (const key of ['s', 'i']) assert.equal(keys.resolveAction(key, 'answer', keys.DEFAULT_BINDINGS), 'rate_known');
});

test('same-state conflicts are rejected while cross-state reuse is allowed', () => {
  const bad = { ...keys.DEFAULT_BINDINGS, rate_known: ['a', 'i'] };
  assert.deepEqual(keys.validateBindings(bad), [{ key: 'a', actions: ['rate_again', 'rate_known'] }]);
  assert.throws(() => keys.attach({ documentRef: fakeDocument(), getPhase: () => 'question', actions: {}, bindings: bad }), /conflict/);
});

test('dispatcher ignores repeat, modifiers, composition, and editable targets', () => {
  const doc = fakeDocument();
  let phase = 'question';
  const calls = [];
  const detach = keys.attach({ documentRef: doc, getPhase: () => phase, actions: {
    reveal_answer: () => { calls.push('reveal'); phase = 'answer'; },
    rate_again: () => calls.push('again'), rate_known: () => calls.push('known')
  } });
  assert.equal(doc.fire('keydown', { key: 'A', repeat: false }), true);
  assert.deepEqual(calls, ['reveal']);
  assert.equal(doc.fire('keydown', { key: 'a', repeat: true }), false);
  doc.fire('keyup', { key: 'a' });
  doc.activeElement = { tagName: 'INPUT' };
  assert.equal(doc.fire('keydown', { key: 'u' }), false);
  doc.activeElement = { tagName: 'BODY' };
  assert.equal(doc.fire('keydown', { key: 's', ctrlKey: true }), false);
  assert.equal(doc.fire('keydown', { key: 'i', isComposing: true }), false);
  assert.deepEqual(calls, ['reveal']);
  detach();
  doc.fire('keyup', { key: 'a' });
});
