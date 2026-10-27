const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');

let server, browser, page;
async function openTab(name){await page.getByRole('tab',{name}).click();}
async function materialIdByText(snippet){return page.evaluate(async text=>{const items=(await (await fetch('/api/materials')).json()).items;return items.find(item=>item.text_content.includes(text)).material_id;},snippet);}
async function selectSavedMaterialByText(targetPage,snippet){const id=await targetPage.evaluate(async text=>{const items=(await (await fetch('/api/materials/overlap-list')).json()).items;return items.find(item=>item.text_content.includes(text)).material_id;},snippet);await targetPage.locator('#savedList').selectOption(id);return id;}
before(async () => {
  server = spawn('py', ['tests/e2e_server.py'], {stdio:'ignore', windowsHide:true});
  const deadline = Date.now() + 20000;
  let ready = false;
  while (Date.now() < deadline) {
    try { const response = await fetch('http://127.0.0.1:18765/health'); if (response.ok) break; }
    catch (_) { await new Promise(resolve => setTimeout(resolve, 100)); }
  }
  browser = await chromium.launch({headless:true});
  page = await browser.newPage();
  page.setDefaultTimeout(5000);
  await page.goto('http://127.0.0.1:18765/');
});
after(async () => {
  if (page) await page.screenshot({path:'tests/e2e-artifacts/learning-final.png', fullPage:true}).catch(()=>{});
  if (browser) await browser.close();
  if (server) { server.kill(); }
});

test('overlap offers the harder native conversation speech condition', async () => {
  await page.goto('http://127.0.0.1:18765/#overlap');
  await page.waitForFunction(() => [...document.querySelector('#style').options].some(option => option.value === 'native_unfiltered'));
  const option = page.locator('#style option[value="native_unfiltered"]');
  assert.match(await option.textContent(), /ネイティブ/);
  await page.locator('#style').selectOption('native_unfiltered');
  assert.equal(await page.locator('#style').inputValue(), 'native_unfiltered');
});

test('overlap generation streams estimated percentage and phase updates', async () => {
  await page.goto('http://127.0.0.1:18765/#overlap');
  await page.locator('#overlapSource').fill('A fixture sentence.');
  await page.evaluate(() => {
    const realFetch=window.fetch.bind(window);
    window.fetch=(input,init)=>{
      if(String(input)!=='/generate')return realFetch(input,init);
      const encoder=new TextEncoder();
      if(window.failNextGeneration){
        window.failNextGeneration=false;
        const failedBody=new ReadableStream({start(controller){controller.enqueue(encoder.encode(JSON.stringify({type:'progress',percent:18,stage:'text'})+'\n'));setTimeout(()=>{controller.enqueue(encoder.encode(JSON.stringify({type:'error',error:'fixture generation failed'})+'\n'));controller.close();},250);}});
        return Promise.resolve(new Response(failedBody,{status:200,headers:{'Content-Type':'application/x-ndjson; charset=utf-8'}}));
      }
      const events=[
        {type:'progress',percent:8,stage:'text'},
        {type:'progress',percent:25,stage:'audio'},
        {type:'complete',result:{audio:'data:audio/mpeg;base64,AA==',words:[],blocks:[{english:'A fixture sentence.',japanese:'合成文です。',vocabulary:[]}],audio_file:'fixture.mp3',subtitle_file:'fixture.json',cost:{total_usd:0.01}}}
      ];
      const body=new ReadableStream({start(controller){
        controller.enqueue(encoder.encode(JSON.stringify(events[0])+'\n'));
        setTimeout(()=>controller.enqueue(encoder.encode(JSON.stringify(events[1])+'\n')),900);
        setTimeout(()=>{controller.enqueue(encoder.encode(JSON.stringify(events[2])+'\n'));controller.close();},1800);
      }});
      return Promise.resolve(new Response(body,{status:200,headers:{'Content-Type':'application/x-ndjson; charset=utf-8'}}));
    };
  });
  await page.locator('#generate').click();
  await page.waitForFunction(()=>document.querySelector('#generationProgressPhase').textContent==='文と和訳の準備');
  await page.waitForTimeout(900);
  const midProgress=Number.parseInt(await page.locator('#generationProgressPercent').textContent(),10);
  assert.ok(midProgress>8&&midProgress<100,'estimated percentage should advance in one-point steps while an API phase is waiting');
  await page.waitForFunction(()=>document.querySelector('#generationProgressPhase').textContent==='音声を生成中');
  await page.waitForFunction(()=>document.querySelector('#generationProgressPercent').textContent==='100%');
  assert.equal(await page.locator('#generationProgress [role="progressbar"]').getAttribute('aria-valuenow'),'100');
  assert.match(await page.locator('#status').textContent(),/完了/);
  await page.evaluate(()=>{window.failNextGeneration=true;});
  await page.locator('#generate').click();
  await page.waitForFunction(()=>document.querySelector('#generationProgressPhase').textContent==='失敗');
  assert.match(await page.locator('#status').textContent(),/fixture generation failed/);
  assert.equal(await page.locator('#generate').isEnabled(),true,'generation button should be re-enabled after failure');
});

test('overlap repeats a selected sentence by button or R and explains missing timing', async () => {
  await page.goto('http://127.0.0.1:18765/#overlap');
  await page.waitForFunction(()=>document.querySelector('#savedList').options.length>1);
  const fixtureId=await selectSavedMaterialByText(page,'A fixture sentence.');
  assert.doesNotMatch(await page.locator(`#savedList option[value="${fixtureId}"]`).textContent(),/\.json/,'saved selector uses DB material labels');
  await page.waitForFunction(()=>document.querySelector('#savedMeta').textContent.includes('教材ID:'));
  assert.match(await page.locator('#savedMeta').textContent(),/教材ID:/);
  await selectSavedMaterialByText(page,'We start here. Then we continue.');
  await page.waitForFunction(() => document.querySelectorAll('.reader-sentence').length === 2);
  const buttons = page.locator('.sentence-repeat');
  assert.equal(await buttons.count(), 2);
  assert.equal(await buttons.first().isEnabled(), true);
  await page.locator('#loop').check();
  await buttons.first().click();
  await page.waitForFunction(() => document.querySelector('.sentence-repeat').getAttribute('aria-pressed') === 'true');
  assert.equal(await buttons.first().getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('.reader-sentence.sentence-looping').count(), 1);
  const firstClip = await page.locator('#player').evaluate(async player => {
    const response = await fetch(player.currentSrc);
    const bytes = await response.arrayBuffer();
    const audio = new AudioContext();
    const decoded = await audio.decodeAudioData(bytes);
    const samples = decoded.getChannelData(0);
    const rms = (from, to) => Math.sqrt(samples.slice(Math.floor(from * decoded.sampleRate), Math.floor(to * decoded.sampleRate)).reduce((sum, value) => sum + value * value, 0) / Math.max(1, (to-from) * decoded.sampleRate));
    await audio.close();
    return {seconds:decoded.duration, firstTone:rms(0.8, 1.0), sampleCount:samples.length, rate:decoded.sampleRate};
  });
  assert.ok(Math.abs(firstClip.seconds - 1.1) < 1 / 24000, 'clip must end exactly at the last word timestamp');
  assert.ok(firstClip.firstTone > 0.1, 'fixture contains audible first-sentence audio');
  assert.equal(firstClip.sampleCount, Math.floor(1.1 * firstClip.rate), 'clip excludes all next-sentence samples');
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#player').evaluate(player => player.paused), true);
  assert.equal(await buttons.first().getAttribute('aria-pressed'), 'true');
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#player').evaluate(player => !player.paused), true);
  await page.locator('#player').evaluate(player => { player.currentTime = player.duration - 0.02; });
  await page.waitForFunction(() => document.querySelector('.sentence-repeat').dataset.repeatState === 'waiting');
  assert.equal(await page.locator('#player').evaluate(player => player.paused), true);
  const gapStarted = Date.now();
  await page.waitForFunction(() => { const player = document.querySelector('#player'); return !player.paused && player.currentTime < 0.5; });
  assert.ok(Date.now() - gapStarted >= 1300, 'a sentence repeat should include about 1.5 seconds of silence');
  await buttons.nth(1).click();
  await page.waitForFunction(() => document.querySelectorAll('.sentence-repeat')[1].getAttribute('aria-pressed') === 'true');
  assert.equal(await buttons.first().getAttribute('aria-pressed'), 'false');
  assert.equal(await buttons.nth(1).getAttribute('aria-pressed'), 'true');
  const secondClip = await page.locator('#player').evaluate(async player => {
    const audio = new AudioContext();
    const decoded = await audio.decodeAudioData(await (await fetch(player.currentSrc)).arrayBuffer());
    const samples = decoded.getChannelData(0);
    const rms = (from, to) => Math.sqrt(samples.slice(Math.floor(from * decoded.sampleRate), Math.floor(to * decoded.sampleRate)).reduce((sum, value) => sum + value * value, 0) / Math.max(1, (to-from) * decoded.sampleRate));
    await audio.close();
    return {seconds:decoded.duration, lead:rms(0.05,0.15), speech:rms(0.35,0.5)};
  });
  assert.ok(Math.abs(secondClip.seconds - 1.55) < 1 / 24000, 'the second clip includes a 0.25-second lead-in');
  assert.ok(secondClip.lead < 0.001 && secondClip.speech > 0.1, 'the second clip has silent lead-in and audible speech');
  await page.locator('#player').evaluate(player => { player.currentTime = player.duration - 0.02; });
  await page.waitForFunction(() => document.querySelectorAll('.sentence-repeat')[1].dataset.repeatState === 'waiting');
  await page.waitForFunction(() => { const player = document.querySelector('#player'); return !player.paused && player.currentTime < 0.25; });
  await page.locator('#player').evaluate(player => { player.currentTime = player.duration - 0.02; });
  await page.waitForFunction(() => document.querySelectorAll('.sentence-repeat')[1].dataset.repeatState === 'waiting');
  await page.keyboard.press('Space');
  assert.equal(await buttons.nth(1).getAttribute('data-repeat-state'), 'paused');
  assert.equal(await page.locator('#player').evaluate(player => player.paused), true);
  await page.keyboard.press('Space');
  await page.waitForFunction(() => { const player = document.querySelector('#player'); return !player.paused && player.currentTime < 0.25; });
  await page.locator('#player').evaluate(player => { player.currentTime = player.duration - 0.02; });
  await page.waitForFunction(() => document.querySelectorAll('.sentence-repeat')[1].dataset.repeatState === 'waiting');
  await buttons.first().click();
  await page.waitForFunction(() => document.querySelectorAll('.sentence-repeat')[0].getAttribute('aria-pressed') === 'true');
  assert.equal(await buttons.first().getAttribute('aria-pressed'), 'true');
  assert.equal(await buttons.nth(1).getAttribute('aria-pressed'), 'false');
  await buttons.nth(1).click();
  await page.waitForFunction(() => document.querySelectorAll('.sentence-repeat')[1].getAttribute('aria-pressed') === 'true');
  await page.keyboard.press('r');
  assert.equal(await buttons.nth(1).getAttribute('aria-pressed'), 'false');
  await page.waitForFunction(() => { const player=document.querySelector('#player'); return player.duration > 3.9 && player.currentTime >= 1.2; });
  await page.keyboard.press('r');
  await page.waitForFunction(() => document.querySelectorAll('.sentence-repeat')[1].getAttribute('aria-pressed') === 'true');
  assert.equal(await buttons.nth(1).getAttribute('aria-pressed'), 'true');
  await page.evaluate(() => document.activeElement?.blur());
  await page.keyboard.press('a');
  await page.waitForFunction(() => !document.querySelector('#player').paused && Math.abs(document.querySelector('#player').currentTime - 1.5) < 0.03);
  assert.equal(await buttons.nth(1).getAttribute('aria-pressed'), 'true', 'current sentence navigation should keep repeat selected');
  await page.keyboard.press('w');
  await page.waitForFunction(() => !document.querySelector('#player').paused && document.querySelector('#player').currentTime < 0.03);
  assert.equal(await buttons.nth(1).getAttribute('aria-pressed'), 'true', 'previous sentence navigation should keep repeat selected');
  await page.keyboard.press('r');
  await page.waitForFunction(() => document.querySelectorAll('.sentence-repeat')[1].getAttribute('aria-pressed') === 'false');
  await buttons.first().click();
  await page.waitForFunction(() => document.querySelectorAll('.sentence-repeat')[0].getAttribute('aria-pressed') === 'true');
  await buttons.first().click();
  assert.equal(await buttons.first().getAttribute('aria-pressed'), 'false', 'repeat button should still cancel repeat');
  await buttons.nth(1).click();
  await page.waitForFunction(() => document.querySelectorAll('.sentence-repeat')[1].getAttribute('aria-pressed') === 'true');
  await page.evaluate(() => document.activeElement?.blur());
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#player').evaluate(player => player.paused), true);
  assert.equal(await buttons.nth(1).getAttribute('aria-pressed'), 'true');
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#player').evaluate(player => !player.paused), true);
  await page.locator('#back').click();
  assert.equal(await buttons.nth(1).getAttribute('aria-pressed'), 'false');
  await page.waitForFunction(() => document.querySelector('#player').duration > 3.9);
  await buttons.first().focus();
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => document.querySelectorAll('.sentence-repeat')[0].getAttribute('aria-pressed') === 'true');
  assert.equal(await buttons.first().getAttribute('aria-pressed'), 'true');
  await page.locator('#restart').click();
  assert.equal(await buttons.first().getAttribute('aria-pressed'), 'false');
  await page.evaluate(() => document.activeElement?.blur());
  await page.keyboard.press('r');
  await page.waitForFunction(() => document.querySelectorAll('.sentence-repeat')[0].getAttribute('aria-pressed') === 'true');
  assert.equal(await buttons.first().getAttribute('aria-pressed'), 'true');
  await page.locator('#overlapSource').focus();
  await page.keyboard.press('r');
  assert.equal(await buttons.first().getAttribute('aria-pressed'), 'true');
  await selectSavedMaterialByText(page,'Go. Now.');
  await page.waitForFunction(() => document.querySelector('#reader').textContent.includes('Go.'));
  assert.equal(await buttons.first().isDisabled(), true);
  assert.equal(await buttons.nth(1).isEnabled(), true);
  await selectSavedMaterialByText(page,'An untimed sentence. Another untimed sentence.');
  await page.waitForFunction(() => document.querySelector('#reader').textContent.includes('An untimed sentence.'));
  assert.equal(await buttons.first().isDisabled(), true);
  assert.match(await buttons.first().getAttribute('aria-label'), /時刻情報がない/);
  assert.equal(await page.locator('#sentenceTimingNotice').isVisible(), true);
  assert.equal(await page.locator('.reader-sentence.sentence-looping').count(), 0);
});

