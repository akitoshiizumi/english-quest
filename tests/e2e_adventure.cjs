const {test} = require('node:test');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {mkdirSync} = require('node:fs');
const {chromium} = require('playwright');

test('ten vocabulary answers defeat an enemy, award XP, and survive a reload', async () => {
  // This server creates its own temporary DB and never uses the user's data/API key.
  const server = spawn('py', ['tests/e2e_server.py'], {stdio:'ignore', windowsHide:true,
    env:{...process.env, ENGLISH_OVERLAP_E2E_PORT:'18766'}});
  let browser;
  try {
    const deadline = Date.now() + 20000;
    let ready = false;
    while (Date.now() < deadline) {
      try { ready = (await fetch('http://127.0.0.1:18766/health')).ok; } catch {}
      if (ready) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(ready, 'isolated fixture server should start');
    browser = await chromium.launch({headless:true});
    const page = await browser.newPage({viewport:{width:1280,height:900}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.setDefaultTimeout(10000);
    await page.goto('http://127.0.0.1:18766/#practice');
    await page.waitForFunction(() => document.querySelector('#questDockSummary').textContent.includes('HP 40/40'));
    await page.waitForFunction(() => document.querySelector('#learningCategory').options.length > 1);
    await page.locator('#learningCategory').selectOption('Pagination');
    await page.locator('#setCount').fill('10');
    await page.locator('#startLearning').click();
    for (let index = 0; index < 10; index++) {
      await page.locator('#revealAnswer').click();
      await page.locator('#rateAgain').click();
      if (index === 0) {
        await page.waitForFunction(() => document.querySelector('#questDockHp').value === 38);
        assert.match(await page.locator('#battleFeedback').textContent(), /2ダメージ/);
      }
    }
    await page.waitForFunction(() => document.querySelector('#battleDefeated').textContent.includes('撃破 1体'));
    assert.match(await page.locator('#battleFeedback').textContent(), /撃破.*20 XP/);
    assert.equal(await page.locator('#questDockHp').evaluate(element => element.value), 40);
    const data = await page.evaluate(async () => (await fetch('/api/adventure')).json());
    assert.equal(data.training_xp, 40);
    assert.equal(data.total_xp, 60);
    assert.equal(data.battle.defeated, 1);
    await page.locator('#questDockSummary').click();
    await page.waitForFunction(() => !document.querySelector('#dashboard-panel').hidden);
    assert.equal(await page.locator('#adventureTotalXp').textContent(), '60 XP');
    assert.equal(await page.locator('#battleEnemyName').textContent(), 'アクアスライム');
    assert.equal(await page.locator('#battleCharacter').getAttribute('data-stage'), '0');
    mkdirSync('tests/e2e-artifacts', {recursive:true});
    await page.screenshot({path:'tests/e2e-artifacts/adventure-desktop.png',fullPage:true});
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#adventureTotalXp').textContent === '60 XP');
    assert.match(await page.locator('#battleDefeated').textContent(), /撃破 1体/);
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'mobile page must not overflow horizontally');
    await page.screenshot({path:'tests/e2e-artifacts/adventure-mobile.png',fullPage:true});
    // Verify all shipped illustrations through real static URLs and the UI's API update path.
    const stages = [
      {level:1,title:'見習い冒険者',file:'apprentice'},
      {level:3,title:'冒険者',file:'adventurer'},
      {level:5,title:'クエストナイト',file:'knight'},
      {level:10,title:'ことばの勇者',file:'hero'},
    ];
    let illustrationData = data;
    await page.route('**/api/adventure', route => route.fulfill({json:illustrationData}));
    for (const [stage, character] of stages.entries()) {
      const next = stages[stage+1];
      illustrationData = {...data,level:character.level,character:{stage,title:character.title,
        next_evolution_level:next?.level??null,next_evolution_title:next?.title??null}};
      await page.evaluate(() => window.dispatchEvent(new CustomEvent('english-overlap-activity-saved')));
      await page.waitForFunction(expected => document.querySelector('#characterTitle').textContent === expected, character.title);
      const sprite = page.locator('#battleCharacter .character-sprite:visible');
      assert.equal(await sprite.count(), 1, 'exactly the current evolution should appear');
      assert.match(await sprite.getAttribute('src'), new RegExp(`${character.file}-pixel-v1`));
      await sprite.evaluate(async image => { await image.decode(); });
      const pixels = await sprite.evaluate(image => {
        const canvas = document.createElement('canvas');
        canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
        const context = canvas.getContext('2d'); context.drawImage(image,0,0);
        const data = context.getImageData(0,0,canvas.width,canvas.height).data;
        return {transparent:data[3]===0,hasArtwork:data.some((value,index) => index%4===3 && value>0)};
      });
      assert.deepEqual(pixels, {transparent:true,hasArtwork:true}, 'illustrations should contain artwork on a transparent background');
      assert.equal(await sprite.evaluate(image => getComputedStyle(image).imageRendering), 'pixelated');
      await page.locator('#battleArena').screenshot({path:`tests/e2e-artifacts/character-stage-${stage}.png`});
    }
    assert.deepEqual(errors, []);
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
});
