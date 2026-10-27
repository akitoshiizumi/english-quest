const {test} = require('node:test');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {mkdirSync} = require('node:fs');
const {chromium} = require('playwright');

test('practice scores, correct-answer battles, sentence damage, and illustrations persist and render', async () => {
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
    const dockSprite = page.locator('#questDockCharacter .character-sprite:visible');
    assert.equal(await dockSprite.count(), 1, 'the practice page should show the character without opening the dashboard');
    await dockSprite.evaluate(async image => { await image.decode(); });
    assert.equal(await page.locator('#questDockEnemy .enemy-slime').isVisible(), true);
    await page.waitForFunction(() => document.querySelector('#learningCategory').options.length > 1);
    await page.locator('#learningCategory').selectOption('Pagination');
    await page.locator('#setCount').fill('21');
    await page.locator('#practiceRandomRange').fill('20');
    await page.locator('#practiceRandomSeed').fill('quest-e2e');
    await page.locator('#startLearning').click();
    await page.waitForFunction(()=>document.querySelector('#practiceScore').textContent!=='—');
    assert.equal(await page.locator('#practiceCorrectCount').textContent(),'0');
    assert.equal(await page.locator('#practiceAnswerCount').textContent(),'0');
    assert.equal(Number(await page.locator('#practiceScore').textContent()),Number(await page.locator('#practiceAdjustment').textContent()));
    mkdirSync('tests/e2e-artifacts', {recursive:true});
    await page.locator('#vocabularyStage').screenshot({path:'tests/e2e-artifacts/practice-score.png'});
    for (let index = 0; index < 21; index++) {
      await page.locator('#revealAnswer').click();
      await page.locator(index===0?'#rateAgain':'#rateKnown').click();
      if (index === 0) {
        const progress=await page.evaluate(async ()=>(await fetch('/api/adventure')).json());
        assert.equal(progress.total_damage,0,'an incorrect answer must not attack');
      }
      if (index === 1) {
        await page.waitForFunction(() => document.querySelector('#questDockHp').value === 38);
        assert.match(await page.locator('#battleFeedback').textContent(), /2ダメージ/);
      }
    }
    await page.waitForFunction(() => document.querySelector('#battleDefeated').textContent.includes('撃破 1体'));
    assert.match(await page.locator('#battleFeedback').textContent(), /撃破.*20 XP/);
    assert.equal(await page.locator('#questDockHp').evaluate(element => element.value), 40);
    const data = await page.evaluate(async () => (await fetch('/api/adventure')).json());
    assert.equal(data.training_xp, 62);
    assert.equal(data.total_xp, 82);
    assert.equal(data.battle.defeated, 1);
    await page.locator('#questDockSummary').click();
    await page.waitForFunction(() => !document.querySelector('#dashboard-panel').hidden);
    assert.equal(await page.locator('#adventureTotalXp').textContent(), '82 XP');
    assert.equal(await page.locator('#battleEnemyName').textContent(), 'アクアスライム');
    assert.equal(await page.locator('#battleCharacter').getAttribute('data-stage'), '0');
    mkdirSync('tests/e2e-artifacts', {recursive:true});
    await page.screenshot({path:'tests/e2e-artifacts/adventure-desktop.png',fullPage:true});
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#adventureTotalXp').textContent === '82 XP');
    assert.equal(await page.locator('#practiceRandomRange').inputValue(),'20');
    assert.equal(await page.locator('#practiceRandomSeed').inputValue(),'quest-e2e');
    assert.match(await page.locator('#battleDefeated').textContent(), /撃破 1体/);
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'mobile page must not overflow horizontally');
    await page.screenshot({path:'tests/e2e-artifacts/adventure-mobile.png',fullPage:true});
    // Real media playback: a seek to the ending earns nothing; a whole sentence
    // and a whole clipped repeat each earn exactly one damage.
    await page.getByRole('tab',{name:'オーバーラッピング',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#savedList').options.length>1);
    const materialId=await page.evaluate(async()=>{
      const items=(await (await fetch('/api/materials/overlap-list')).json()).items;
      return items.find(item=>item.text_content==='A fixture sentence.').material_id;
    });
    await page.locator('#savedList').selectOption(materialId);
    await page.waitForFunction(id=>document.body.dataset.materialId===id&&document.querySelector('#player').readyState>=2,materialId);
    await page.locator('#loop').uncheck();
    await page.evaluate(async()=>{const audio=document.querySelector('#player');audio.currentTime=.8;await audio.play();});
    await page.waitForFunction(()=>document.querySelector('#player').ended);
    assert.equal(await page.evaluate(async()=>(await (await fetch('/api/adventure')).json()).total_damage),40);
    await page.locator('#restart').click();
    await page.waitForFunction(async()=>(await (await fetch('/api/adventure')).json()).total_damage===41);
    await page.evaluate(()=>document.querySelector('#player').pause());
    await page.locator('.sentence-repeat').first().click();
    await page.waitForFunction(async()=>(await (await fetch('/api/adventure')).json()).total_damage===42);
    await page.locator('.sentence-repeat').first().click();
    await page.evaluate(()=>document.querySelector('#player').pause());

    // Existing saved blocks may already be split after U.S. or Dr.; the reader repairs them.
    await page.route('**/saved-data?material_id=*',async route=>{
      const response=await route.fetch();const body=await response.json();
      body.text='The U.S. government met Dr. Smith. They left.';
      body.blocks=[{english:'The U.S.',japanese:'米国の'},{english:'government met Dr.',japanese:'政府が博士に会った。'},
        {english:'Smith.'},{english:'They left.'}];
      await route.fulfill({json:body});
    });
    await page.locator('#savedList').selectOption(materialId);
    await page.waitForFunction(()=>document.querySelectorAll('.reader-sentence').length===2);
    assert.equal(await page.locator('.reader-english').first().textContent(),'The U.S. government met Dr. Smith.');
    await page.locator('#openDashboard').click();
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
      assert.match(await sprite.getAttribute('src'), new RegExp(`${character.file}-pixel-128`));
      const dockSprite = page.locator('#questDockCharacter .character-sprite:visible');
      assert.match(await dockSprite.getAttribute('src'), new RegExp(`${character.file}-pixel-128`));
      await sprite.evaluate(async image => { await image.decode(); });
      const pixels = await sprite.evaluate(image => {
        const canvas = document.createElement('canvas');
        canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
        const context = canvas.getContext('2d'); context.drawImage(image,0,0);
        const data = context.getImageData(0,0,canvas.width,canvas.height).data;
        return {transparent:data[3]===0,hasArtwork:data.some((value,index) => index%4===3 && value>0)};
      });
      assert.deepEqual(pixels, {transparent:true,hasArtwork:true}, 'illustrations should contain artwork on a transparent background');
      for (const image of [sprite,dockSprite]) {
        await image.evaluate(async element => { await element.decode(); });
        const dimensions = await image.evaluate(element => {
          const bounds = element.getBoundingClientRect();
          return [element.naturalWidth,element.naturalHeight,bounds.width,bounds.height];
        });
        assert.deepEqual(dimensions, [128,128,128,128], 'the actual PNG resolution and rendered size must match in both panels');
      }
      assert.equal(await sprite.evaluate(image => getComputedStyle(image).imageRendering), 'pixelated');
      await page.locator('#battleArena').screenshot({path:`tests/e2e-artifacts/character-stage-${stage}.png`});
    }
    // Reproduce the reported wide-screen boss encounter on the practice page.
    illustrationData = {...data,level:2,character:{...data.character,stage:0},
      battle:{...data.battle,is_boss:true,enemy_style:4,enemy_name:'ワードドラゴン',hp:74,max_hp:80}};
    await page.getByRole('tab',{name:'語彙練習',exact:true}).click();
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('english-overlap-activity-saved')));
    await page.waitForFunction(() => document.querySelector('#questDockSummary').textContent.includes('HP 74/80'));
    assert.equal(await page.locator('#questDockCharacter .character-stage-0').isVisible(), true);
    assert.equal(await page.locator('#questDockEnemy .enemy-dragon').isVisible(), true);
    assert.equal(await page.locator('#questDockEnemy .enemy-slime').isVisible(), false);
    await page.setViewportSize({width:1700,height:900});
    const dockBounds = await page.locator('.quest-dock').boundingBox();
    const hpBounds = await page.locator('#questDockHp').boundingBox();
    assert.ok(dockBounds.width <= 860 && hpBounds.width <= 340, 'the character, text, and HP should stay grouped on a wide screen');
    await page.locator('.quest-dock').screenshot({path:'tests/e2e-artifacts/adventure-dock-desktop.png'});
    for (const width of [1700,390,320]) {
      await page.setViewportSize({width,height:900});
      const spriteBounds = await page.locator('#questDockCharacter .character-sprite:visible').boundingBox();
      assert.equal(spriteBounds.width, 128, 'pixel characters must not shrink into unreadable thumbnails');
      assert.equal(spriteBounds.height, 128, 'pixel characters must keep a square frame');
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.locator('#questDockSummary').click();
      const dashboardSprite = page.locator('#battleCharacter .character-sprite:visible');
      const dimensions = await dashboardSprite.evaluate(element => {
        const bounds = element.getBoundingClientRect();
        return [element.naturalWidth,element.naturalHeight,bounds.width,bounds.height];
      });
      assert.deepEqual(dimensions, [128,128,128,128], 'dashboard sprites must also remain at native size on narrow screens');
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'native-size dashboard art must not overflow on mobile');
      await page.getByRole('tab',{name:'語彙練習',exact:true}).click();
      if (width === 390) await page.locator('.quest-dock').screenshot({path:'tests/e2e-artifacts/adventure-dock-mobile.png'});
    }
    assert.deepEqual(errors, []);
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
});