test('overlap sentence navigation keys are configurable and controls stay beside scrolling text', async () => {
  await page.goto('http://127.0.0.1:18765/#overlap');
  await page.waitForFunction(()=>[...document.querySelector('#savedList').options].some(option=>option.textContent.includes('Finally, we finish.')));
  await selectSavedMaterialByText(page,'Finally, we finish.');
  await page.waitForFunction(()=>document.querySelectorAll('.reader-sentence').length===3);
  const player=page.locator('#player');
  await page.waitForFunction(()=>document.querySelector('#player').duration>3.9);
  await page.evaluate(()=>document.activeElement?.blur());
  await player.evaluate(audio=>{audio.currentTime=2;});
  await page.keyboard.press('a');
  await page.waitForFunction(()=>Math.abs(document.querySelector('#player').currentTime-1.5)<0.03&&!document.querySelector('#player').paused);
  await player.evaluate(audio=>audio.pause());
  await player.evaluate(audio=>{audio.currentTime=2;});
  await page.keyboard.press('w');
  await page.waitForFunction(()=>document.querySelector('#player').currentTime<0.03&&!document.querySelector('#player').paused);
  await player.evaluate(audio=>audio.pause());
  await player.evaluate(audio=>{audio.currentTime=0.5;});
  await page.keyboard.press('w');
  await page.waitForFunction(()=>document.querySelector('#player').currentTime<0.03&&!document.querySelector('#player').paused);
  await player.evaluate(audio=>audio.pause());
  await page.locator('#overlapSource').focus();
  await page.keyboard.press('a');
  assert.equal(await player.evaluate(audio=>audio.paused),true,'editable controls should keep A as text input');
  await page.evaluate(()=>document.activeElement?.blur());
  await player.evaluate(audio=>{audio.currentTime=2;});
  await page.keyboard.press('Shift+a');
  assert.ok(Math.abs(await player.evaluate(audio=>audio.currentTime)-2)<0.1,'modifier shortcuts should not seek');
  await page.evaluate(()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'a',bubbles:true,isComposing:true})));
  assert.ok(Math.abs(await player.evaluate(audio=>audio.currentTime)-2)<0.1,'IME composition should suppress shortcuts');
  await page.locator('#currentSentenceKey').fill('x');
  await page.locator('#previousSentenceKey').fill('y');
  await page.locator('#sentenceRepeatKey').fill('z');
  await page.locator('#saveOverlapSettings').click();
  await page.reload();
  assert.equal(await page.locator('#currentSentenceKey').inputValue(),'x');
  assert.equal(await page.locator('#previousSentenceKey').inputValue(),'y');
  assert.equal(await page.locator('#sentenceRepeatKey').inputValue(),'z');
  await page.locator('#sentenceRepeatKey').fill('r');
  await page.locator('#currentSentenceKey').fill('a');
  await page.locator('#previousSentenceKey').fill('w');
  await page.locator('#saveOverlapSettings').click();
  const sidebar=page.locator('.overlap-sidebar');
  assert.equal(await sidebar.evaluate(node=>getComputedStyle(node).position),'sticky');
  const transcript=page.locator('.overlap-transcript');
  await selectSavedMaterialByText(page,'Finally, we finish.');
  await page.waitForFunction(()=>document.querySelectorAll('.reader-sentence').length===3);
  await page.locator('#reader').evaluate(root=>{for(let index=0;index<8;index++)root.append(root.firstElementChild.cloneNode(true));});
  await transcript.evaluate(node=>{node.scrollTop=100;});
  assert.ok(await transcript.evaluate(node=>node.scrollTop>0),'sentence text should scroll independently');
  assert.ok(await sidebar.isVisible(),'playback and settings remain visible beside transcript');
  const alignActiveSentence=async(index)=>{
    await page.waitForFunction(sentenceIndex=>document.querySelectorAll('.reader-sentence')[sentenceIndex]?.classList.contains('sentence-active'),index);
    await page.waitForFunction(sentenceIndex=>{
      const container=document.querySelector('.overlap-transcript');
      const sentence=document.querySelectorAll('.reader-sentence')[sentenceIndex];
      return Math.abs(sentence.getBoundingClientRect().top-container.getBoundingClientRect().top)<3;
    },index);
  };
  await page.locator('#scroll').check();
  await player.evaluate(audio=>{audio.currentTime=1.6;void audio.play();});
  await alignActiveSentence(1);
  const secondTop=await transcript.evaluate(node=>node.scrollTop);
  await player.evaluate(audio=>{audio.currentTime=1.8;});
  await page.waitForTimeout(120);
  assert.ok(Math.abs(await transcript.evaluate(node=>node.scrollTop)-secondTop)<=2,'focus within one sentence should not scroll repeatedly');
  await player.evaluate(audio=>{audio.currentTime=3.1;});
  await alignActiveSentence(2);
  await player.evaluate(audio=>audio.pause());
  await page.locator('#scroll').uncheck();
  await player.evaluate(audio=>{audio.currentTime=0;void audio.play();});
  await page.waitForFunction(()=>document.querySelectorAll('.reader-sentence')[0]?.classList.contains('sentence-active'));
  await player.evaluate(audio=>audio.pause());
  await transcript.evaluate(node=>{node.scrollTop=100;});
  const beforeManualFocus=await transcript.evaluate(node=>node.scrollTop);
  await player.evaluate(audio=>{audio.currentTime=3.2;void audio.play();});
  await page.waitForFunction(()=>document.querySelectorAll('.reader-sentence')[2]?.classList.contains('sentence-active'));
  await page.waitForTimeout(120);
  assert.ok(Math.abs(await transcript.evaluate(node=>node.scrollTop)-beforeManualFocus)<=2,'disabled follow should preserve manual scroll');
});

test('A/U reveals answer, S/I records, mouse works and settings persist', async () => {
  await openTab('語彙練習');
  await page.locator('#learningCategory').selectOption('WorkAndCareer');
  await page.locator('#startLearning').click();
  await page.waitForFunction(() => document.querySelector('#vocabularyQuestion').textContent === 'take part');
  await page.keyboard.press('u');
  assert.equal(await page.locator('#vocabularyAnswer').textContent(), '参加する');
  await page.keyboard.press('i');
  await page.waitForFunction(() => document.querySelector('#vocabularyQuestion').textContent === 'comprehensive');
  await page.locator('#learningDirection').selectOption('ja_to_en');
  await page.locator('#startLearning').click();
  await page.waitForFunction(() => document.querySelector('#vocabularyQuestion').textContent === '参加する');
  await page.locator('#revealAnswer').click();
  assert.equal(await page.locator('#vocabularyAnswer').textContent(), 'take part');
  await page.locator('#againKeys').fill('q,w');
  const keySave=page.waitForResponse(response=>response.url().includes('/api/settings/keys')&&response.request().method()==='POST');
  await page.locator('#saveKeySettings').click();
  assert.equal((await keySave).status(),200);
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#againKeys').value === 'q,w');
  assert.equal(await page.locator('#againKeys').inputValue(), 'q,w');
  await openTab('オーバーラッピング');
  await page.waitForFunction(() => document.querySelector('#storageLocation').textContent.includes('教材保存先'));
  await page.waitForFunction(() => document.querySelector('#storageLocation').textContent.includes('テスト用'));
  assert.match(await page.locator('#storageLocation').textContent(),/overlap-e2e-.*materials/);
  await selectSavedMaterialByText(page,'A fixture sentence.');
  await page.waitForFunction(() => document.querySelector('#reader').textContent.includes('A fixture sentence.'));
  assert.equal(await page.locator('#reader .reader-sentence').count(),1);
  assert.match(await page.locator('#reader .reader-japanese').textContent(),/\u5408\u6210/);
  assert.match(await page.locator('#reader .reader-vocabulary').textContent(),/fixture/);
  await page.locator('#play').click();
  await page.waitForFunction(() => document.querySelector('#reader .active'));
  assert.equal(await page.locator('#player').evaluate(player => !player.paused), true);
  await page.evaluate(()=>{(document.activeElement instanceof HTMLElement ? document.activeElement : null)?.blur();});
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#player').evaluate(player=>player.paused),true);
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#player').evaluate(player=>!player.paused),true);
});

test('vocabulary prompt is prominent in both directions and fits a mobile viewport', async () => {
  await page.setViewportSize({width:1280,height:900});
  await page.goto('http://127.0.0.1:18765/');
  await openTab('語彙練習');
  await page.waitForFunction(()=>document.querySelector('#learningCategory').options.length>1);
  await page.locator('#learningCategory').selectOption('DailyLife');
  await page.locator('#masteryStatus').selectOption('all');
  await page.locator('#startLearning').click();
  await page.waitForFunction(()=>document.querySelector('#vocabularyQuestion').textContent==='guide');
  const englishFont=await page.locator('#vocabularyQuestion').evaluate(element=>parseFloat(getComputedStyle(element).fontSize));
  assert.ok(englishFont>=39,`desktop prompt font ${englishFont}px`);
  await page.keyboard.press('u');
  assert.equal(await page.locator('#vocabularyAnswer').textContent(),'手引き');
  await page.screenshot({path:'tests/e2e-artifacts/vocabulary-modern.png',fullPage:true});
  await page.locator('#learningDirection').selectOption('ja_to_en');
  await page.locator('#startLearning').click();
  await page.waitForFunction(()=>document.querySelector('#vocabularyQuestion').textContent==='手引き');
  assert.equal(await page.locator('#vocabularyAnswer').isHidden(),true);
  await page.setViewportSize({width:390,height:844});
  const width=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));
  assert.ok(width.document<=width.viewport,JSON.stringify(width));
  assert.ok(await page.locator('#vocabularyStage').isVisible());
});

test('shortcut guidance explains both learning states and follows customized keys', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await openTab('語彙練習');
  await page.locator('#resetKeySettings').click();
  await page.waitForFunction(()=>document.querySelector('#learningStatus').textContent.includes('初期値に戻しました'));
  await page.waitForFunction(()=>document.querySelector('#shortcutHint').textContent.includes('問題中：A / U / S / I'));
  assert.match(await page.locator('#shortcutHint').textContent(),/答え表示後：A \/ U でもう一度、S \/ I で覚えていた/);
  await page.locator('#againKeys').fill('q,w');
  const saved=page.waitForResponse(response=>response.url().includes('/api/settings/keys')&&response.request().method()==='POST');
  await page.locator('#saveKeySettings').click();
  assert.equal((await saved).status(),200);
  await page.waitForFunction(()=>document.querySelector('#shortcutHint').textContent.includes('答え表示後：Q / W でもう一度'));
  await page.locator('#learningCategory').selectOption('DailyLife');
  await page.locator('#masteryStatus').selectOption('all');
  await page.locator('#startLearning').click();
  await page.waitForFunction(()=>document.querySelector('#vocabularyQuestion').textContent==='guide');
  await page.keyboard.press('u');
  assert.equal(await page.locator('#vocabularyAnswer').textContent(),'手引き');
  const answerSaved=page.waitForResponse(response=>response.url().includes('/api/answer')&&response.request().method()==='POST');
  await page.keyboard.press('q');
  assert.equal((await answerSaved).status(),200);
  await page.waitForFunction(()=>document.querySelector('#learningStatus').textContent.includes('もう一度、と記録しました'));
  await page.locator('#resetKeySettings').click();
  await page.waitForFunction(()=>document.querySelector('#learningStatus').textContent.includes('初期値に戻しました'));
  assert.match(await page.locator('#shortcutHint').textContent(),/答え表示後：A \/ U でもう一度/);
});

