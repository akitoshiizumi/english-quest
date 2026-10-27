const assert=require('node:assert/strict');
const test=require('node:test');
const {buildVocabularyDistribution}=require('../english_overlap/static/statistics_distribution.js');

test('accuracy distribution uses ten bounded bins and excludes unstudied vocabulary',()=>{
  const result=buildVocabularyDistribution([
    {attempts:1,known_rate:0},{attempts:10,known_rate:.099},{attempts:10,known_rate:.1},
    {attempts:100,known_rate:.999},{attempts:1,known_rate:1},{attempts:0,known_rate:null},
    {attempts:0,known_rate:0}
  ],'accuracy');
  assert.equal(result.label,'自己評価正解率');
  assert.equal(result.total,5);
  assert.equal(result.excludedUnstudied,2);
  assert.deepEqual(result.bins.map(bin=>bin.label),['0–9%','10–19%','20–29%','30–39%','40–49%','50–59%','60–69%','70–79%','80–89%','90–100%']);
  assert.deepEqual(result.bins.map(bin=>bin.count),[2,1,0,0,0,0,0,0,0,2]);
});

test('count distributions include unseen words at zero and group larger counts',()=>{
  const rows=[0,1,2,3,4,5,6,10,11,20,21].map(value=>({attempts:value,known:value,again:value}));
  for(const metric of ['attempts','known','again']){
    const result=buildVocabularyDistribution(rows,metric);
    assert.equal(result.total,11);
    assert.equal(result.excludedUnstudied,0);
    assert.deepEqual(result.bins.map(bin=>bin.label),['0','1','2','3','4','5','6–10','11–20','21+']);
    assert.deepEqual(result.bins.map(bin=>bin.count),[1,1,1,1,1,1,2,2,1]);
  }
});

test('empty and repeated distributions do not share mutable bin state',()=>{
  assert.ok(buildVocabularyDistribution([],'accuracy').bins.every(bin=>bin.count===0));
  const first=buildVocabularyDistribution([{attempts:1,known_rate:.5}],'accuracy');
  const second=buildVocabularyDistribution([],'accuracy');
  assert.equal(first.bins[5].count,1);
  assert.equal(second.bins[5].count,0);
});
