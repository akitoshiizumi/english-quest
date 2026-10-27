const {test} = require('node:test');
const assert = require('node:assert/strict');
const {sentenceClip} = require('../frontend/src/audio-clip.ts');

test('sentence clip uses exclusive timestamp end at sample boundary', async () => {
  const first = Float32Array.from({length: 40}, (_, index) => index < 15 ? 0.25 : -0.75);
  const buffer = {sampleRate: 10, length: first.length, numberOfChannels: 1, getChannelData: () => first};
  const bytes = new DataView(await sentenceClip(buffer, 0.2, 1.5).arrayBuffer());
  assert.equal(bytes.getUint32(24, true), 10);
  assert.equal(bytes.getUint32(40, true), 26);
  assert.equal(bytes.getInt16(44, true), 8191);
  assert.equal(bytes.getInt16(44 + 12 * 2, true), 8191);
  assert.equal(bytes.byteLength, 44 + 13 * 2);
  assert.throws(() => sentenceClip(buffer, 1.5, 1.5), /no audio samples/);
});