test('shared mastery and count filters limit the vocabulary practice session', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await page.getByRole('tab').nth(1).click();
  await page.waitForFunction(()=>document.querySelector('#learningCategory').options.length>1);
  await page.locator('#learningCategory').selectOption('DailyLife');
  await page.locator('#masteryStatus').selectOption('all');
  await page.locator('#setCount').fill('1');
  await page.locator('#startLearning').click();
  await page.waitForFunction(()=>!document.querySelector('#revealAnswer').disabled);
  assert.equal(await page.locator('#learningProgress').textContent(),'1 / 1問目');
  await page.locator('#revealAnswer').click();
  await page.locator('#rateKnown').click();
  await page.waitForFunction(()=>document.querySelector('#vocabularyAnswer').hidden);
  assert.equal(await page.locator('#learningProgress').textContent(),'1問完了');
  assert.equal(await page.locator('#rateKnown').isDisabled(),true);
});

test('practice supports 1000 questions and recent performance filters', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await openTab('語彙練習');
  await page.locator('#setCount').fill('1000');
  await page.locator('#recentAttempts').fill('5');
  await page.locator('#maxRecentAccuracy').fill('40');
  await page.locator('#includeInsufficientHistory').check();
  await page.locator('#allAttemptsIncorrect').selectOption('true');
  let query;
  await page.route('**/api/next-question?**',async route=>{
    query=new URL(route.request().url()).searchParams;
    await route.fulfill({json:{item:{vocab_id:'fixture-vocab',english:'take part',meaning:'参加する',pos:'verb'}}});
  });
  await page.locator('#startLearning').click();
  await page.waitForFunction(()=>document.querySelector('#learningProgress').textContent==='1 / 1\u554f\u76ee');
  assert.equal(query.get('count'),'1000');
  assert.equal(query.get('recent_attempts'),'5');
  assert.equal(query.get('max_recent_accuracy'),'40');
  assert.equal(query.get('include_insufficient_history'),'true');
  assert.equal(query.get('all_attempts_incorrect'),'true');
  assert.equal(await page.locator('#setCount').getAttribute('max'),'1000');
  await page.unroute('**/api/next-question?**');
});

test('vocabulary progress advances, completes, resets and explains an empty set', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await openTab('語彙練習');
  await page.waitForFunction(()=>document.querySelector('#learningCategory').options.length>1);
  await page.locator('#learningCategory').selectOption('WorkAndCareer');
  await page.locator('#masteryStatus').selectOption('all');
  await page.locator('#setCount').fill('2');
  await page.locator('#startLearning').click();
  await page.waitForFunction(()=>document.querySelector('#learningProgress').textContent==='1 / 2問目');
  await page.keyboard.press('u');
  await page.keyboard.press('i');
  await page.waitForFunction(()=>document.querySelector('#learningProgress').textContent==='2 / 2問目');
  await page.keyboard.press('u');
  await page.keyboard.press('i');
  await page.waitForFunction(()=>document.querySelector('#learningProgress').textContent==='2問完了');
  await page.locator('#startLearning').click();
  await page.waitForFunction(()=>document.querySelector('#learningProgress').textContent==='1 / 2問目');
  await page.locator('#setDifficulty').selectOption('C2');
  await page.locator('#startLearning').click();
  await page.waitForFunction(()=>document.querySelector('#learningProgress').textContent==='この条件に合う語彙はありません');
});



