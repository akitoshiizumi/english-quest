const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const {splitEnglishSentences,abbreviationContinues}=require('../frontend/src/sentences.ts');
const {SentenceCompletionTracker}=require('../frontend/src/sentence-completion.ts');

test('sentence boundaries preserve abbreviations, initials, decimals, and quoted endings',()=>{
  for(const fixture of JSON.parse(readFileSync('tests/fixtures/sentences.json','utf8'))){
    assert.deepEqual(splitEnglishSentences(fixture.text),fixture.sentences,fixture.text);
  }
  assert.equal(abbreviationContinues('The U.S.','government works.'),true);
  assert.equal(abbreviationContinues('They live in the U.S.','The next day was sunny.'),false);
});

test('sentence completion needs playback coverage, ignores duplicates and permits full replays',()=>{
  const completed=[];
  const tracker=new SentenceCompletionTracker(index=>completed.push(index));
  tracker.ranges=[{start:0,end:1},{start:1.2,end:2.2}];
  tracker.resume(0);
  tracker.advance(.5);tracker.pause();tracker.resume(.5);tracker.advance(1);
  tracker.advance(1);tracker.advance(1.25);
  assert.deepEqual(completed,[0]);
  tracker.advance(1.75);tracker.advance(2.2);
  assert.deepEqual(completed,[0,1]);
  tracker.reset();tracker.resume(.95);tracker.advance(1);
  assert.deepEqual(completed,[0,1],'seeking to the end must not count');
  tracker.reset();tracker.resume(0);tracker.advance(.5);tracker.advance(1);
  assert.deepEqual(completed,[0,1,0],'replaying the complete sentence earns damage');
  tracker.reset();tracker.resume(0);tracker.advance(10);
  assert.deepEqual(completed,[0,1,0],'a discontinuous position jump is not playback');
});
