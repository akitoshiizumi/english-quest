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
    assert.deepEqual(errors, []);
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
});