test('category weakness plan, automatic material save, editing and vocabulary links', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await openTab('オーバーラッピング');
  await page.waitForFunction(()=>document.querySelector('#studySetCategory').options.length>1);
  await page.locator('#studySetCategory').selectOption('WorkAndCareer');
  await page.waitForFunction(()=>document.querySelector('#setTheme').options.length>1);
  await page.locator('#setTheme').selectOption('WorkAndCareer');
  await page.locator('#studySetCount').fill('2');
  assert.equal(await page.locator('#studySetMasteryStatus').inputValue(),'all');
  await openTab('語彙練習');
  assert.equal(await page.locator('#studySetCard').isVisible(),false);
  assert.equal(await page.locator('#learningCategory').inputValue(),'','vocabulary practice filters must remain independent');
  await openTab('オーバーラッピング');
  await page.locator('#planStudySet').click();
  await page.waitForFunction(() => document.querySelectorAll('#studySetPlan input[type=checkbox]').length === 2);
  const planned=await page.evaluate(async()=>{const response=await fetch('/api/study-set/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:'WorkAndCareer',direction:'en_to_ja',count:2,include_unstudied:true,mastery_status:'all',difficulty:'',theme:'WorkAndCareer',length:'short'})});return await response.json();});
  for(const item of planned.items)await page.evaluate(async item=>{await fetch('/api/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vocab_id:item.vocab_id,sense_id:item.sense_id,direction:'en_to_ja',rating:'again',duration_seconds:1,idempotency_key:crypto.randomUUID()})});},item);
  await page.locator('#studySetRecentAttempts').fill('1');
  await page.locator('#studySetMaxRecentAccuracy').fill('0');
  await page.locator('#studySetIncludeInsufficientHistory').check();
  const plannedResponse=page.waitForResponse(response=>response.url().includes('/api/study-set/plan')&&response.request().method()==='POST');
  await page.locator('#planStudySet').click();
  const filteredPlan=await (await plannedResponse).json();
  assert.equal(filteredPlan.selected_count,2);
  assert.deepEqual([filteredPlan.conditions.theme,filteredPlan.conditions.recent_attempts,filteredPlan.conditions.max_recent_accuracy,filteredPlan.conditions.include_insufficient_history],['WorkAndCareer',1,0,true]);
  assert.equal(await page.locator('#studySetMode').inputValue(),'per_vocabulary','sentence-per-word mode is the default');
  await page.locator('#studySetMode').selectOption('article');
  await page.waitForFunction(() => document.querySelectorAll('#studySetPlan input[type=checkbox]').length === 2);
  let generatedIds=[];
  await page.route('**/api/study-set/generate', async route => {const request=route.request().postDataJSON();generatedIds=request.vocab_ids;assert.equal(request.theme,'WorkAndCareer');assert.equal(request.generation_mode,'article');await route.fulfill({status:202,json:{job_id:'fixture-generation-job'}});});
  await page.route('**/api/jobs?id=fixture-generation-job',async route=>{
    const text='Our comprehensive team took part in the program.';
    await route.fulfill({json:{status:'completed',completed_items:generatedIds.length,total_items:generatedIds.length,payload:{vocab_ids:generatedIds,generation_mode:'article'},result:{text,groups:[[text]],sentences:[text],used_vocab_ids:generatedIds,unused_vocab_ids:[],usages:[],model:'fixture-model',usage:{input_tokens:10,output_tokens:12},cost:{usd:.000007},request_count:1,generation_mode:'article'}}});
  });
  assert.equal(await page.locator('#saveStudySet').count(),0,'redundant material-save button is still visible');
  assert.ok(await page.locator('#source').evaluate(element=>element.getBoundingClientRect().height>=320),'generated-text editor should be taller');
  const saveResponse=page.waitForResponse(response=>response.url().includes('/api/study-set/save'));
  await page.locator('#generateStudySet').click();
  await page.waitForFunction(() => document.querySelector('#source').value.includes('took part'));
  const saved=await saveResponse;
  assert.equal(saved.status(),200,await saved.text());
  const savedBody=await saved.json();
  await page.locator('#source').fill('Our comprehensive group planned the response.\n\nThe team took part in a trial.');
  await page.locator('#generateStudySet').focus();
  const listedIds=await page.evaluate(async()=> (await (await fetch('/api/materials')).json()).items.map(item=>item.material_id));
  assert.ok(savedBody.material_ids.every(id=>listedIds.includes(id)),'database-only generated study material appears in the shared material list');
  await page.waitForFunction(()=>document.querySelector('#tab-overlap').getAttribute('aria-selected')==='true');
  assert.equal(await page.locator('#overlapSource').inputValue(),'Our comprehensive group planned the response.\n\nThe team took part in a trial.');
  await selectSavedMaterialByText(page,'A fixture sentence.');
  await page.locator('#play').click();
  await page.waitForFunction(()=>document.querySelector('#reader .active'));
  await page.waitForFunction(()=>document.querySelector('#player').currentTime>.2);
  const activitySaved=page.waitForResponse(response=>response.url().includes('/api/overlap/activity')&&response.ok());
  await page.locator('#play').click();
  await activitySaved;
  const stats=await page.evaluate(async()=> (await (await fetch('/api/statistics')).json()));
  assert.ok(stats.active_seconds>0);
  assert.ok(stats.vocabulary_active_seconds>0,JSON.stringify(stats));
  assert.ok(stats.overlap_active_seconds>0,JSON.stringify(stats));
  assert.equal(stats.active_seconds,stats.vocabulary_active_seconds+stats.overlap_active_seconds);
  assert.equal((await page.evaluate(async()=> (await (await fetch('/api/study-set/last')).json()).conditions.category)),'WorkAndCareer');
  assert.equal((await page.evaluate(async()=> (await (await fetch('/api/study-set/last')).json()).conditions.mastery_status)),'all');
  assert.equal((await page.evaluate(async()=> (await (await fetch('/api/study-set/last')).json()).conditions.mastery_status)),'all');
  assert.match(await page.locator('#statisticsPanel').textContent(),/\u65e5\u672c\u6642\u9593/);
  await page.locator('#openDashboard').click();
  await page.waitForFunction(()=>document.querySelector('#databaseStatistics').children.length===6);
  const performanceDetails=page.locator('#vocabularyPerformanceDetails');
  assert.equal(await performanceDetails.evaluate(node=>node.open),false,'vocabulary performance starts collapsed');
  await performanceDetails.locator('summary').click();
  assert.equal(await performanceDetails.evaluate(node=>node.open),true);
  assert.match(await page.locator('#databaseStatistics').textContent(),/\u767b\u5834\u6570/);
  assert.match(await page.locator('#vocabularyPerformance').textContent(),/take part/);
  await page.locator('#performanceSort').selectOption('attempts');
  await page.locator('#performanceSearch').fill('take part');
  assert.match(await page.locator('#performanceCount').textContent(),/\u8a9e/);
  await page.locator('#statisticsRange').selectOption('7');
  await page.waitForFunction(()=>document.querySelector('#statisticsPanel').textContent.includes('7\u65e5\u9593')&&document.querySelector('#statisticsPanel').textContent.includes('\u8a9e\u5f59\u7df4\u7fd2\u6642\u9593')&&document.querySelector('#statisticsPanel').textContent.includes('\u30aa\u30fc\u30d0\u30fc\u30e9\u30c3\u30d4\u30f3\u30b0\u6642\u9593'));
  await page.route('**/api/statistics?days=90',route=>route.fulfill({json:{daily:{},database_stats:{vocabulary_count:10,active_vocabulary_count:8,archived_vocabulary_count:2,sense_count:12,attempt_count:4,known_count:3,again_count:1,accuracy:.75,unseen_vocabulary_count:6},vocabulary_performance:Array.from({length:25},(_,i)=>({english:i===0?'exceptionally-long-vocabulary-label-for-narrow-screens':`fixture-word-${i}`,japanese:'fixture meaning',attempts:i===0?0:i,known:i===0?0:i%3,again:i===0?0:i%2,known_rate:i===0?null:(i-1)/23})),vocabulary_active_seconds:0,overlap_active_seconds:0,active_seconds:0,study_days:0,due_count:0,due_items:[],new_vocabulary_count:6,known_rate:null,legacy_history_count_excluded:0,period_start_tokyo:'2026-07-27',period_end_tokyo:'2026-10-24'}}));
  const stats90Response=page.waitForResponse(response=>response.url().includes('/api/statistics?days=90')&&response.ok());
  await page.locator('#statisticsRange').selectOption('90');
  await stats90Response;
  await page.waitForFunction(()=>document.querySelector('#databaseStatistics').textContent.includes('登録語彙'));
  const inventoryText=await page.locator('#databaseStatistics').textContent();
  assert.match(inventoryText,/登録語彙/);assert.match(inventoryText,/学習対象/);assert.match(inventoryText,/語義/);
  assert.equal(await page.locator('#databaseStatistics').locator('.stat-card').count(),8,'different inventory values are shown separately');
  await page.locator('#performanceSearch').fill('');
  await page.waitForFunction(()=>document.querySelectorAll('#vocabularyPerformanceChart .chart-row').length===25);
  await page.locator('#vocabularyViewChart').click();
  assert.equal(await page.locator('#vocabularyPerformanceChart .chart-row').count(),25,'chart renders a larger vocabulary fixture');
  const longChartLabel=page.locator('#vocabularyPerformanceChart .chart-label').filter({hasText:'exceptionally-long'});
  assert.match(await longChartLabel.getAttribute('title'),/exceptionally-long/,'long labels remain available as a tooltip');
  assert.equal(await page.locator('#vocabularyDistributionMetric').inputValue(),'accuracy');
  assert.match(await page.locator('#vocabularyDistributionSummary').textContent(),/正答率を計算できる語彙 24 語 \/ 未学習のため除外 1 語/);
  assert.match(await page.locator('#vocabularyDistributionChart svg').getAttribute('aria-label'),/0–9%: 3語/);
  await page.locator('#vocabularyDistributionMetric').selectOption('attempts');
  assert.match(await page.locator('#vocabularyDistributionChart svg').getAttribute('aria-label'),/登場回数ごとの語彙数分布/);
  assert.match(await page.locator('#vocabularyDistributionChart svg').getAttribute('aria-label'),/0: 1語/,'unseen vocabulary is included in the zero-count bin');
  await page.locator('#vocabularyDistributionMetric').focus();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await page.waitForFunction(()=>document.querySelector('#vocabularyDistributionChart svg')?.getAttribute('aria-label').includes('正解数ごと'));
  await page.locator('#vocabularyDistributionMetric').selectOption('again');
  assert.match(await page.locator('#vocabularyDistributionChart svg').getAttribute('aria-label'),/再学習数ごとの語彙数分布/);
  await page.locator('#vocabularyDistributionMetric').selectOption('attempts');
  await page.locator('#performanceSearch').fill('fixture-word-24');
  await page.waitForFunction(()=>document.querySelector('#vocabularyDistributionSummary').textContent.includes('対象 1 語'));
  assert.match(await page.locator('#vocabularyDistributionChart svg').getAttribute('aria-label'),/21\+: 1語/);
  await page.locator('#performanceSearch').fill('no matching vocabulary');
  await page.waitForFunction(()=>document.querySelector('#vocabularyDistributionChart').textContent.includes('検索条件に合う語彙がありません'));
  await page.locator('#performanceSearch').fill('');
  await page.waitForFunction(()=>document.querySelectorAll('#vocabularyDistributionChart svg').length===1);
  await page.locator('#performanceSort').selectOption('english');
  await page.waitForFunction(()=>document.querySelector('#vocabularyPerformanceChart .chart-label')?.textContent==='exceptionally-long-vocabulary-label-for-narrow-screens');
  await page.locator('#dailyViewChart').click();
  assert.match(await page.locator('#dailyLearningChart').textContent(),/表示できる学習実績がありません/,'empty daily chart is handled');
  await page.unroute('**/api/statistics?days=90');
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#dashboard-panel').hidden===false&&document.querySelector('#databaseStatistics').children.length>=6);
  assert.equal(await page.locator('#vocabularyPerformanceDetails').evaluate(node=>node.open),false,'direct dashboard navigation starts collapsed');
  assert.match(await page.locator('#databaseStatistics').textContent(),/語彙/);
  assert.doesNotMatch(await page.locator('#databaseStatistics').textContent(),/登録語彙|学習対象|語義/,'equal counts are consolidated as vocabulary');
  await page.locator('#vocabularyPerformanceDetails summary').focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#vocabularyPerformanceDetails').evaluate(node=>node.open),true,'keyboard can expand performance');
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#vocabularyPerformanceDetails').evaluate(node=>node.open),false,'keyboard can collapse performance');
  await page.locator('#vocabularyPerformanceDetails summary').click();
  assert.ok(await page.locator('#vocabularyPerformance tbody tr').count()>0,'per-vocabulary rows should render');
  assert.ok((await page.locator('#dailyLearningTable table tr').count())>1,'daily learning table should include data rows');
  assert.equal(await page.locator('.daily-performance-section > summary').textContent(),'日付ごとの学習実績');
  await page.locator('#vocabularyViewChart').focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#vocabularyPerformance').isHidden(),true,'keyboard switches vocabulary results to chart');
  assert.ok(await page.locator('#vocabularyPerformanceChart .chart-row').count()>0);
  assert.match(await page.locator('#vocabularyPerformanceChart').textContent(),/正解/);
  await page.locator('#performanceSearch').fill('take part');
  await page.waitForFunction(()=>document.querySelectorAll('#vocabularyPerformanceChart .chart-row').length===1);
  assert.equal(await page.locator('#vocabularyPerformanceChart .chart-row').count(),1,'search filters chart data');
  await page.locator('#vocabularyViewTable').focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#vocabularyPerformance').isHidden(),false,'keyboard switches back to the table');
  await page.locator('#dailyViewChart').click();
  assert.equal(await page.locator('#dailyLearningTable').isHidden(),true);
  assert.ok(await page.locator('#dailyLearningChart .chart-row').count()>0);
  await page.locator('#dailyChartMetric').selectOption('duration');
  await page.waitForFunction(()=>document.querySelector('#dailyLearningChart').getAttribute('aria-label').includes('学習時間'));
  assert.match(await page.locator('#dailyLearningChart').getAttribute('aria-label'),/学習時間/,'daily chart metric switches to study time');
  assert.match(await page.locator('#statisticsPanel').textContent(),/\u5b66\u7fd2\u65e5\u6570/);
  await page.route('**/api/statistics?days=7',async route=>{
    await route.fulfill({json:{daily:{'2026-10-24':{answers:1,known:1,again:0,vocabulary_active_seconds:4,overlap_active_seconds:0,active_seconds:4}},vocabulary_active_seconds:4,overlap_active_seconds:0,active_seconds:4,study_days:1,due_count:0,due_items:[],new_vocabulary_count:125,known_rate:1,legacy_history_count_excluded:0,period_start_tokyo:'2026-10-18',period_end_tokyo:'2026-10-24'}});
  });
  await page.locator('#statisticsRange').selectOption('7');
  await page.waitForFunction(()=>document.querySelector('#statisticsPanel').textContent.includes('7\u65e5\u9593'));
  assert.match(await page.locator('#statisticsPanel').textContent(),/\u5b66\u7fd2\u65e5\u6570/,'period summary remains available when optional all-time fields are missing');
  assert.match(await page.locator('#databaseStatistics').textContent(),/\u30c7\u30fc\u30bf\u30d9\u30fc\u30b9\u5168\u4f53\u306e\u7d71\u8a08\u3092\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093/);
  assert.match(await page.locator('#vocabularyPerformance').textContent(),/\u8a9e\u5f59\u5225\u306e\u5b66\u7fd2\u5b9f\u7e3e\u3092\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093/);
  await page.locator('#vocabularyViewChart').click();
  assert.match(await page.locator('#vocabularyPerformanceChart').textContent(),/表示できる学習実績がありません/,'empty vocabulary chart has a helpful message');
  await page.locator('#dailyViewChart').click();
  await page.unroute('**/api/statistics?days=7');
  await page.locator('#statisticsRange').selectOption('30');
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'dashboard should fit a mobile viewport');
  await page.setViewportSize({width:1280,height:900});
  await page.reload();
  await openTab('オーバーラッピング');
  await page.waitForFunction(()=>document.querySelector('#studySetCategory').value==='WorkAndCareer');
  assert.equal(await page.locator('#studySetCategory').inputValue(),'WorkAndCareer');
  assert.equal(await page.locator('#setTheme').inputValue(),'WorkAndCareer');
  assert.equal(await page.locator('#studySetCount').inputValue(),'2');
  assert.equal(await page.locator('#studySetRecentAttempts').inputValue(),'1');
  assert.equal(await page.locator('#studySetMaxRecentAccuracy').inputValue(),'0');
  assert.equal(await page.locator('#studySetIncludeInsufficientHistory').isChecked(),true);
  await page.screenshot({path:'tests/e2e-artifacts/study-set.png',fullPage:true});
});

test('study-set history filters return eligible words for all categories and selected category', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await page.locator('#tab-overlap').click();
  await page.waitForFunction(()=>document.querySelector('#studySetCategory').options.length>1);
  await page.locator('#studySetCategory').selectOption('');
  await page.locator('#studySetCount').fill('10');
  await page.locator('#studySetRecentAttempts').fill('1');
  await page.locator('#studySetMaxRecentAccuracy').fill('0');
  const allResponse=page.waitForResponse(response=>response.url().includes('/api/study-set/plan')&&response.request().method()==='POST');
  await page.locator('#planStudySet').click();
  const allPlan=await (await allResponse).json();
  assert.ok(allPlan.selected_count>0,'all categories should include eligible low-accuracy words');
  assert.ok(allPlan.items.length>0);
  assert.equal(await page.locator('#studySetPlan input[type=checkbox]').count(),allPlan.selected_count,'all selected vocabulary is displayed');

  await page.locator('#studySetCategory').selectOption('WorkAndCareer');
  const categoryResponse=page.waitForResponse(response=>response.url().includes('/api/study-set/plan')&&response.request().method()==='POST');
  await page.locator('#planStudySet').click();
  const categoryPlan=await (await categoryResponse).json();
  assert.ok(categoryPlan.selected_count>0,'selected category should include eligible low-accuracy words');
  assert.ok(categoryPlan.items.every(item=>item.vocab_id));
  await page.waitForFunction(()=>document.querySelectorAll('#studySetPlan input[type=checkbox]').length>0);
});

test('empty study-set plan explains filters and direction-unknown legacy history', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await page.locator('#tab-overlap').click();
  await page.locator('#studySetDirection').selectOption('ja_to_en');
  await page.route('**/api/study-set/plan',route=>route.fulfill({json:{conditions:{},selected_count:0,items:[],history_summary:{direction:'ja_to_en',category:null,directional_answer_vocabulary_count:0,legacy_history_count_excluded:14085},estimated_total_usd:0,estimated_text_usd:0,estimated_realtime_usd:0,estimated_transcription_usd:0,estimate_note:''}}));
  await page.locator('#planStudySet').click();
  await page.waitForFunction(()=>document.querySelector('#studySetStatus').textContent.includes('学習方向が記録されていない'));
  const status=await page.locator('#studySetStatus').textContent();
  assert.match(status,/条件に一致する語彙がありません/);
  assert.match(status,/日本語→英語の回答履歴がある語彙: 0件/);
  assert.match(status,/旧履歴14,085件/);
  await page.unroute('**/api/study-set/plan');
});

test('study-set insufficient-history option includes a category with no answers', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await page.locator('#tab-overlap').click();
  await page.waitForFunction(()=>[...document.querySelector('#studySetCategory').options].some(option=>option.value==='Pagination'));
  await page.locator('#studySetCategory').selectOption('Pagination');
  assert.equal(await page.locator('#studySetCategory').inputValue(),'Pagination');
  await page.locator('#studySetRecentAttempts').fill('3');
  await page.locator('#studySetMaxRecentAccuracy').fill('0');
  await page.locator('#studySetIncludeInsufficientHistory').check();
  const planResponse=page.waitForResponse(response=>response.url().includes('/api/study-set/plan')&&response.request().method()==='POST');
  await page.locator('#planStudySet').click();
  const plan=await (await planResponse).json();
  assert.equal(plan.conditions.category,'Pagination');
  assert.equal(plan.conditions.include_insufficient_history,true);
  assert.equal(plan.history_summary.directional_answer_vocabulary_count,0);
  assert.ok(plan.selected_count>0,'the category has vocabulary but no answer history');
  await page.waitForFunction(()=>document.querySelectorAll('#studySetPlan input[type=checkbox]').length>0);
});

test('keyboard is ignored in editable fields and answer remains after a save error', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await openTab('語彙練習');
  await page.locator('#learningCategory').selectOption('DailyLife');
  await page.locator('#startLearning').click();
  await page.waitForFunction(() => document.querySelector('#vocabularyQuestion').textContent === 'guide');
  await page.locator('#setCount').focus();
  await page.keyboard.press('a');
  assert.equal(await page.locator('#vocabularyAnswer').isHidden(), true);
  await page.locator('#setCount').evaluate(element => element.blur());
  await page.keyboard.press('a');
  assert.equal(await page.locator('#vocabularyAnswer').textContent(), '手引き');
  let firstAnswerKey;
  await page.route('**/api/answer', async route => {
    firstAnswerKey=route.request().postDataJSON().idempotency_key;
    const saved=await route.fetch();
    await route.fulfill({status:503,json:{error:'fixture storage error'}});
    assert.equal(saved.status(),200);
  });
  await page.keyboard.press('s');
  await page.waitForFunction(() => document.querySelector('#learningStatus').textContent.includes('保存できませんでした'));
  assert.equal(await page.locator('#vocabularyAnswer').isHidden(), false);
  assert.equal(await page.locator('#rateKnown').isDisabled(), false);
  await page.unroute('**/api/answer');
  const retryResponse=page.waitForResponse(response=>response.url().includes('/api/answer')&&response.request().method()==='POST');
  await page.keyboard.press('s');
  const retry=await retryResponse;
  assert.equal(retry.status(),200);
  assert.equal(retry.request().postDataJSON().idempotency_key,firstAnswerKey);
  assert.equal((await retry.json()).saved,false,'a retried response must not count a second time');
  await page.screenshot({path:'tests/e2e-artifacts/answer-save-error.png',fullPage:true});
});

test('automatic CEFR settings and startup queue are visible and can be stopped', async () => {
  await page.goto('http://127.0.0.1:18765/');
  const startup=await page.evaluate(async()=>await(await fetch('/api/difficulty/auto/status')).json());
  assert.equal(startup.api_key_configured,false);
  assert.equal(startup.job.status,'queued');
  assert.equal(startup.pending_senses,3);
  await page.getByRole('tab').nth(2).click();
  await page.waitForFunction(()=>document.querySelector('#automaticDifficultyStatus').textContent.length>0);
  await page.locator('#automaticDifficultyEnabled').uncheck();
  await page.locator('#saveAutomaticDifficulty').click();
  await page.waitForFunction(async()=>!(await(await fetch('/api/difficulty/auto/status')).json()).settings.enabled);
  await page.locator('#automaticDifficultyEnabled').check();
  await page.locator('#automaticDifficultyLimit').fill('2');
  await page.locator('#automaticDifficultyBudget').fill('0.02');
  await page.locator('#saveAutomaticDifficulty').click();
  await page.waitForFunction(async()=>{const s=await(await fetch('/api/difficulty/auto/status')).json();return s.settings.enabled&&s.settings.per_run_limit===2&&s.settings.daily_budget_usd===0.02;});
});

test('difficulty assessment estimate and background job controls are keyboard and mouse accessible', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await openTab('語彙管理');
  await page.locator('#planDifficulty').click();
  await page.waitForFunction(() => document.querySelector('#difficultyEstimate').textContent.includes('未評価 3 語義'));
  await page.route('**/api/difficulty/start', route => route.fulfill({status:202,json:{job_id:'fixture-difficulty-job'}}));
  await page.route('**/api/jobs?id=fixture-difficulty-job', route => route.fulfill({json:{status:'completed',completed_items:3,total_items:3}}));
  await page.locator('#startDifficulty').click();
  await page.waitForFunction(() => document.querySelector('#difficultyJobStatus').textContent.includes('completed: 3/3'));
  assert.equal(await page.locator('#resumeDifficulty').isDisabled(),true);
});

test('vocabulary and materials can be searched, archived, restored and exported', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await openTab('語彙管理');
  await page.locator('#searchVocabulary').click();
  const materialRow=page.locator(`#materialRows tr[data-material-id="${await materialIdByText('A fixture sentence.')}"]`);
  await materialRow.getByRole('button',{name:'アーカイブ'}).click();
  await page.waitForFunction(()=>document.querySelector('#materialRows').textContent.includes('archived'));
  await materialRow.getByRole('button',{name:'復元'}).click();
  await page.waitForFunction(()=>document.querySelector('#materialRows tr')?.textContent.includes('ready'));
  const download=page.waitForEvent('download');
  await page.locator('#exportMaterials').click();
  assert.equal((await download).suggestedFilename(),'materials.csv');
  await page.locator('#vocabularySearch').fill('take part');
  await page.locator('#searchVocabulary').click();
  const vocabRow=page.locator('#vocabularyRows tr').filter({hasText:'take part'});
  await vocabRow.getByRole('button',{name:'アーカイブ'}).click();
  await page.locator('#includeArchived').check();
  await page.waitForFunction(()=>Array.from(document.querySelectorAll('#vocabularyRows tr')).some(row=>row.textContent.includes('take part')));
  await page.locator('#vocabularyRows tr').filter({hasText:'take part'}).getByRole('button',{name:'復元'}).click();
  await page.waitForFunction(()=>document.querySelector('#vocabularyRows').textContent.includes('take part'));
});

test('saved material lists use the same database records and reload', async () => {
  await page.goto('http://127.0.0.1:18765/#overlap');
  await page.waitForFunction(()=>document.querySelector('#savedList').options.length>0);
  const created=await page.evaluate(async()=>fetch('/api/materials/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'DB only list fixture',text_content:'Not present in practice_data.'})}).then(response=>response.json()));
  const bothLists=await page.evaluate(async()=>[(await (await fetch('/api/materials')).json()).items,(await (await fetch('/api/materials/overlap-list')).json()).items]);
  const expected=bothLists[0].map(item=>item.material_id);
  assert.deepEqual(expected,bothLists[1].map(item=>item.material_id));
  await page.goto('http://127.0.0.1:18765/#manage');
  await page.waitForFunction(expectedCount=>document.querySelectorAll('#materialRows tr[data-material-id]').length===expectedCount,expected.length);
  assert.equal(await page.locator('#materialRows tr').count(),expected.length);
  assert.equal(await page.locator('#materialCount').textContent(),String(expected.length));
  assert.equal(await page.locator(`#materialRows tr[data-material-id="${created.material_id}"]`).count(),1,'database-only materials are included');
  await page.locator('#refreshMaterials').click();
  assert.equal(await page.locator('#materialRows tr').count(),expected.length);
  await page.goto('http://127.0.0.1:18765/#overlap');
  await page.waitForFunction(expectedCount=>document.querySelector('#savedList').options.length===expectedCount,expected.length);
  assert.equal(await page.locator('#savedList option').count(),expected.length);
  assert.equal(await page.locator('#savedMaterialCount').textContent(),`${expected.length}\u4ef6`);
  for(const id of expected)assert.ok(await page.locator(`#savedList option[value="${id}"]`).count(),`overlap shows database material ${id}`);
  await page.locator('#refreshSavedMaterials').click();
  await page.waitForFunction(expectedCount=>document.querySelector('#savedList').options.length===expectedCount,expected.length);
  assert.equal(await page.locator('#savedList option').count(),expected.length);
  const fixtureId=await page.evaluate(async()=>{const items=(await (await fetch('/api/materials/overlap-list')).json()).items;return items.find(item=>item.text_content==='A fixture sentence.').material_id;});
  await page.locator('#savedList').selectOption(fixtureId,{force:true});
  await page.waitForFunction(()=>document.querySelector('#play').disabled===false);
  await page.waitForFunction(()=>document.querySelector('#overlapSource').value==='A fixture sentence.');
  assert.equal(await page.locator('#overlapSource').inputValue(),'A fixture sentence.');
  const managementReload=page.waitForResponse(response=>response.url().endsWith('/api/materials')&&response.ok());
  await page.locator('#tab-manage').click();
  await managementReload;
});

test('overlap material details display database AI summaries without generating them', async () => {
  let summaryCalls=0,fileRowFound=false;
  await page.route('**/api/materials/overlap-list',async route=>{
    const response=await route.fetch(),body=await response.json();
    const saved=body.items.find(item=>item.text_content==='A fixture sentence.');
    fileRowFound=Boolean(saved);
    if(saved)saved.ai_summary='Synthetic AI summary for overlap details.';
    return route.fulfill({response,json:body});
  });
  await page.route('**/api/materials/summarize',route=>{summaryCalls++;return route.continue();});
  await page.reload();
  await page.locator('#tab-overlap').click();
  await page.waitForFunction(()=>document.querySelector('#savedList').options.length>0);
  await page.waitForFunction(()=>document.querySelector('#savedList').options.length>1);
  assert.equal(fileRowFound,true,'imported fixture is present in the canonical overlap list response');
  const fixtureId=await page.evaluate(async()=>{const items=(await (await fetch('/api/materials/overlap-list')).json()).items;return items.find(item=>item.text_content==='A fixture sentence.').material_id;});
  await page.locator('#savedList').selectOption(fixtureId);
  await page.waitForFunction(()=>document.querySelector('#savedMeta').textContent.includes('Synthetic AI summary for overlap details.'));
  const fileMeta=await page.locator('#savedMeta').textContent();
  assert.match(fileMeta,/AI\u8981\u7d04/);
  assert.match(fileMeta,/\u5358\u8a9e\u6570/,'word count and remaining metadata stay visible');
  assert.match(fileMeta,/作成日時: 2026\/10\/24 09:00 JST/,'legacy material creation time is visible in JST');
  assert.doesNotMatch(fileMeta,/A legacy description|\u6559\u6750\u306e\u8aac\u660e/);
  assert.equal(await page.locator('#play').isEnabled(),true,'DB-backed playback remains available');
  const dbOnly=await page.evaluate(async()=>fetch('/api/materials/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'Timestamp DB fixture',text_content:'A database-only timestamp fixture.'})}).then(response=>response.json()));
  await page.locator('#refreshSavedMaterials').click();
  await page.waitForFunction(id=>[...document.querySelector('#savedList').options].some(option=>option.value===id),dbOnly.material_id);
  await page.locator('#savedList').selectOption(dbOnly.material_id,{force:true});
  await page.waitForFunction(()=>document.querySelector('#savedMeta').textContent.includes('作成日時:')&&!document.querySelector('#savedMeta').textContent.includes('作成日時: －'));
  assert.match(await page.locator('#savedMeta').textContent(),/作成日時: .* JST/,'DB-only material creation time is visible in JST');
  assert.equal(summaryCalls,0,'opening saved material details never calls the summary API');
  await page.unroute('**/api/materials/summarize');
  await page.unroute('**/api/materials/overlap-list');
});

test('saved materials keep summaries and edits in SQLite', async () => {
  let calls=0;const summaries=new Map();
  await page.route('**/api/materials',async route=>{
    const response=await route.fetch(),body=await response.json();
    body.items=body.items.map(item=>{const generated=summaries.get(item.material_id);if(!generated)return item;const content=JSON.parse(item.content_json||'{}');content.summary=generated.summary;content.summary_model='fixture-model';return {...item,title:generated.title,summary:generated.summary,content_json:JSON.stringify(content)};});
    return route.fulfill({response,json:body});
  });
  await page.route('**/api/materials/summarize',async route=>{
    calls++;
    const id=route.request().postDataJSON().material_id;
    if(calls===3)return route.fulfill({status:502,json:{error:'fixture API failure'}});
    const title=`Fixture generated title ${calls}`,summary=`Synthetic summary ${calls}`;summaries.set(id,{title,summary});
    return route.fulfill({status:200,json:{material_id:id,title,summary,model:'fixture-model',cost:{usd:0.00001}}});
  });
  await page.goto('http://127.0.0.1:18765/#manage');
  const ids=await page.evaluate(async()=>{const items=(await (await fetch('/api/materials')).json()).items;const noSummary=items.find(item=>item.text_content.includes('without a generated summary'));const second=items.find(item=>item.text_content.includes('Another synthetic sentence'));const editable=items.find(item=>item.text_content==='Editable audio fixture.');return [noSummary,second,editable];});
  await page.locator('#vocabularySearch').fill('');
  await page.locator('#searchVocabulary').click();
  await page.waitForFunction(()=>document.querySelector('#materialRows').textContent.includes('AI\u8981\u7d04\u306f\u307e\u3060\u3042\u308a\u307e\u305b\u3093\u3002'));
  assert.equal(calls,0,'loading material metadata never calls the summary API');
  const row=page.locator(`#materialRows tr[data-material-id="${ids[0].material_id}"]`);
  await row.getByRole('button',{name:/AI\u8981\u7d04.*\u751f\u6210/}).click();
  await page.waitForFunction(()=>!document.querySelector('#learningStatus').textContent.includes('\u751f\u6210\u3057\u3066\u3044\u307e\u3059'));
  assert.equal(calls,1,await page.locator('#learningStatus').textContent());
  assert.match(await row.locator('.material-summary').textContent(),/Synthetic summary 1/);
  assert.equal(await row.locator('strong').textContent(),'Fixture generated title 1');
  assert.equal(await row.getByRole('button',{name:/AI\u8981\u7d04.*\u66f4\u65b0/}).count(),1);
  await row.getByRole('button',{name:/AI\u8981\u7d04.*\u66f4\u65b0/}).click();
  await page.waitForFunction(id=>document.querySelector(`#materialRows tr[data-material-id="${id}"]`)?.textContent.includes('Synthetic summary 2'),ids[0].material_id);
  const failedRow=page.locator(`#materialRows tr[data-material-id="${ids[1].material_id}"]`);
  await failedRow.getByRole('button',{name:/AI\u8981\u7d04.*\u751f\u6210/}).click();
  await page.waitForFunction(()=>document.querySelector('#learningStatus').textContent.includes('fixture API failure'));
  assert.match(await failedRow.locator('.material-summary').textContent(),/AI\u8981\u7d04.*\u307e\u3060/);
  assert.equal(calls,3);
  const editableRow=page.locator(`#materialRows tr[data-material-id="${ids[2].material_id}"]`);
  await page.evaluate(()=>{const values=['Edited source title','Edited source body.'];window.prompt=()=>values.shift();});
  const editResponse=page.waitForResponse(response=>response.url().endsWith('/api/materials/update')&&response.ok());
  await editableRow.getByRole('button',{name:/\u7de8\u96c6/}).click();
  await editResponse;
  await page.waitForFunction(id=>document.querySelector(`#materialRows tr[data-material-id="${id}"] strong`)?.textContent==='Edited source title',ids[2].material_id);
  summaries.delete(ids[2].material_id);
  await page.locator('#tab-overlap').click();
  await page.waitForFunction(id=>[...document.querySelector('#savedList').options].some(option=>option.value===id),ids[2].material_id);
  const editedMaterial=await page.evaluate(async id=>(await (await fetch('/api/materials/overlap-list')).json()).items.find(item=>item.material_id===id),ids[2].material_id);
  assert.equal(editedMaterial.audio_path,null);
  assert.equal(editedMaterial.file,null);
  await page.locator('#refreshSavedMaterials').click();
  await page.waitForFunction(id=>[...document.querySelector('#savedList').options].some(option=>option.value===id),ids[2].material_id);
  const freshEdited=await page.evaluate(async id=>(await (await fetch('/api/materials/overlap-list')).json()).items.find(item=>item.material_id===id),ids[2].material_id);
  assert.equal(freshEdited.text_content,'Edited source body.');
  await page.locator('#savedList').selectOption(ids[2].material_id,{force:true});
  await page.waitForFunction(()=>document.querySelector('#overlapSource').value==='Edited source body.'&&document.querySelector('#play').disabled===true);
  assert.equal(await page.locator('#play').isDisabled(),true,'edited body detaches outdated audio');
  assert.equal(await page.locator('#overlapSource').inputValue(),'Edited source body.');
  await page.unroute('**/api/materials/summarize');
  await page.unroute('**/api/materials');
});

test('vocabulary management sorts and pages 50 rows while retaining filters', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await openTab('語彙管理');
  await page.waitForFunction(()=>document.querySelector('#vocabularyPageStatus').textContent.includes('128件'));
  assert.equal(await page.locator('#vocabularyRows tr').count(),50);
  assert.equal(await page.locator('#vocabularyPreviousPage').isDisabled(),true);
  await page.locator('#vocabularyNextPage').click();
  await page.waitForFunction(()=>document.querySelector('#vocabularyPageStatus').textContent.startsWith('51–100'));
  assert.equal(await page.locator('#vocabularyRows tr').count(),50);
  await page.locator('[data-vocab-sort="japanese"]').click();
  await page.waitForFunction(()=>document.querySelector('#vocabularyPageStatus').textContent.startsWith('1–50')&&document.querySelector('[data-sort-header="japanese"]').getAttribute('aria-sort')==='ascending');
  await page.locator('[data-vocab-sort="tags"]').click();
  await page.waitForFunction(()=>document.querySelector('[data-sort-header="tags"]').getAttribute('aria-sort')==='ascending');
  await page.locator('[data-vocab-sort="english"]').click();
  await page.waitForFunction(()=>document.querySelector('[data-sort-header="english"]').getAttribute('aria-sort')==='ascending');
  const ascending=await page.locator('#vocabularyRows tr:first-child td:first-child').textContent();
  await page.locator('[data-vocab-sort="english"]').click();
  await page.waitForFunction(first=>document.querySelector('[data-sort-header="english"]').getAttribute('aria-sort')==='descending'&&document.querySelector('#vocabularyRows tr:first-child td:first-child').textContent!==first,ascending);
  assert.equal(await page.locator('#vocabularyRows tr:first-child td:first-child').textContent(),'take part');
  await page.locator('#vocabularySearch').fill('Pageword 12');
  await page.locator('#searchVocabulary').click();
  await page.waitForFunction(()=>document.querySelector('#vocabularyPageStatus').textContent.includes('5件'));
  assert.equal(await page.locator('#vocabularyRows tr').count(),5);
  await page.locator('#vocabularySearch').fill('');
  await page.locator('#searchVocabulary').click();
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'vocabulary management should fit mobile viewport');
});

test('major page sections can be collapsed independently with mouse and keyboard', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await openTab('語彙管理');
  const management = page.locator('#vocabularyManagementSection');
  assert.equal(await management.evaluate(node => node.open), true);
  await page.locator('#managedMaterialsSection > summary').click();
  assert.equal(await page.locator('#managedMaterialsSection').evaluate(node => node.open), false);
  assert.equal(await page.locator('#difficultyCard').evaluate(node => node.open), true);
  const materialsSummary = page.locator('#managedMaterialsSection > summary');
  await materialsSummary.focus();
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#managedMaterialsSection').evaluate(node => node.open), true);
  await page.locator('#vocabularyManagementSection > summary').click();
  assert.equal(await management.evaluate(node => node.open), false);
  await page.locator('#vocabularyManagementSection > summary').click();
  assert.equal(await page.locator('#vocabularyRows').isVisible(), true);
  assert.equal(await page.locator('#materialRows').isVisible(), true);
});

test('vocabulary page number jumps directly and clamps to the available range', async () => {
  const requestedPages=[];
  await page.route('**/api/vocabulary?*',async route=>{
    const url=new URL(route.request().url()),current=Number(url.searchParams.get('page')||1);
    requestedPages.push(current);
    const items=Array.from({length:Math.min(50,16920-(current-1)*50)},(_,index)=>({vocab_id:`mock-${(current-1)*50+index+1}`,english:`Word ${(current-1)*50+index+1}`,meaning:'意味',part_of_speech:'noun',tags:'',genre_tags:'',difficulty_level:null,archived_at_utc:null}));
    await route.fulfill({json:{items,total:16920,page:current,page_size:50,pages:339,categories:[]}});
  });
  await page.goto('http://127.0.0.1:18765/');
  await openTab('語彙管理');
  await page.waitForFunction(()=>document.querySelector('#vocabularyPageCount').textContent==='339');
  const input=page.locator('#vocabularyPageInput');
  await input.fill('5');await input.press('Enter');
  await page.waitForFunction(()=>document.querySelector('#vocabularyPageStatus').textContent.startsWith('201–250'));
  assert.equal(await input.inputValue(),'5');
  assert.ok(requestedPages.includes(5),'page five should be sent to the server');
  await input.fill('9999');await input.press('Enter');
  await page.waitForFunction(()=>document.querySelector('#vocabularyPageStatus').textContent.startsWith('16901–16920'));
  assert.equal(await input.inputValue(),'339','out-of-range page values clamp to the final page');
  await page.unroute('**/api/vocabulary?*');
});

test('candidate deduplication explains exact and in-batch matches and honors the chosen cosine threshold', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await openTab('語彙追加');
  await page.locator('#candidateSource').fill('TAKE PART | 参加する | verb\nNovel | 新規 | noun\nnovel | 新規 | noun');
  await page.locator('#extractCandidates').click();
  await page.waitForFunction(()=>document.querySelectorAll('#candidateRows input').length===3);
  assert.match(await page.locator('#candidateRows').textContent(),/完全一致/);
  assert.match(await page.locator('#candidateRows').textContent(),/表記重複/);
  await page.locator('#similarityThreshold').fill('0.91');
  await page.route('**/api/candidates/compare',async route=>{
    assert.equal(route.request().postDataJSON().threshold,.91);
    await route.fulfill({json:{excluded:true,reason:'cosine_similarity',matched_english:'novelty',similarity:.932,threshold:.91}});
  });
  await page.locator('#candidateRows button').first().click();
  await page.waitForFunction(()=>document.querySelector('#candidateRows').textContent.includes('0.932'));
});

test('study set generation exposes partial progress and resumes the same job after failure', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await openTab('オーバーラッピング');
  await page.waitForFunction(()=>document.querySelector('#studySetCategory').options.length>1);
  await page.locator('#studySetCategory').selectOption('WorkAndCareer');
  await page.locator('#studySetDirection').selectOption('en_to_ja');
  await page.locator('#studySetCount').fill('2');
  await page.locator('#studySetMasteryStatus').selectOption('all');
  await page.locator('#studySetIncludeUnstudied').check();
  await page.locator('#studySetRecentAttempts').fill('');
  await page.locator('#studySetMaxRecentAccuracy').fill('');
  await page.locator('#studySetIncludeInsufficientHistory').uncheck();
  await page.locator('#studySetDifficulty').selectOption('');
  await page.locator('#planStudySet').click();
  await page.waitForFunction(()=>document.querySelectorAll('#studySetPlan input[type=checkbox]').length===2);
  await page.locator('#studySetMode').selectOption('per_vocabulary');
  assert.equal(await page.locator('#studySetPlan input:checked').count(),2);
  let resumed=false;
  let jobPolls=0;
  let startIds=[];
  await page.route('**/api/study-set/generate',route=>{const request=route.request().postDataJSON();startIds=request.vocab_ids;assert.equal(request.generation_mode,'per_vocabulary');return route.fulfill({status:202,json:{job_id:'fixture-retry-job'}});});
  await page.route('**/api/study-set/resume',async route=>{resumed=true;await route.fulfill({status:202,json:{job_id:'fixture-retry-job'}});});
  await page.route('**/api/jobs?id=fixture-retry-job',async route=>{
    if(!resumed){jobPolls++;const error='\u6307\u5b9a\u8a9e\u5f59\u3092\u542b\u307e\u306a\u3044\u751f\u6210\u6587\u304c\u3042\u308a\u307e\u3059: rave about \uff5e';const missing=jobPolls===1?['rave about \uff5e']:error;await route.fulfill({json:{status:'failed',completed_items:1,total_items:2,error,payload:{vocab_ids:['e2e-1','e2e-2']},result:{missing_targets:missing}}});return;}
    const text='The team took part in a useful program.';
    await route.fulfill({json:{status:'completed',completed_items:2,total_items:2,payload:{vocab_ids:['e2e-1','e2e-2']},result:{text,groups:[[text]],used_vocab_ids:['e2e-1','e2e-2'],unused_vocab_ids:[],usages:[],model:'fixture-model',usage:{input_tokens:15,output_tokens:10},request_count:2}}});
  });
  await page.locator('#generateStudySet').click();
  await page.waitForFunction(()=>!document.querySelector('#resumeStudySet').hidden);
  assert.match(await page.locator('#studySetStatus').textContent(),/完了済み 1\/2/);
  assert.match(await page.locator('#studySetStatus').textContent(),/\u6307\u5b9a\u8a9e\u5f59\u3092\u542b\u307e\u306a\u3044\u751f\u6210\u6587\u304c\u3042\u308a\u307e\u3059: rave about \uff5e/);
  assert.match(await page.locator('#studySetStatus').textContent(),/\u672a\u751f\u6210\u306e\u5bfe\u8c61\u8a9e: rave about \uff5e/);
  await page.reload();
  assert.equal(await page.locator('#studySetMode').inputValue(),'per_vocabulary');
  await page.waitForFunction(()=>!document.querySelector('#resumeStudySet').hidden);
  assert.match(await page.locator('#studySetStatus').textContent(),/\u6307\u5b9a\u8a9e\u5f59\u3092\u542b\u307e\u306a\u3044\u751f\u6210\u6587\u304c\u3042\u308a\u307e\u3059: rave about \uff5e/);
  assert.doesNotMatch(await page.locator('#studySetStatus').textContent(),/\u672a\u751f\u6210\u306e\u5bfe\u8c61\u8a9e/);
  assert.ok(await page.evaluate(()=>localStorage.getItem('englishOverlapStudySetJob')),'generation job state was not persisted');
  assert.equal(await page.locator('#resumeStudySet').isDisabled(),false);
  assert.equal(await page.locator('#resumeStudySet').evaluate(button=>typeof button.onclick),'function');
  await page.locator('#resumeStudySet').click();
  await page.waitForTimeout(300);
  assert.equal(startIds.length,2);
  assert.equal(resumed,true,'resume endpoint was not called: '+await page.locator('#studySetStatus').textContent());
  await page.waitForFunction(()=>document.querySelector('#source').value.includes('took part'),{timeout:5000}).catch(async error=>{throw new Error(await page.locator('#studySetStatus').textContent()+': '+error.message);});
  assert.equal(resumed,true);
  assert.equal(await page.locator('#saveStudySet').count(),0);
});

test('React feature tabs expose all five areas and support arrow-key navigation', async () => {
  await page.goto('http://127.0.0.1:18765/');
  assert.equal(await page.title(),'English Quest');
  assert.equal(await page.locator('header h1').textContent(),'English Quest');
  const tabs=page.getByRole('tab');
  assert.deepEqual(await tabs.allTextContents(),['オーバーラッピング', '語彙練習', '語彙管理（閲覧・編集）', '語彙追加', 'データベース管理']);
  await tabs.first().focus();
  await page.keyboard.press('ArrowRight');
  assert.equal(await page.getByRole('tab',{name:'語彙練習'}).getAttribute('aria-selected'),'true');
  assert.equal(await page.locator('#panel-practice').isVisible(),true);
  await page.keyboard.press('ArrowRight');
  assert.equal(await page.getByRole('tab',{name:'語彙管理'}).getAttribute('aria-selected'),'true');
  await page.keyboard.press('End');
  assert.equal(await page.getByRole('tab',{name:'データベース管理'}).getAttribute('aria-selected'),'true');
  await page.keyboard.press('Home');
  assert.equal(await page.getByRole('tab',{name:'オーバーラッピング'}).getAttribute('aria-selected'),'true');
});

test('UX review captures all feature areas at desktop and mobile widths', async () => {
  await page.setViewportSize({width:1280,height:900});
  await page.goto('http://127.0.0.1:18765/');
  const tabs=page.getByRole('tab');
  const ids=['overlap','practice','manage','add','database'];
  for(let index=0;index<ids.length;index++){
    await tabs.nth(index).click();
    await page.waitForFunction(id=>document.querySelector(`#tab-${id}`).getAttribute('aria-selected')==='true',ids[index]);
    if(ids[index]==='manage')await page.waitForFunction(()=>document.querySelector('#vocabularyRows').children.length>0);
    if(ids[index]==='database')await page.waitForFunction(()=>document.querySelector('#databaseStatus').textContent.includes('正常'));
    const width=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll('body *')].map(node=>({tag:node.tagName,id:node.id,cls:node.className,right:Math.round(node.getBoundingClientRect().right),width:Math.round(node.getBoundingClientRect().width)})).filter(node=>node.right>innerWidth+2).slice(0,8)}));
    assert.ok(width.document<=width.viewport,`${ids[index]} desktop overflow: ${JSON.stringify(width)}`);
    await page.screenshot({path:`tests/e2e-artifacts/ux-${ids[index]}-desktop.png`,fullPage:true});
  }
  await page.setViewportSize({width:390,height:844});
  for(let index=0;index<ids.length;index++){
    await tabs.nth(index).click();
    const width=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll('body *')].map(node=>({tag:node.tagName,id:node.id,cls:node.className,right:Math.round(node.getBoundingClientRect().right),width:Math.round(node.getBoundingClientRect().width)})).filter(node=>node.right>innerWidth+2).slice(0,8)}));
    assert.ok(width.document<=width.viewport,`${ids[index]} mobile overflow: ${JSON.stringify(width)}`);
    await page.screenshot({path:`tests/e2e-artifacts/ux-${ids[index]}-mobile.png`,fullPage:true});
  }
});

test('main content and overlap columns expand with wide screens and stack on mobile', async () => {
  await page.setViewportSize({width:1800,height:1000});
  await page.goto('http://127.0.0.1:18765/#overlap');
  const wide=await page.evaluate(()=>({main:document.querySelector('main').getBoundingClientRect().width,columns:getComputedStyle(document.querySelector('.overlap-workspace')).gridTemplateColumns}));
  assert.ok(wide.main>1700,`wide main should use available width: ${JSON.stringify(wide)}`);
  const wideSide=parseFloat(wide.columns.split(' ').at(-1));
  await page.setViewportSize({width:1440,height:900});
  const medium=await page.evaluate(()=>({main:document.querySelector('main').getBoundingClientRect().width,columns:getComputedStyle(document.querySelector('.overlap-workspace')).gridTemplateColumns}));
  const mediumSide=parseFloat(medium.columns.split(' ').at(-1));
  assert.ok(medium.main>1240&&medium.main<wide.main,`main width should follow viewport: ${JSON.stringify(medium)}`);
  assert.ok(wideSide>mediumSide,'settings sidebar should grow on wider displays');
  await page.setViewportSize({width:390,height:844});
  const narrow=await page.evaluate(()=>({columns:getComputedStyle(document.querySelector('.overlap-workspace')).gridTemplateColumns,viewport:innerWidth,document:document.documentElement.scrollWidth}));
  assert.equal(narrow.columns.split(' ').length,1,'overlap columns should stack on narrow screens');
  assert.ok(narrow.document<=narrow.viewport,`mobile layout should not overflow: ${JSON.stringify(narrow)}`);
});

test('database tab displays status and confirms safe backup restoration', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await openTab('\u30c7\u30fc\u30bf\u30d9\u30fc\u30b9\u7ba1\u7406');
  await page.waitForFunction(()=>document.querySelector('#databaseStatus').textContent.includes('\u6b63\u5e38'));
  assert.match(await page.locator('.db-facts').textContent(),/\u30b9\u30ad\u30fc\u30de/);
  const backupResponse=page.waitForResponse(response=>response.url().includes('/api/database/backup')&&response.ok());
  await page.getByRole('button',{name:'\u30d0\u30c3\u30af\u30a2\u30c3\u30d7\u3092\u4f5c\u6210'}).click();
  const backup=await backupResponse;
  assert.equal(backup.status(),201);
  await page.waitForFunction(()=>document.querySelector('select[aria-label="\u5fa9\u5143\u3059\u308b\u30d0\u30c3\u30af\u30a2\u30c3\u30d7"]').value!=='');
  const restore=page.getByRole('button',{name:'\u78ba\u8a8d\u3057\u3066\u5fa9\u5143'});
  assert.equal(await restore.isDisabled(),false);
  page.once('dialog', dialog => void dialog.accept());
  const restoreResponse=page.waitForResponse(response=>response.url().includes('/api/database/restore')&&response.request().method()==='POST');
  await restore.click();
  const restored=await restoreResponse;
  assert.equal(restored.status(),200,await restored.text());
  await page.waitForFunction(()=>document.querySelector('#databaseStatus').textContent.includes('\u5fa9\u5143\u3057\u307e\u3057\u305f'));
  const listing=await page.evaluate(async()=>await(await fetch('/api/database/backups')).json());
  assert.ok(listing.items.length>=2,'restore must preserve a safety backup');
});


test('unsaved text edits trigger a browser leave warning', async () => {
  await page.goto('http://127.0.0.1:18765/');
  await page.locator('#overlapSource').fill('Unsaved fixture sentence.');
  const warned = await page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  });
  assert.equal(warned, true);
});

test('last incorrect practice uses eligible total and shows O/X history', async () => {
  await page.goto('http://127.0.0.1:18765/#practice');
  await page.waitForFunction(()=>document.querySelector('#learningCategory').options.length>1);
  await page.locator('#learningCategory').selectOption('DailyLife');
  await page.locator('#setCount').fill('1000');
  await page.locator('#startLearning').click();
  await page.waitForFunction(()=>document.querySelector('#vocabularyQuestion').textContent==='guide');
  assert.match(await page.locator('#learningProgress').textContent(),/1 \/ 1/);
  await page.locator('#revealAnswer').click();
  await page.locator('#rateAgain').click();
  await page.waitForFunction(()=>document.querySelector('#learningProgress').textContent.includes('\u5b8c\u4e86'));
  await page.locator('#lastAttemptIncorrect').check();
  await page.locator('#startLearning').click();
  await page.waitForFunction(()=>document.querySelector('#vocabularyQuestion').textContent==='guide');
  assert.match(await page.locator('#learningProgress').textContent(),/1 \/ 1/);
  assert.match(await page.locator('#vocabularyHistory').textContent(),/X/);
  assert.equal(await page.locator('#vocabularyHistory [aria-label="\u4e0d\u6b63\u89e3"]').count()>0,true);
});


test('due review mode requests only due history and keeps normal practice selectable', async () => {
  await page.goto('http://127.0.0.1:18765/#practice');
  let observed;
  let dueItems=[{vocab_id:'due-fixture',sense_id:1,english:'due fixture',meaning:'review word',history:[]}];
  await page.route('**/api/next-question?**',async route=>{
    observed=new URL(route.request().url()).searchParams;
    await route.fulfill({json:{items:dueItems}});
  });
  await page.locator('#reviewMode').selectOption('due');
  assert.equal(await page.locator('#dueReviewHint').isVisible(),true);
  assert.equal(await page.locator('.standard-only').first().isVisible(),false);
  await page.locator('#startLearning').click();
  await page.waitForFunction(()=>document.querySelector('#vocabularyQuestion').textContent==='due fixture');
  assert.equal(observed.get('due_only'),'true');
  assert.equal(observed.get('count'),await page.locator('#setCount').inputValue());
  dueItems=[];
  await page.locator('#startLearning').click();
  await page.waitForFunction(()=>document.querySelector('#vocabularyQuestion').textContent.includes('\u5fa9\u7fd2\u671f\u9650'));
  await page.locator('#reviewMode').selectOption('standard');
  assert.equal(await page.locator('.standard-only').first().isVisible(),true);
  assert.equal(await page.locator('#dueReviewHint').isVisible(),false);
  await page.unroute('**/api/next-question?**');
});

test('vocabulary focus mode hides surrounding UI and exits by button or Escape', async () => {
  await page.goto('http://127.0.0.1:18765/#practice');
  await page.route('**/api/next-question?**',async route=>route.fulfill({json:{items:[{vocab_id:'focus-fixture',sense_id:1,english:'focus fixture',meaning:'focus meaning',history:[]}]}}));
  await page.locator('#reviewMode').selectOption('standard');
  await page.locator('#masteryStatus').selectOption('all');
  await page.locator('#startLearning').click();
  await page.waitForFunction(()=>document.querySelector('#vocabularyQuestion').textContent==='focus fixture');
  await page.locator('#focusModeToggle').click();
  assert.equal(await page.locator('#focusModeToggle').getAttribute('aria-pressed'),'true');
  assert.equal(await page.locator('#vocabularyStage').isVisible(),true);
  assert.equal(await page.locator('#revealAnswer').isVisible(),true);
  assert.equal(await page.locator('#exitFocusMode').isVisible(),true);
  assert.equal(await page.locator('#tab-practice').isVisible(),false);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#focusModeToggle').getAttribute('aria-pressed'),'false');
  assert.equal(await page.locator('#tab-practice').isVisible(),true);
  await page.locator('#focusModeToggle').click();
  await page.locator('#exitFocusMode').click();
  assert.equal(await page.locator('#focusModeToggle').getAttribute('aria-pressed'),'false');
  await page.unroute('**/api/next-question?**');
});

test('dashboard cumulative goals track overlap hours and distinct vocabulary across periods', async () => {
  await page.goto('http://127.0.0.1:18765/#dashboard');
  await page.waitForFunction(()=>document.querySelector('#learningGoalsProgress')?.textContent.includes('目標未設定'));
  const baseline=await page.evaluate(async()=>await (await fetch('/api/learning-goals')).json());
  await page.locator('#overlapGoalHours').fill('0.5');
  await page.locator('#vocabularyGoalCount').fill('1');
  await page.locator('#saveLearningGoals').click();
  await page.waitForFunction(()=>document.querySelector('#learningGoalsStatus').textContent.includes('保存しました'));
  const added=await page.evaluate(async()=>{
    const [questions,stats]=await Promise.all([fetch('/api/next-question?direction=en_to_ja&count=1000').then(response=>response.json()),fetch('/api/statistics?days=all').then(response=>response.json())]);
    const neverAnswered=new Set(stats.vocabulary_performance.filter(item=>item.attempts===0).map(item=>item.vocab_id));
    const unstudied=questions.items.filter(item=>neverAnswered.has(item.vocab_id)).slice(0,2);
    for(const [index,item] of unstudied.entries())await fetch('/api/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vocab_id:item.vocab_id,sense_id:item.sense_id,direction:'en_to_ja',rating:'known',duration_seconds:1,idempotency_key:`goal-e2e-${index}-${crypto.randomUUID()}`})});
    const session=await (await fetch('/api/overlap/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({material_id:'goal-e2e'})})).json();
    await fetch('/api/overlap/activity',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:session.session_id,material_id:'goal-e2e',duration_seconds:1800,idempotency_key:crypto.randomUUID()})});
    window.dispatchEvent(new CustomEvent('english-overlap-activity-saved'));
    return {vocabularyCount:unstudied.length,progress:await (await fetch('/api/learning-goals')).json()};
  });
  assert.equal(added.vocabularyCount,2,'two previously unstudied fixture words should advance distinct vocabulary progress');
  await page.waitForFunction(()=>document.querySelector('#overlapGoalProgress')?.value===100&&document.querySelector('#vocabularyGoalProgress')?.value===100);
  const goalText=await page.locator('#learningGoalsProgress').textContent();
  assert.ok(goalText.includes(`現在 ${(added.progress.overlap_seconds/3600).toFixed(2)}時間 / 目標 0.5時間`));
  assert.ok(goalText.includes(`現在 ${baseline.learned_vocabulary_count+added.vocabularyCount}語 / 目標 1語`));
  assert.equal(await page.locator('#vocabularyGoalProgress').getAttribute('max'),'100');
  await page.locator('#statisticsRange').selectOption('7');
  await page.waitForFunction(()=>document.querySelector('#statisticsPanel').textContent.includes('7日間'));
  assert.equal(await page.locator('#overlapGoalProgress').evaluate(element=>element.value),100,'period selection does not change lifetime goal progress');
  await page.locator('#overlapGoalHours').fill('');
  await page.locator('#saveLearningGoals').click();
  await page.waitForFunction(()=>!document.querySelector('#overlapGoalProgress'));
  assert.equal(await page.locator('#vocabularyGoalProgress').evaluate(element=>element.value),100,'clearing one target preserves the other');
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#vocabularyGoalProgress')?.value===100);
  assert.equal(await page.locator('#vocabularyGoalCount').inputValue(),'1','targets persist across page reloads');
  await page.locator('#vocabularyGoalCount').fill('');
  await page.locator('#saveLearningGoals').click();
  await page.waitForFunction(()=>document.querySelector('#learningGoalsProgress').textContent.includes('目標未設定'));
});
test('similarity index action processes every missing sense in batches with visible progress', async () => {
  let remaining=205;const batchSizes=[];
  await page.route('**/api/embeddings/plan',route=>route.fulfill({json:{missing_count:remaining,estimated_usd:0.01,model:'fixture-model',note:'fixture'}}));
  await page.route('**/api/embeddings/index',async route=>{
    const body=route.request().postDataJSON();assert.equal(body.limit,100);
    const indexed=Math.min(body.limit,remaining);batchSizes.push(indexed);remaining-=indexed;
    await new Promise(resolve=>setTimeout(resolve,100));
    await route.fulfill({json:{indexed,remaining,model:'fixture-model'}});
  });
  await page.goto('http://127.0.0.1:18765/#add');
  await page.waitForFunction(()=>document.querySelector('#indexEmbeddings')?.disabled===false);
  await page.locator('#indexEmbeddings').click();
  await page.waitForFunction(()=>document.querySelector('#indexEmbeddings').disabled===true);
  assert.equal(await page.locator('#indexEmbeddings').isDisabled(),true,'duplicate batches cannot start concurrently');
  assert.equal(await page.locator('#embeddingProgress').isVisible(),true);
  await page.waitForFunction(()=>document.querySelector('#embeddingProgressText').textContent.includes('205 \u8a9e\u7fa9')&&document.querySelector('#embeddingProgressText').textContent.includes('\u5b8c\u4e86'));
  assert.deepEqual(batchSizes,[100,100,5]);
  assert.equal(await page.locator('#embeddingProgress').evaluate(node=>node.value),205);
  assert.equal(await page.locator('#indexEmbeddings').isDisabled(),true,'completed indexing cannot be started again');
  await page.waitForFunction(()=>document.querySelector('#embeddingEstimate').textContent.includes('fixture-model'));
  await page.unroute('**/api/embeddings/plan');await page.unroute('**/api/embeddings/index');
});

test('similarity indexing keeps completed batches and resumes after a failed batch', async () => {
  let remaining=105,failOnce=true;
  await page.route('**/api/embeddings/plan',route=>route.fulfill({json:{missing_count:remaining,estimated_usd:0.001,model:'fixture-model',note:'fixture'}}));
  await page.route('**/api/embeddings/index',async route=>{
    if(failOnce){failOnce=false;remaining=5;await route.fulfill({json:{indexed:100,remaining,model:'fixture-model'}});return;}
    await route.abort('failed');
  });
  await page.goto('http://127.0.0.1:18765/#add');
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#indexEmbeddings')?.disabled===false);
  await page.locator('#indexEmbeddings').click();
  await page.waitForFunction(()=>document.querySelector('#embeddingProgressText').textContent.includes('\u6b8b\u308a 5'));
  assert.equal(await page.locator('#indexEmbeddings').isDisabled(),false,'remaining work is retryable');
  await page.unroute('**/api/embeddings/index');
  await page.route('**/api/embeddings/index',route=>{remaining=0;return route.fulfill({json:{indexed:5,remaining,model:'fixture-model'}});});
  await page.locator('#indexEmbeddings').click();
  await page.waitForFunction(()=>document.querySelector('#embeddingProgressText').textContent.includes('5 \u8a9e\u7fa9')&&document.querySelector('#embeddingProgressText').textContent.includes('\u5b8c\u4e86'));
  assert.equal(await page.locator('#indexEmbeddings').isDisabled(),true);
  await page.unroute('**/api/embeddings/plan');await page.unroute('**/api/embeddings/index');
});

test('vocabulary preview batches similarity checks and shows per-batch progress', async () => {
  let savedCalls=0,compareCalls=0;const batchSizes=[];
  const fixtureWords=Array.from({length:125},(_,index)=>({word:`preview-word-${index}`,meaning:`meaning-${index}`,part_of_speech:'noun'}));
  await page.route('**/saved',route=>{savedCalls++;return route.fulfill({json:[{material_id:'preview-material',title:'Preview fixture',summary:'Synthetic vocabulary'}]});});
  await page.route('**/saved-data*',route=>route.fulfill({json:{title:'Preview fixture',blocks:[{vocabulary:fixtureWords}]}}));
  await page.route('**/api/candidates/create',async route=>{
    const rows=route.request().postDataJSON().source.split('\n').map((line,index)=>{const [english,meaning,part_of_speech]=line.split(' | ');return {candidate_id:`preview-${index}`,english,meaning,part_of_speech};});
    await route.fulfill({json:{batch_id:'preview-batch',items:rows}});
  });
  await page.route('**/api/candidates/compare-batch',async route=>{
    compareCalls++;const request=route.request().postDataJSON();batchSizes.push(request.candidate_ids.length);assert.equal(request.threshold,0.8);
    if(compareCalls===1)await new Promise(resolve=>setTimeout(resolve,150));
    await route.fulfill({json:{job_id:`preview-job-${compareCalls}`,items:request.candidate_ids.map(id=>{const index=Number(id.split('-')[1]);const excluded=index===0;return {candidate_id:id,excluded,reason:excluded?'cosine_similarity':null,matched_vocab_id:excluded?'fixture-vocab':null,matched_english:excluded?'similar word':null,similarity:excluded?.94:null,similar_matches:Array.from({length:4},(_,matchIndex)=>({vocab_id:`near-${index}-${matchIndex}`,english:`near-${index}-${matchIndex+1}`,similarity:.72-matchIndex*.03})),threshold:.8,model:'fixture-model'};}),model:'fixture-model'}});
  });
  await page.goto('http://127.0.0.1:18765/#add');
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#practiceDataSource').options.length===2);
  await page.locator('#practiceDataSource').selectOption('preview-material');
  await page.locator('#previewPracticeVocabulary').click();
  await page.waitForFunction(()=>document.querySelector('#previewPracticeVocabulary').disabled===true);
  await page.waitForFunction(()=>document.querySelector('#practiceVocabularyProgress').hidden===false);
  assert.equal(await page.locator('#practiceVocabularyProgress').isVisible(),true);
  await page.waitForFunction(()=>document.querySelector('#practiceVocabularyProgress').value===125);
  assert.equal(await page.locator('#candidateRows input[type="checkbox"]').count(),125);
  assert.deepEqual(batchSizes,[50,50,25]);
  assert.equal(compareCalls,3,'one server call handles each group instead of one call per vocabulary item');
  assert.equal(await page.locator('#practiceVocabularyProgress').evaluate(node=>node.value),125);
  const previewText=await page.locator('#candidateRows').textContent();
  assert.ok(previewText.includes('\u8ffd\u52a0\u5019\u88dc \u00b7 \u985e\u4f3c\u8a9e: near-1-1 (0.720), near-1-2 (0.690), near-1-3 (0.660)'));
  assert.ok(previewText.includes('near-0-1 (0.720)'),'similar words also appear for a threshold-excluded candidate');
  assert.ok(!previewText.includes('near-1-4'),'only the nearest three words are displayed');
  assert.equal(await page.locator('#registerCandidates').isEnabled(),true);
  await page.unroute('**/saved');await page.unroute('**/saved-data*');await page.unroute('**/api/candidates/create');await page.unroute('**/api/candidates/compare-batch');
});

test('candidate registration blocks duplicate clicks and can retry after a failed request', async () => {
  let selectCalls=0;
  await page.route('**/api/candidates/create',route=>route.fulfill({json:{batch_id:'registration-batch',items:[{candidate_id:'registration-candidate',english:'registration-word',meaning:'\u767b\u9332\u8a9e',part_of_speech:'noun'}]}}));
  await page.route('**/api/candidates/select',async route=>{
    selectCalls++;
    await new Promise(resolve=>setTimeout(resolve,200));
    if(selectCalls===1)return route.fulfill({status:503,json:{error:'fixture database busy'}});
    return route.fulfill({json:{created_vocab_ids:['registration-vocab']}});
  });
  await page.goto('http://127.0.0.1:18765/#add');
  await page.locator('#candidateSource').fill('registration-word | \u767b\u9332\u8a9e | noun');
  await page.locator('#extractCandidates').click();
  await page.waitForFunction(()=>document.querySelector('#candidateRows input[type="checkbox"]'));
  await page.locator('#registerCandidates').click();
  await page.waitForFunction(()=>document.querySelector('#registerCandidates').disabled===true);
  await page.evaluate(()=>document.getElementById('registerCandidates').onclick());
  assert.equal(selectCalls,1,'a second handler invocation while pending must not send another request');
  await page.waitForFunction(()=>document.querySelector('#learningStatus').textContent.includes('fixture database busy'));
  assert.equal(await page.locator('#registerCandidates').isEnabled(),true,'failed request restores the retry button');
  await page.locator('#registerCandidates').click();
  await page.waitForFunction(()=>document.querySelector('#learningStatus').textContent.includes('1\u4ef6\u3092\u767b\u9332\u3057\u307e\u3057\u305f'));
  assert.equal(selectCalls,2);
  assert.equal(await page.locator('#registerCandidates').isDisabled(),true,'completed candidates cannot be submitted again');
  await page.unroute('**/api/candidates/create');await page.unroute('**/api/candidates/select');
});

test('vocabulary preview reports batch errors and can be retried', async () => {
  let failOnce=true;
  const vocabulary=[{word:'retry-word',meaning:'retry meaning',part_of_speech:'noun'}];
  await page.route('**/saved',route=>route.fulfill({json:[{material_id:'retry-material',title:'Retry fixture'}]}));
  await page.route('**/saved-data*',route=>route.fulfill({json:{title:'Retry fixture',blocks:[{vocabulary}]}}));
  await page.route('**/api/candidates/create',route=>route.fulfill({json:{batch_id:'retry-batch',items:[{candidate_id:'retry-candidate',english:'retry-word',meaning:'retry meaning',part_of_speech:'noun'}]}}));
  await page.route('**/api/candidates/compare-batch',route=>{
    if(failOnce){failOnce=false;return route.fulfill({status:503,json:{error:'fixture database busy'}});}
    return route.fulfill({json:{job_id:'retry-job',items:[{candidate_id:'retry-candidate',excluded:false,reason:null,similarity:null,threshold:.8,model:'fixture-model'}],model:'fixture-model'}});
  });
  await page.goto('http://127.0.0.1:18765/#add');
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#practiceDataSource').options.length===2);
  await page.locator('#practiceDataSource').selectOption('retry-material');
  await page.locator('#previewPracticeVocabulary').click();
  await page.waitForFunction(()=>document.querySelector('#practiceVocabularyProgressText').textContent.includes('fixture database busy'));
  assert.equal(await page.locator('#previewPracticeVocabulary').isEnabled(),true);
  await page.locator('#previewPracticeVocabulary').click();
  await page.waitForFunction(()=>document.querySelector('#practiceVocabularyProgress').value===1&&document.querySelector('#practiceImportStatus').textContent.includes('1'));
  assert.equal(await page.locator('#registerCandidates').isEnabled(),true);
  await page.unroute('**/saved');await page.unroute('**/saved-data*');await page.unroute('**/api/candidates/create');await page.unroute('**/api/candidates/compare-batch');
});
