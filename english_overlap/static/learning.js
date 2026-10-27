(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const defaults = {reveal_answer: ['a','u','s','i'], rate_again: ['a','u'], rate_known: ['s','i']};
  let bindings = defaults, question = null, phase = 'idle', busy = false, learningAnswered = 0, learningItems = [], learningTotal = 0;
  let vocabularyPage=1,vocabularySort='english',vocabularySortDirection='asc',vocabularyRequest=0;
  let practiceTabActive=window.location.hash.slice(1)==='practice',learningElapsedMs=0,learningActiveSince=null,pendingAnswer=null;
  let detachKeys = null, embeddingIndexBusy = false;
  const status = message => { $('learningStatus').textContent = message; };
  const studySetStatus = message => { $('studySetStatus').textContent = message; };
  function studySetFailureMessage(job, prefix='生成に失敗しました。') {
    const reason=job.error||'原因情報がありません。サーバーログを確認してください。';
    const missing=job.result?.missing_targets;
    // Older jobs stored the entire error string here instead of target names.
    const missingText=Array.isArray(missing)?missing.join('、'):(missing&&missing!==job.error?missing:'');
    return `${prefix}完了済み ${job.completed_items}/${job.total_items} 語義。理由: ${reason}${missingText?`（未生成の対象語: ${missingText}）`:''} 再開できます。`;
  }
  const request = async (url, options) => {
    const response = await fetch(url, options);
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || 'Request failed');
    return body;
  };
  const parseKeys = value => value.split(',').map(x => x.trim().toLowerCase()).filter(Boolean);
  function updateLearningProgress(state){const total=learningTotal;if(state==='active')$('learningProgress').textContent=`${Math.min(learningAnswered+1,total)} / ${total}\u554f\u76ee`;else if(state==='complete')$('learningProgress').textContent=`${learningAnswered}\u554f\u5b8c\u4e86`;else if(state==='empty')$('learningProgress').textContent='\u3053\u306e\u6761\u4ef6\u306b\u5408\u3046\u8a9e\u5f59\u306f\u3042\u308a\u307e\u305b\u3093';else $('learningProgress').textContent='\u7df4\u7fd2\u958b\u59cb\u524d';}
  function pauseLearningTimer(){if(learningActiveSince!==null){learningElapsedMs+=Date.now()-learningActiveSince;learningActiveSince=null;}}
  function resumeLearningTimer(){if(practiceTabActive&&!document.hidden&&question&&learningActiveSince===null&&!pendingAnswer)learningActiveSince=Date.now();}
  window.addEventListener('english-overlap-tab-change',event=>{practiceTabActive=event.detail?.tabId==='practice';if(practiceTabActive)resumeLearningTimer();else pauseLearningTimer();});
  document.addEventListener('visibilitychange',()=>document.hidden?pauseLearningTimer():resumeLearningTimer());
  window.addEventListener('pagehide',pauseLearningTimer);
  const display = () => {
    const historyRoot=$('vocabularyHistory');
    if(historyRoot){historyRoot.replaceChildren();if(question){const history=Array.isArray(question.history)?question.history:[];historyRoot.title=history.length?`過去 ${history.length} 回の回答`:'回答履歴なし';history.slice(-12).forEach(rating=>{const mark=document.createElement('span');mark.className=rating==='known'?'history-known':'history-again';mark.textContent=rating==='known'?'O':'X';mark.setAttribute('aria-label',rating==='known'?'正解':'不正解');historyRoot.append(mark);});}}
    if (!question) {
      $('vocabularyAnswer').hidden = true;
      $('revealAnswer').disabled = $('rateAgain').disabled = $('rateKnown').disabled = true;
      return;
    }
    $('vocabularyQuestion').textContent = phase === 'question' && $('learningDirection').value === 'ja_to_en' ? question.meaning : question.english;
    $('vocabularyAnswer').hidden = phase !== 'answer';
    $('vocabularyAnswer').textContent = phase === 'answer' ? ($('learningDirection').value === 'ja_to_en' ? question.english : question.meaning) : '';
    $('revealAnswer').disabled = phase !== 'question';
    $('rateAgain').disabled = $('rateKnown').disabled = phase !== 'answer' || busy;
  };
  async function loadSettings() {
    try {
      const result = await request('/api/settings/keys');
      if (result.bindings) bindings = result.bindings;
    } catch (_) {}
    $('revealKeys').value = bindings.reveal_answer.join(',');
    $('againKeys').value = bindings.rate_again.join(',');
    $('knownKeys').value = bindings.rate_known.join(',');
    attachKeys();
  }
  function attachKeys() {
    $('shortcutHint').textContent='問題中：'+bindings.reveal_answer.map(key=>key.toUpperCase()).join(' / ')+' で答えを見る。答え表示後：'+bindings.rate_again.map(key=>key.toUpperCase()).join(' / ')+' でもう一度、'+bindings.rate_known.map(key=>key.toUpperCase()).join(' / ')+' で覚えていた。';
    document.querySelectorAll('#revealAnswer,#rateAgain,#rateKnown').forEach(button => {
      const label = button.textContent.replace(/\s*\([^)]*\)$/, '');
      const action = button.id === 'revealAnswer' ? 'reveal_answer' : button.id === 'rateAgain' ? 'rate_again' : 'rate_known';
      button.textContent = label + ' (' + bindings[action].map(k => k.toUpperCase()).join(' / ') + ')';
    });
    if (detachKeys) detachKeys();
    if (window.EnglishOverlapKeys) detachKeys = window.EnglishOverlapKeys.attach({
      documentRef: document, getPhase: () => practiceTabActive ? phase : 'idle',
      bindings, isBusy: () => busy,
      actions: {reveal_answer: reveal, rate_again: () => rate('again'), rate_known: () => rate('known')}
    });
  }
  async function start() {
    try {
      const countInput=$('setCount');countInput.value=String(Math.min(1000,Math.max(1,Number(countInput.value)||50)));
      const dueOnly=$('reviewMode').value==='due';
      $('dueReviewHint').hidden=!dueOnly;
      const parameters=new URLSearchParams({direction:$('learningDirection').value,category:$('learningCategory').value,count:countInput.value,include_unstudied:String($('includeUnstudied').checked),mastery_status:$('masteryStatus').value,difficulty:$('setDifficulty').value,all_attempts_incorrect:$('allAttemptsIncorrect').value,last_attempt_incorrect:String($('lastAttemptIncorrect').checked),include_insufficient_history:String($('includeInsufficientHistory').checked),due_only:String(dueOnly)});
      if(!dueOnly&&$('recentAttempts').value)parameters.set('recent_attempts',$('recentAttempts').value);
      if(!dueOnly&&$('maxRecentAccuracy').value)parameters.set('max_recent_accuracy',$('maxRecentAccuracy').value);
      const result = await request('/api/next-question?' + parameters.toString());
      learningItems=Array.isArray(result.items)?result.items:(result.item?[result.item]:[]);
      learningTotal=learningItems.length;
      question=learningItems[0]||null;phase=question?'question':'idle';learningElapsedMs=0;learningActiveSince=null;pendingAnswer=null;resumeLearningTimer();
      updateLearningProgress(question?'active':'empty');
      if(!question)$('vocabularyQuestion').textContent=dueOnly?'\u5fa9\u7fd2\u671f\u9650\u304c\u6765\u305f\u8a9e\u5f59\u306f\u3042\u308a\u307e\u305b\u3093\u3002':'\u6761\u4ef6\u306b\u5408\u3046\u8a9e\u5f59\u304c\u3042\u308a\u307e\u305b\u3093\u3002';
      status(question ? '出題しました。A/U/S/I またはボタンで答えを表示してください。' : '該当する語彙がありません。');
      display();
    } catch (error) { status(error.message); }
  }
  function reveal() { if (phase !== 'question' || busy) return; phase = 'answer'; display(); }
  async function rate(rating) {
    if (phase !== 'answer' || busy || !question) return;
    if(!pendingAnswer){pauseLearningTimer();pendingAnswer={idempotency_key:crypto.randomUUID(),rating,duration_seconds:(learningElapsedMs/1000)};}
    rating=pendingAnswer.rating;
    busy = true; display();
    try {
      await request('/api/answer', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vocab_id:question.vocab_id,sense_id:question.sense_id,direction:$('learningDirection').value,rating,duration_seconds:pendingAnswer.duration_seconds,idempotency_key:pendingAnswer.idempotency_key})});
      pendingAnswer=null;void loadStatistics();
      learningAnswered++;
      if (learningAnswered >= learningTotal) {
        question = null; phase = 'idle'; $('vocabularyQuestion').textContent = `設定件数 ${learningAnswered} 件の学習が完了しました。`;
        updateLearningProgress('complete');
        status(rating === 'known' ? '覚えていた、と記録しました。' : 'もう一度、と記録しました。'); display(); return;
      }
      status(rating === 'known' ? '覚えていた、と記録しました。' : 'もう一度、と記録しました。');
      question=learningItems[learningAnswered]||null;phase=question?'question':'idle';learningElapsedMs=0;learningActiveSince=null;resumeLearningTimer();display();updateLearningProgress(question?'active':'complete');
    } catch (error) { status('保存できませんでした。回答は保持しています。' + error.message); }
    finally { busy = false; display(); }
  }
  $('reviewMode').addEventListener('change',()=>{$('dueReviewHint').hidden=$('reviewMode').value!=='due';document.querySelectorAll('.standard-only').forEach(el=>el.hidden=$('reviewMode').value==='due');});
  function setFocusMode(active){document.body.classList.toggle('vocabulary-focus-mode',active);$('focusModeToggle').setAttribute('aria-pressed',String(active));if(active)$('exitFocusMode').focus();else $('focusModeToggle').focus();}
  $('focusModeToggle').onclick=()=>setFocusMode(true);
  $('exitFocusMode').onclick=()=>setFocusMode(false);
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.body.classList.contains('vocabulary-focus-mode')){event.preventDefault();setFocusMode(false);}});
  $('startLearning').onclick = () => { if(pendingAnswer){status('未保存の回答を同じキーで再送してください。');return;}learningAnswered = 0;updateLearningProgress('idle');void start(); };
  $('revealAnswer').onclick = reveal;
  $('rateAgain').onclick = () => rate('again');
  $('rateKnown').onclick = () => rate('known');
  $('saveKeySettings').onclick = async () => {
    const candidate = {reveal_answer:parseKeys($('revealKeys').value),rate_again:parseKeys($('againKeys').value),rate_known:parseKeys($('knownKeys').value)};
    if (EnglishOverlapKeys.validateBindings(candidate).length) return status('同じ状態のキー割当が重複しています。');
    try { await request('/api/settings/keys',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({bindings:candidate})}); bindings=candidate; attachKeys(); status('キー設定を保存しました。'); }
    catch (error) { status(error.message); }
  };
  $('resetKeySettings').onclick = async () => {
    bindings=defaults; $('revealKeys').value='a,u,s,i'; $('againKeys').value='a,u'; $('knownKeys').value='s,i'; attachKeys();
    try { await request('/api/settings/keys',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({bindings})}); status('キー設定を初期値に戻しました。'); }
    catch(error) { status(error.message); }
  };
  async function loadVocabulary() {
    try {
      const requestId=++vocabularyRequest;
      const query = new URLSearchParams({q:$('vocabularySearch').value,direction:$('learningDirection').value,include_archived:$('includeArchived').checked?'1':'0',page:String(vocabularyPage),page_size:'50',sort_by:vocabularySort,sort_direction:vocabularySortDirection});
      const result = await request('/api/vocabulary?' + query);
      if(requestId!==vocabularyRequest)return;
      vocabularyPage=result.page;
      const first=result.total?(result.page-1)*result.page_size+1:0,last=(result.page-1)*result.page_size+result.items.length;
      const pageCount=Math.max(1,result.pages);
      $('vocabularyPageRange').textContent=`${first}–${last} / ${result.total}件（`;
      $('vocabularyPageInput').max=String(pageCount);$('vocabularyPageInput').value=String(result.page);
      $('vocabularyPageCount').textContent=String(pageCount);
      $('vocabularyPageStatus').textContent=`${first}–${last} / ${result.total}件（${result.page}/${pageCount}ページ）`;
      $('vocabularyPageStatus').dataset.pages=String(pageCount);
      $('vocabularyFirstPage').disabled=$('vocabularyPreviousPage').disabled=result.page<=1;
      $('vocabularyNextPage').disabled=$('vocabularyLastPage').disabled=result.page>=result.pages;
      document.querySelectorAll('[data-sort-header]').forEach(header=>{const active=header.dataset.sortHeader===vocabularySort;header.setAttribute('aria-sort',active?(vocabularySortDirection==='asc'?'ascending':'descending'):'none');const button=header.querySelector('button');if(button)button.textContent=button.textContent.replace(/[▲▼]$/,'').trim()+(active?(vocabularySortDirection==='asc'?' ▲':' ▼'):'');});
      const rows = $('vocabularyRows'); rows.replaceChildren();
      result.items.forEach(item => {
        const row = document.createElement('tr');
        for (const value of [item.english,item.meaning,item.part_of_speech || '',item.tags||item.genre_tags||'',item.difficulty_level||'未判定']) { const cell=document.createElement('td'); cell.textContent=value; row.append(cell); }
        const cell=document.createElement('td'), edit=document.createElement('button'), archive=document.createElement('button');
        edit.textContent='編集'; edit.onclick=async()=>{
          const english=prompt('英語見出し語',item.english), meaning=prompt('日本語の意味',item.meaning);
          if(english===null||meaning===null)return;
          const part_of_speech=prompt('品詞',item.part_of_speech||'');if(part_of_speech===null)return;
          const tags=prompt('タグ',item.tags||'');if(tags===null)return;
          const sources=prompt('出典',item.sources||'');if(sources===null)return;
          const level=prompt('CEFR難易度（A1-C2、未設定は空欄）',item.difficulty_level||'');if(level===null)return;
          await request('/api/vocabulary/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vocab_id:item.vocab_id,english,meaning,part_of_speech,tags,sources})});
          if(level!==item.difficulty_level)await request('/api/difficulty/manual',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sense_id:item.sense_id,level})});
          loadVocabulary();
        };
        archive.textContent=item.archived_at_utc?'復元':'アーカイブ'; archive.onclick=async()=>{await request('/api/vocabulary/archive',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vocab_id:item.vocab_id,archived:!item.archived_at_utc})});loadVocabulary();}; cell.append(edit,archive); row.append(cell); rows.append(row);
      });
      for(const select of [$('learningCategory'),$('studySetCategory')]){
        const selected=select.value;
        select.replaceChildren(new Option('すべて',''));
        result.categories.forEach(category=>select.add(new Option(category.name,category.category_id)));
        select.value=selected;
      }
      const themeSelect=$('setTheme'),savedTheme=themeSelect.value;
      themeSelect.replaceChildren(new Option('指定なし',''));
      result.categories.forEach(category=>themeSelect.add(new Option(category.name,category.name)));
      themeSelect.value=savedTheme;
      if(!restoredStudySetConditions){restoredStudySetConditions=true;try{const saved=await request('/api/study-set/last');const c=saved.conditions||{};const studyCategory=$('studySetCategory');if(c.category&&Array.from(studyCategory.options).some(option=>option.value===c.category))studyCategory.value=c.category;if(c.direction)$('studySetDirection').value=c.direction;if(c.count)$('studySetCount').value=c.count;if(c.include_unstudied!==undefined)$('studySetIncludeUnstudied').checked=c.include_unstudied;if(c.mastery_status)$('studySetMasteryStatus').value=c.mastery_status;if(c.difficulty)$('studySetDifficulty').value=c.difficulty;if(c.theme&&Array.from(themeSelect.options).some(option=>option.value===c.theme))themeSelect.value=c.theme;if(c.length)$('setLength').value=c.length;if(c.generation_mode)$('studySetMode').value=c.generation_mode;if(c.recent_attempts)$('studySetRecentAttempts').value=c.recent_attempts;if(c.max_recent_accuracy!==null&&c.max_recent_accuracy!==undefined)$('studySetMaxRecentAccuracy').value=c.max_recent_accuracy;if(c.include_insufficient_history!==undefined)$('studySetIncludeInsufficientHistory').checked=c.include_insufficient_history;}catch(_){}}
      await loadMaterials();
    } catch(error) { status(error.message); }
  }
  async function loadMaterials(){
    const result=await request('/api/materials');
    if(result.legacy_import_warnings?.length)status(`\u65e7\u6559\u6750JSON ${result.legacy_import_warnings.length}\u4ef6\u3092DB\u306b\u53d6\u308a\u8fbc\u3081\u307e\u305b\u3093\u3067\u3057\u305f: ${result.legacy_import_warnings.map(item=>item.file).join(', ')}`);
    const root=$('materialRows');root.replaceChildren();const count=$('materialCount');if(count)count.textContent=String(result.items.length);
    result.items.forEach(item=>{
      const row=document.createElement('tr');
      row.dataset.materialId=item.material_id;
      let metadata={};try{metadata=JSON.parse(item.content_json||'{}');}catch{}
      const titleCell=document.createElement('td'),title=document.createElement('strong'),summary=document.createElement('p');
      title.textContent=item.title;summary.className='material-summary';summary.textContent=typeof metadata.summary==='string'&&metadata.summary.trim()?metadata.summary:'AI要約はまだありません。';
      titleCell.append(title,summary);
      for(const cell of [titleCell,...[String(item.vocabulary_count),item.status].map(text=>{const td=document.createElement('td');td.textContent=text;return td;})])row.append(cell);
      const cell=document.createElement('td'),practice=document.createElement('button'),edit=document.createElement('button'),archive=document.createElement('button'),remove=document.createElement('button'),summarize=document.createElement('button');
      practice.textContent='練習する';practice.onclick=()=>{if(item.status==='archived')return status('アーカイブ済み教材は復元してから練習できます。');const editor=$('source');editor.value=item.text_content;const overlap=document.getElementById('overlapSource');if(overlap)overlap.value=item.text_content;document.body.dataset.materialId=item.material_id;status('選択した教材をオーバーラッピングへ読み込みました。');window.dispatchEvent(new CustomEvent('english-overlap-open'));};
      edit.textContent='編集';edit.onclick=async()=>{const title=prompt('教材名',item.title),text=prompt('英文',item.text_content);if(title===null||text===null)return;await request('/api/materials/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({material_id:item.material_id,title,text_content:text})});loadMaterials();};
      archive.textContent=item.status==='archived'?'復元':'アーカイブ';archive.onclick=async()=>{await request('/api/materials/archive',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({material_id:item.material_id,archived:item.status!=='archived'})});loadMaterials();};
      summarize.type='button';summarize.textContent=metadata.summary?'AI要約・教材名を更新':'AI要約・教材名を生成';summarize.title='OpenAI APIを使って教材を要約します。API利用料が発生します。';summarize.onclick=async()=>{summarize.disabled=true;status(`「${item.title}」のAI要約を生成しています…`);try{const response=await request('/api/materials/summarize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({material_id:item.material_id})});await loadMaterials();status(`AI要約を保存しました（${response.model} / 概算 $${Number(response.cost?.usd??0).toFixed(6)}）。`);}catch(error){summarize.disabled=false;status(`AI要約を生成できませんでした: ${error.message}`);}};
      remove.type='button';remove.textContent='削除';remove.setAttribute('aria-label',`教材「${item.title}」を削除`);remove.onclick=async()=>{if(!window.confirm(`「${item.title}」を削除します。教材と語彙リンク、他教材から参照されていない音声ファイルを削除します。語彙本体と学習履歴は残ります。続けますか？`))return;remove.disabled=true;try{const result=await request('/api/materials/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({material_id:item.material_id})});try{await loadMaterials();}catch(error){status('教材は削除しましたが一覧を更新できませんでした: '+error.message);return;}if(result.file_cleanup_errors?.length||result.skipped_files?.length)status('教材を削除しました。一部の音声ファイルは安全のため削除できませんでした。');else if(result.shared_files_kept?.length)status('教材を削除しました。他教材と共有されている音声ファイルは残しました。');else status('教材を削除しました。');}catch(error){remove.disabled=false;status('教材を削除できませんでした: '+error.message);}};
      cell.append(practice,edit,archive,summarize,remove);row.append(cell);root.append(row);
    });
  }
  $('refreshMaterials').onclick=()=>loadMaterials().catch(error=>status(error.message));
  window.addEventListener('english-overlap-tab-change',event=>{if(event.detail?.tabId==='manage')void loadMaterials().catch(error=>status(error.message));});
  $('searchVocabulary').onclick = () => {vocabularyPage=1;void loadVocabulary();};
  $('vocabularySearch').addEventListener('keydown',event=>{if(event.key==='Enter'){vocabularyPage=1;void loadVocabulary();}});
  $('includeArchived').onchange=()=>{vocabularyPage=1;void loadVocabulary();};
  $('vocabularyFirstPage').onclick=()=>{vocabularyPage=1;void loadVocabulary();};
  $('vocabularyPreviousPage').onclick=()=>{vocabularyPage=Math.max(1,vocabularyPage-1);void loadVocabulary();};
  $('vocabularyNextPage').onclick=()=>{vocabularyPage++;void loadVocabulary();};
  $('vocabularyLastPage').onclick=()=>{vocabularyPage=Number($('vocabularyPageStatus').dataset.pages)||vocabularyPage;void loadVocabulary();};
  const jumpVocabularyPage=()=>{const input=$('vocabularyPageInput'),max=Number(input.max)||1;vocabularyPage=Math.max(1,Math.min(max,Math.trunc(Number(input.value)||1)));input.value=String(vocabularyPage);void loadVocabulary();};
  $('vocabularyPageInput').addEventListener('change',jumpVocabularyPage);
  $('vocabularyPageInput').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();jumpVocabularyPage();}});
  document.querySelectorAll('[data-vocab-sort]').forEach(button=>button.addEventListener('click',()=>{const column=button.dataset.vocabSort;if(vocabularySort===column)vocabularySortDirection=vocabularySortDirection==='asc'?'desc':'asc';else{vocabularySort=column;vocabularySortDirection='asc';}vocabularyPage=1;void loadVocabulary();}));
  $('exportVocabulary').onclick = async () => {
    try { const response=await fetch('/api/vocabulary/export');if(!response.ok)throw Error('Export failed');const a=document.createElement('a');a.href=URL.createObjectURL(await response.blob());a.download='vocabulary.csv';a.click();URL.revokeObjectURL(a.href); }
    catch(error) { status(error.message); }
  };
  $('exportMaterials').onclick=async()=>{try{const response=await fetch('/api/materials/export');if(!response.ok)throw Error('Export failed');const a=document.createElement('a');a.href=URL.createObjectURL(await response.blob());a.download='materials.csv';a.click();URL.revokeObjectURL(a.href);}catch(error){status(error.message);}};
  let activeBatch = null, registeringCandidates = false;
  $('extractCandidates').onclick = async () => {
    const source=$('candidateSource').value.trim();if(!source)return status('英文か語彙リストを入力してください。');
    const lines=source.split('\n').filter(Boolean), isList=lines.every(line=>line.includes('|')||line.includes('\t')||line.includes('｜'));
    try {
      const result=await request('/api/candidates/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source,source_type:isList?'vocabulary_list':'english_text'})});
      activeBatch=result.batch_id;const root=$('candidateRows');root.replaceChildren();
      result.items.forEach(item=>{
        const label=document.createElement('label'),check=document.createElement('input'),compare=document.createElement('button'),reason=document.createElement('span');check.type='checkbox';check.value=item.candidate_id;check.checked=!item.excluded_reason;
        label.append(check,document.createTextNode(' '+item.english+' — '+item.meaning+' '));
        reason.textContent=item.excluded_reason==='exact_match'?`完全一致: ${item.matched_vocab_id}`:item.excluded_reason==='duplicate_candidate'?'入力候補内の表記重複':'';
        compare.type='button';compare.textContent='類似確認（API）';compare.onclick=async()=>{compare.disabled=true;try{const threshold=Number($('similarityThreshold').value);const assessment=await request('/api/candidates/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_id:activeBatch,candidate_id:item.candidate_id,threshold})});reason.textContent=assessment.excluded?`除外候補: ${assessment.matched_english||assessment.matched_vocab_id} (${assessment.similarity?.toFixed(3)}、閾値 ${assessment.threshold})`:assessment.reason==='dataset_embeddings_not_indexed'?'既存索引なし。先に既存語彙を索引化してください。':assessment.reason==='exact_match'?`完全一致: ${assessment.matched_vocab_id}`:'類似候補なし';if(assessment.excluded)check.checked=false;}catch(error){reason.textContent=error.message;}finally{compare.disabled=false;}};
        label.append(compare,reason);root.append(label,document.createElement('br'));
      });
      $('registerCandidates').disabled=registeringCandidates||result.items.length===0;status('候補を確認して登録対象を選んでください。');
    } catch(error) { status(error.message); }
  };
  $('registerCandidates').onclick=async()=>{
    if(!activeBatch||registeringCandidates)return;
    const button=$('registerCandidates'),checks=Array.from($('candidateRows').querySelectorAll('input[type="checkbox"]'));
    const candidate_ids=checks.filter(input=>input.checked).map(input=>input.value);
    if(!candidate_ids.length)return;
    registeringCandidates=true;button.disabled=true;checks.forEach(input=>input.disabled=true);status('選択した候補を登録しています…');
    try {
      const result=await request('/api/candidates/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_id:activeBatch,candidate_ids})});
      status(result.created_vocab_ids.length+'件を登録しました。');loadVocabulary();void loadAutomaticDifficulty(false);
    } catch(error) {
      checks.forEach(input=>input.disabled=false);status(error.message);
    } finally {
      registeringCandidates=false;
      button.disabled=!$('candidateRows').querySelector('input:checked:not(:disabled)');
    }
  };
  async function updateEmbeddingEstimate(){
    try{const result=await request('/api/embeddings/plan');$('embeddingEstimate').textContent=`${result.missing_count}\u8a9e\u7fa9\u306e\u7d22\u5f15\u304c\u672a\u4f5c\u6210\u3002\u6982\u7b97 $${result.estimated_usd.toFixed(6)}\u3002\u30e2\u30c7\u30eb ${result.model}\u3002${result.note}`;$('indexEmbeddings').disabled=embeddingIndexBusy||result.missing_count===0;return result;}
    catch(error){$('embeddingEstimate').textContent=error.message;$('indexEmbeddings').disabled=embeddingIndexBusy;return null;}
  }
  async function loadPracticeDataSources(){
    try{
      const items=await request('/saved');const select=$('practiceDataSource');select.replaceChildren(new Option('\u6559\u6750\u3092\u9078\u629e\u3057\u3066\u304f\u3060\u3055\u3044',''));
      items.forEach(item=>{const summary=String(item.summary||item.title);select.add(new Option(`${summary.length>48?summary.slice(0,45)+'…':summary} (${item.title})`,item.material_id));});
      $('previewPracticeVocabulary').disabled=items.length===0;
      $('practiceImportStatus').textContent=items.length?`${items.length}\u4ef6\u306eDB\u6559\u6750\u3092\u8aad\u307f\u8fbc\u307f\u307e\u3057\u305f\u3002`:'\u4f7f\u3048\u308bDB\u6559\u6750\u304c\u3042\u308a\u307e\u305b\u3093\u3002';
    }catch(error){$('practiceImportStatus').textContent=error.message;}
  }
  loadPracticeDataSources();
  $('previewPracticeVocabulary').onclick=async()=>{
    const materialId=$('practiceDataSource').value;if(!materialId)return $('practiceImportStatus').textContent='\u6559\u6750\u3092\u9078\u629e\u3057\u3066\u304f\u3060\u3055\u3044\u3002';
    const button=$('previewPracticeVocabulary'),root=$('candidateRows'),progress=$('practiceVocabularyProgress'),progressText=$('practiceVocabularyProgressText');
    button.disabled=true;root.replaceChildren();$('registerCandidates').disabled=true;progress.hidden=true;progress.value=0;progressText.hidden=true;
    let total=0,processed=0;
    try{
      const data=await request(`/saved-data?material_id=${encodeURIComponent(materialId)}`);
      const candidates=[];const seen=new Set();
      for(const block of data.blocks||[])for(const entry of block.vocabulary||[]){const english=String(entry.word||'').trim(),meaning=String(entry.meaning||'').trim(),key=english.toLocaleLowerCase();if(english&&!seen.has(key)){seen.add(key);candidates.push({english,meaning,part_of_speech:entry.part_of_speech||entry.pos||'',source:data.title||materialId});}}
      if(!candidates.length)throw new Error('\u9078\u629e\u3057\u305f\u6559\u6750\u306b\u8a9e\u5f59\u304c\u3042\u308a\u307e\u305b\u3093\u3002');
      const batch=await request('/api/candidates/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_type:'vocabulary_list',source:candidates.map(item=>`${item.english} | ${item.meaning} | ${item.part_of_speech}`).join('\n')})});
      activeBatch=batch.batch_id;const threshold=Number($('similarityThreshold').value);total=batch.items.length;
      progress.hidden=false;progress.max=Math.max(total,1);progressText.hidden=false;
      const chunkSize=50;
      for(let offset=0;offset<batch.items.length;offset+=chunkSize){
        const chunk=batch.items.slice(offset,offset+chunkSize);
        progressText.textContent=`\u985e\u4f3c\u5ea6\u3092\u78ba\u8a8d\u4e2d: ${processed} / ${total} \u8a9e\u7fa9`;
        const compared=await request('/api/candidates/compare-batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_id:activeBatch,candidate_ids:chunk.map(item=>item.candidate_id),threshold})});
        const scores=new Map(compared.items.map(item=>[item.candidate_id,item]));
        const assessed=chunk.map(item=>{const score=scores.get(item.candidate_id);if(!score)throw new Error('\u985e\u4f3c\u5ea6\u306e\u8a55\u4fa1\u7d50\u679c\u304c\u4e0d\u8db3\u3057\u3066\u3044\u307e\u3059\u3002');if(score.reason==='dataset_embeddings_not_indexed')throw new Error('\u65e2\u5b58\u8a9e\u5f59\u306e\u7d22\u5f15\u304c\u3042\u308a\u307e\u305b\u3093\u3002\u5148\u306b\u985e\u4f3c\u5224\u5b9a\u7528\u30a4\u30f3\u30c7\u30c3\u30af\u30b9\u3092\u4f5c\u6210\u3057\u3066\u304f\u3060\u3055\u3044\u3002');return {...item,...score,sourceIncluded:!score.excluded};});
        assessed.forEach(item=>{
          const label=document.createElement('label'),check=document.createElement('input'),details=document.createElement('span');check.type='checkbox';check.value=item.candidate_id;check.checked=item.sourceIncluded;
          const similarity=item.similarity===null?`\u95be\u5024\u4ee5\u4e0b (${threshold.toFixed(2)})`:item.similarity.toFixed(3);
          const decision=item.reason==='exact_match'?'\u5b8c\u5168\u4e00\u81f4':item.sourceIncluded?'\u8ffd\u52a0\u5019\u88dc':'\u3057\u304d\u5024\u4ee5\u4e0a';
          const similar=(item.similar_matches||[]).slice(0,3).map(match=>`${match.english} (${match.similarity.toFixed(3)})`).join(', ');
          details.textContent=` ${item.english} \u2014 ${item.meaning} \u00b7 \u985e\u4f3c\u5ea6 ${similarity} \u00b7 ${decision}${similar?` \u00b7 \u985e\u4f3c\u8a9e: ${similar}`:''} `;
          label.append(check,details);root.append(label,document.createElement('br'));
        });
        processed+=assessed.length;progress.value=processed;progressText.textContent=`\u985e\u4f3c\u5ea6\u3092\u78ba\u8a8d\u3057\u307e\u3057\u305f: ${processed} / ${total} \u8a9e\u7fa9`;
        $('registerCandidates').disabled=!root.querySelector('input:checked');
      }
      $('registerCandidates').disabled=!root.querySelector('input:checked');
      $('practiceImportStatus').textContent=`${total}\u8a9e\u7fa9\u306e\u30d7\u30ec\u30d3\u30e5\u30fc\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002\u3057\u304d\u3044\u5024 ${threshold.toFixed(2)} \u4ee5\u4e0b\u306e\u5019\u88dc\u3092\u9078\u629e\u3057\u3066\u767b\u9332\u3067\u304d\u307e\u3059\u3002`;
    }catch(error){
      progress.hidden=false;progress.max=Math.max(total,1);progress.value=processed;progressText.hidden=false;
      progressText.textContent=`\u4e2d\u65ad: ${processed} / ${total} \u8a9e\u7fa9\u3092\u78ba\u8a8d\u6e08\u307f\u3002 ${error.message}`;
      $('practiceImportStatus').textContent=error.message;
      $('registerCandidates').disabled=!root.querySelector('input:checked');
    }finally{button.disabled=false;}
  };
  $('indexEmbeddings').onclick=async()=>{
    if(embeddingIndexBusy)return;
    embeddingIndexBusy=true;$('indexEmbeddings').disabled=true;
    const progress=$('embeddingProgress'),progressText=$('embeddingProgressText');
    progress.hidden=false;progress.value=0;progressText.hidden=false;progressText.textContent='\u985e\u4f3c\u5224\u5b9a\u7528\u30a4\u30f3\u30c7\u30c3\u30af\u30b9\u3092\u6e96\u5099\u4e2d\u2026';
    let initialTotal=0,indexedTotal=0,remaining=0;
    try{
      const plan=await request('/api/embeddings/plan');initialTotal=remaining=plan.missing_count;progress.max=Math.max(initialTotal,1);
      progressText.textContent=`\u7d22\u5f15\u6e08\u307f 0 / ${initialTotal} \u8a9e\u7fa9; \u6b8b\u308a ${remaining}\u3002`;
      while(remaining>0){
        const result=await request('/api/embeddings/index',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit:100})});
        indexedTotal+=result.indexed;remaining=result.remaining;
        progress.max=Math.max(initialTotal,indexedTotal+remaining,1);progress.value=Math.min(indexedTotal,progress.max);
        progressText.textContent=`\u7d22\u5f15\u6e08\u307f ${indexedTotal} / ${initialTotal} \u8a9e\u7fa9; \u6b8b\u308a ${remaining}\u3002`;
        if(result.indexed===0&&remaining>0)throw new Error('\u51e6\u7406\u304c\u9032\u307e\u306a\u3044\u305f\u3081\u4e2d\u65ad\u3057\u307e\u3057\u305f\u3002\u6b8b\u308a\u306f\u518d\u5b9f\u884c\u3067\u304d\u307e\u3059\u3002');
      }
      progress.value=progress.max;progressText.textContent=`\u5b8c\u4e86: ${indexedTotal} \u8a9e\u7fa9\u3092\u7d22\u5f15\u5316\u3057\u307e\u3057\u305f; \u6b8b\u308a 0\u3002`;
    }catch(error){
      const refreshed=await request('/api/embeddings/plan').catch(()=>null);if(refreshed)remaining=refreshed.missing_count;
      progressText.textContent=`\u4e2d\u65ad: ${indexedTotal} \u8a9e\u7fa9\u51e6\u7406\u6e08\u307f; \u6b8b\u308a ${remaining}\u3002 ${error.message}`;
    }finally{
      embeddingIndexBusy=false;await updateEmbeddingEstimate();
    }
  };
  let difficultyPlan=null,difficultyJobId=null,difficultyPoll=null;
  let automaticDifficultyJobId=null,automaticDifficultyPoll=null;
  async function loadAutomaticDifficulty(initial=false){
    try{
      const state=await request('/api/difficulty/auto/status');
      if(initial){$('automaticDifficultyEnabled').checked=state.settings.enabled;$('automaticDifficultyLimit').value=state.settings.per_run_limit;$('automaticDifficultyBudget').value=state.settings.daily_budget_usd;}
      const job=state.job;automaticDifficultyJobId=job?.job_id||null;
      let text=`未評価 ${state.pending_senses} 語義。今日の利用額 $${state.spent_today_usd.toFixed(6)} / $${Number(state.settings.daily_budget_usd).toFixed(3)} USD。`;
      if(!state.api_key_configured)text+=' APIキー未設定のため待機中です。';
      if(job){text+=` 自動評価 ${job.status}: ${job.completed_items}/${job.total_items} 件。`;if(job.error==='daily_budget_limit')text+='日次上限で停止しました。';else if(job.error==='waiting_for_api_key')text+='APIキーを設定後に起動してください。';else if(job.error&&job.status==='failed')text+=`失敗: ${job.error}`;}
      $('automaticDifficultyStatus').textContent=text;
      $('pauseAutomaticDifficulty').disabled=!job||job.status!=='running';
      $('resumeAutomaticDifficulty').disabled=!job||!['paused','failed'].includes(job.status);
      const awaitingNextChunk=!!job&&job.status==='completed'&&state.pending_senses>0&&state.settings.enabled&&state.api_key_configured;
      if(job&&(job.status==='running'||job.status==='queued'||awaitingNextChunk)&&!automaticDifficultyPoll)automaticDifficultyPoll=setInterval(()=>void loadAutomaticDifficulty(false),1000);
      if((!job||(!['running','queued'].includes(job.status)&&!awaitingNextChunk))&&automaticDifficultyPoll){clearInterval(automaticDifficultyPoll);automaticDifficultyPoll=null;loadVocabulary();}
    }catch(error){$('automaticDifficultyStatus').textContent=error.message;}
  }
  $('saveAutomaticDifficulty').onclick=async()=>{try{await request('/api/difficulty/auto/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:$('automaticDifficultyEnabled').checked,per_run_limit:Number($('automaticDifficultyLimit').value),daily_budget_usd:Number($('automaticDifficultyBudget').value)})});await loadAutomaticDifficulty(false);}catch(error){$('automaticDifficultyStatus').textContent=error.message;}};
  $('pauseAutomaticDifficulty').onclick=async()=>{try{await request('/api/jobs/pause',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:automaticDifficultyJobId})});await loadAutomaticDifficulty(false);}catch(error){$('automaticDifficultyStatus').textContent=error.message;}};
  $('resumeAutomaticDifficulty').onclick=async()=>{try{await request('/api/difficulty/resume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:automaticDifficultyJobId})});await loadAutomaticDifficulty(false);}catch(error){$('automaticDifficultyStatus').textContent=error.message;}};
  $('planDifficulty').onclick=async()=>{try{difficultyPlan=await request('/api/difficulty/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit:100})});$('difficultyEstimate').textContent=`未評価 ${difficultyPlan.items} 語義。概算 $${difficultyPlan.estimated_usd.toFixed(6)}（${difficultyPlan.model}）。手動設定済みの難易度は維持します。`;$('startDifficulty').disabled=!difficultyPlan.items;}catch(error){$('difficultyEstimate').textContent=error.message;}};
  async function pollDifficulty(){if(!difficultyJobId)return;try{const job=await request('/api/jobs?id='+encodeURIComponent(difficultyJobId));$('difficultyJobStatus').textContent=`${job.status}: ${job.completed_items}/${job.total_items} 件`;$('pauseDifficulty').disabled=job.status!=='running';$('resumeDifficulty').disabled=!['paused','failed'].includes(job.status);if(job.status==='completed'||job.status==='failed'){clearInterval(difficultyPoll);difficultyPoll=null;if(job.status==='completed')loadVocabulary();}}catch(error){$('difficultyJobStatus').textContent=error.message;}}
  $('startDifficulty').onclick=async()=>{try{const result=await request('/api/difficulty/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sense_ids:difficultyPlan.sense_ids})});difficultyJobId=result.job_id;difficultyPoll=setInterval(pollDifficulty,1000);pollDifficulty();}catch(error){status(error.message);}};
  $('pauseDifficulty').onclick=async()=>{try{await request('/api/jobs/pause',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:difficultyJobId})});await pollDifficulty();}catch(error){status(error.message);}};
  $('resumeDifficulty').onclick=async()=>{try{await request('/api/difficulty/resume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:difficultyJobId})});await pollDifficulty();}catch(error){status(error.message);}};
  let studySetPlan=null,restoredStudySetConditions=false;
  let generatedStudySet=null;
  let generationJobId=null,generationJobIds=[];
  $('planStudySet').onclick=async()=>{
    const recentAttempts=$('studySetRecentAttempts').value;
    const maxRecentAccuracy=$('studySetMaxRecentAccuracy').value;
    if(maxRecentAccuracy!==''&&!recentAttempts)return studySetStatus('正答率で絞るには、判定に使う出題数（直近N回）も指定してください。');
    const requestBody={category:$('studySetCategory').value||null,direction:$('studySetDirection').value,count:Number($('studySetCount').value),include_unstudied:$('studySetIncludeUnstudied').checked,mastery_status:$('studySetMasteryStatus').value,difficulty:$('studySetDifficulty').value,theme:$('setTheme').value,length:$('setLength').value,generation_mode:$('studySetMode').value,recent_attempts:recentAttempts?Number(recentAttempts):null,max_recent_accuracy:maxRecentAccuracy?Number(maxRecentAccuracy):maxRecentAccuracy===''?null:0,include_insufficient_history:$('studySetIncludeInsufficientHistory').checked};
    try {
      studySetPlan=await request('/api/study-set/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(requestBody)});
      const root=$('studySetPlan');root.replaceChildren();
      const info=document.createElement('p');info.textContent=`対象 ${studySetPlan.selected_count} 語 / 概算合計 $${studySetPlan.estimated_total_usd.toFixed(6)}（英文 $${studySetPlan.estimated_text_usd.toFixed(6)} + 音声 $${studySetPlan.estimated_realtime_usd.toFixed(6)} + 文字起こし $${studySetPlan.estimated_transcription_usd.toFixed(6)}）。${studySetPlan.estimate_note} 旧履歴は方向が不明なため順位に含めません。`;root.append(info);
      studySetPlan.items.forEach(item=>{const label=document.createElement('label'),checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=true;checkbox.value=item.vocab_id;label.append(checkbox,document.createTextNode(` ${item.english} — ${item.meaning} (${item.selection_reason})`));root.append(label,document.createElement('br'));});
      $('generateStudySet').disabled=studySetPlan.selected_count===0;
      if(studySetPlan.selected_count){studySetStatus('条件に一致する語彙を確認してください。');}
      else {
        const history=studySetPlan.history_summary||{};
        const coverage=history.directional_answer_vocabulary_count??0,legacy=history.legacy_history_count_excluded??0;
        const direction=$('studySetDirection').value==='en_to_ja'?'英語→日本語':'日本語→英語';
        const legacyNote=legacy?` 旧履歴${legacy.toLocaleString()}件は学習方向が記録されていないため、この絞り込みには使われません。`:'';
        studySetStatus(`選択した条件に一致する語彙がありません。${direction}の回答履歴がある語彙: ${coverage.toLocaleString()}件。正答率上限・直近回数・カテゴリ・方向・CEFRを緩めてください。${legacyNote}`);
      }
    } catch(error){studySetStatus(error.message);}
  };
  async function runStudySetGeneration(resume=false){
    if(!studySetPlan){studySetStatus('再開する教材条件がありません。条件をもう一度選んでください。');return;}
    const vocab_ids=Array.from($('studySetPlan').querySelectorAll('input:checked')).map(input=>input.value);
    const selectedIds=resume&&generationJobId?generationJobIds:vocab_ids;
    if(!selectedIds.length)return studySetStatus('英文作成に使う語彙を選択してください。');
    try {
      $('generateStudySet').disabled=true;$('resumeStudySet').disabled=true;studySetStatus('英文生成ジョブを開始しています…');
      if(resume==='resume'){await request('/api/study-set/resume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:generationJobId})});}
      else if(resume!=='poll'){const started=await request('/api/study-set/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vocab_ids,difficulty:studySetPlan.conditions.difficulty,theme:studySetPlan.conditions.theme,length:$('setLength').value,generation_mode:$('studySetMode').value})});generationJobId=started.job_id;generationJobIds=vocab_ids;localStorage.setItem('englishOverlapStudySetJob',JSON.stringify({job_id:generationJobId,vocab_ids:generationJobIds,generation_mode:$('studySetMode').value,conditions:{...studySetPlan.conditions,generation_mode:$('studySetMode').value},items:studySetPlan.items.filter(item=>vocab_ids.includes(item.vocab_id))}));}
      while(true){const job=await request('/api/jobs?id='+encodeURIComponent(generationJobId));studySetStatus(`英文を作成しています ${job.completed_items}/${job.total_items} 語義`);if(job.status==='completed'){await applyGeneratedStudySet(job);break;}if(job.status==='failed'){$('resumeStudySet').hidden=false;$('resumeStudySet').disabled=false;studySetStatus(studySetFailureMessage(job));break;}await new Promise(resolve=>setTimeout(resolve,500));}
    } catch(error){studySetStatus(error.message);if(generationJobId)$('resumeStudySet').hidden=false;}
    finally{$('generateStudySet').disabled=!studySetPlan||studySetPlan.selected_count===0;}
  }
  async function applyGeneratedStudySet(job){
    const result=job.result;
    generatedStudySet={...result,vocab_ids:job.payload.vocab_ids,selected_count:job.total_items,used_count:result.used_vocab_ids.length,conditions:{...studySetPlan.conditions,length:studySetPlan.conditions.length||$('setLength').value,generation_mode:job.payload.generation_mode||'per_vocabulary'},selectedItems:studySetPlan.items.filter(item=>job.payload.vocab_ids.includes(item.vocab_id))};
    $('source').value=result.text;
    const overlapSource=$('overlapSource');if(overlapSource)overlapSource.value=result.text;
    document.querySelector('#source').scrollIntoView({behavior:'smooth'});
    $('resumeStudySet').hidden=true;
    studySetStatus('????????????????????????????????');
    await saveGeneratedStudySet();
  }
  async function saveGeneratedStudySet(){
    if(!generatedStudySet)return;
    try{
      const title='Vocabulary practice '+new Date().toLocaleDateString('ja-JP',{timeZone:'Asia/Tokyo'});
      const result=await request('/api/study-set/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,text_content:$('source').value,source:'dataset',difficulty_level:generatedStudySet.conditions.difficulty,metadata:{...generatedStudySet.conditions,selected_vocab_ids:generatedStudySet.vocab_ids,selected_vocabulary:generatedStudySet.selectedItems,model:generatedStudySet.model,usage:generatedStudySet.usage},usages:generatedStudySet.usages})});
      generatedStudySet.material_id=result.material_id;generatedStudySet.material_title=title;
      localStorage.removeItem('englishOverlapStudySetJob');
      document.body.dataset.materialId=result.material_id;
      const overlapSource=$('overlapSource');if(overlapSource)overlapSource.value=$('source').value;
      studySetStatus('???????????????????????????????????????????????????????');
      await loadMaterials();
      window.dispatchEvent(new CustomEvent('english-overlap-open'));
    }catch(error){studySetStatus('??????????????: '+error.message);}
  }
  $('source').addEventListener('input',()=>{if(generatedStudySet?.material_id){const overlapSource=$('overlapSource');if(overlapSource)overlapSource.value=$('source').value;}});
  $('source').addEventListener('change',async()=>{
    if(!generatedStudySet?.material_id)return;
    try{await request('/api/materials/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({material_id:generatedStudySet.material_id,title:generatedStudySet.material_title,text_content:$('source').value})});studySetStatus('???????????????????');await loadMaterials();}
    catch(error){studySetStatus('???????????????: '+error.message);}
  });
  async function restoreStudySetJob(){try{const saved=JSON.parse(localStorage.getItem('englishOverlapStudySetJob')||'null');if(!saved)return;generationJobId=saved.job_id;generationJobIds=saved.vocab_ids;studySetPlan={conditions:saved.conditions,items:saved.items,selected_count:saved.vocab_ids.length};if(saved.generation_mode)studySetMode.value=saved.generation_mode;const job=await request('/api/jobs?id='+encodeURIComponent(generationJobId));if(job.status==='failed'){$('resumeStudySet').hidden=false;$('resumeStudySet').disabled=false;studySetStatus(studySetFailureMessage(job,'前回の英文生成に失敗しました。'));}else if(job.status==='completed')await applyGeneratedStudySet(job);else if(job.status==='running')runStudySetGeneration('poll');}catch(error){studySetStatus('前回の英文生成状態を読み込めませんでした: '+error.message);}}
  $('generateStudySet').onclick=()=>runStudySetGeneration(false);
  $('resumeStudySet').onclick=()=>runStudySetGeneration('resume');
  function renderLearningChart(container,rows,config){
    container.replaceChildren();container.setAttribute('role','img');container.setAttribute('aria-label',config.description);
    const legend=document.createElement('div');legend.className='chart-legend';for(const series of config.series){const item=document.createElement('span');item.className='chart-legend-item';const swatch=document.createElement('i');swatch.className='chart-swatch '+series.color;item.append(swatch,document.createTextNode(series.name));legend.append(item);}container.append(legend);
    if(!rows.length){const empty=document.createElement('p');empty.className='muted';empty.textContent='表示できる学習実績がありません。';container.append(empty);return;}
    const max=Math.max(1,...rows.map(row=>config.series.reduce((sum,series)=>sum+Math.max(0,Number(series.value(row))||0),0)));const list=document.createElement('div');list.className='chart-rows';
    for(const row of rows){const line=document.createElement('div');line.className='chart-row';const label=document.createElement('span');label.className='chart-label';label.textContent=config.label(row);label.title=`${config.label(row)} · ${config.detail(row)}`;const track=document.createElement('span');track.className='chart-track';const total=config.series.reduce((sum,series)=>sum+Math.max(0,Number(series.value(row))||0),0);for(const series of config.series){const value=Math.max(0,Number(series.value(row))||0);if(!value||!total)continue;const bar=document.createElement('i');bar.className='chart-bar '+series.color;bar.style.width=`${value/max*100}%`;bar.setAttribute('aria-hidden','true');track.append(bar);}const detail=document.createElement('span');detail.className='chart-detail';detail.textContent=config.detail(row);line.append(label,track,detail);list.append(line);}container.append(list);
  }
  function renderVocabularyDistribution(rows){
    const container=$('vocabularyDistributionChart'),summary=$('vocabularyDistributionSummary');if(!container||!summary)return;
    const metric=$('vocabularyDistributionMetric')?.value||'accuracy';const result=window.EnglishOverlapDistribution.buildVocabularyDistribution(rows,metric);container.replaceChildren();
    if(metric==='accuracy')summary.textContent=`正答率を計算できる語彙 ${result.total} 語 / 未学習のため除外 ${result.excludedUnstudied} 語`;
    else summary.textContent=`対象 ${result.total} 語。未学習語も0回として含みます。`;
    if(!rows.length||(!result.total&&metric==='accuracy')){const empty=document.createElement('p');empty.className='muted';empty.textContent=rows.length?'正答率を計算できる学習済み語彙がありません。':'検索条件に合う語彙がありません。';container.append(empty);return;}
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.classList.add('distribution-svg');svg.setAttribute('viewBox','0 0 780 370');svg.setAttribute('role','img');svg.setAttribute('aria-label',`${result.label}ごとの語彙数分布。${result.bins.map(bin=>`${bin.label}: ${bin.count}語`).join('、')}`);
    const make=(name,attrs={},textValue)=>{const element=document.createElementNS(ns,name);for(const [key,value] of Object.entries(attrs))element.setAttribute(key,String(value));if(textValue!==undefined)element.textContent=textValue;return element;};const title=make('title',{},`${result.label}別の語彙数`);svg.append(title);
    const left=72,right=24,top=24,bottom=294,width=780-left-right,height=bottom-top,max=Math.max(1,...result.bins.map(bin=>bin.count));const ticks=[...new Set([0,Math.ceil(max/4),Math.ceil(max/2),Math.ceil(max*3/4),max])].sort((a,b)=>a-b);
    for(const tick of ticks){const y=bottom-tick/max*height;svg.append(make('line',{x1:left,y1:y,x2:width+left,y2:y,class:'distribution-grid'}),make('text',{x:left-10,y:y+4,'text-anchor':'end',class:'distribution-tick'},tick));}
    svg.append(make('line',{x1:left,y1:top,x2:left,y2:bottom,class:'distribution-axis'}),make('line',{x1:left,y1:bottom,x2:width+left,y2:bottom,class:'distribution-axis'}));const slot=width/result.bins.length;
    result.bins.forEach((bin,index)=>{const x=left+slot*index+slot*.16,bw=slot*.68,bh=bin.count/max*height,y=bottom-bh;const rect=make('rect',{x,y,width:bw,height:Math.max(0,bh),rx:3,class:'distribution-bar'});rect.append(make('title',{},`${bin.label}: ${bin.count}語`));svg.append(rect,make('text',{x:x+bw/2,y:Math.max(top+14,y-6),'text-anchor':'middle',class:'distribution-value'},bin.count),make('text',{x:left+slot*(index+.5),y:bottom+22,'text-anchor':'middle',class:'distribution-tick'},bin.label));});
    svg.append(make('text',{x:left+width/2,y:355,'text-anchor':'middle',class:'distribution-axis-label'},result.label),make('text',{transform:`translate(20 ${top+height/2}) rotate(-90)`,'text-anchor':'middle',class:'distribution-axis-label'},'語彙数'));container.append(svg);
  }
  function setStatisticsView(prefix,mode){const table=$(prefix==='vocabulary'?'vocabularyPerformance':'dailyLearningTable'),chart=$(prefix==='vocabulary'?'vocabularyPerformanceChart':'dailyLearningChart'),tableButton=$(prefix==='vocabulary'?'vocabularyViewTable':'dailyViewTable'),chartButton=$(prefix==='vocabulary'?'vocabularyViewChart':'dailyViewChart');const isChart=mode==='chart';if(table)table.hidden=isChart;if(chart)chart.hidden=!isChart;if(tableButton)tableButton.setAttribute('aria-pressed',String(!isChart));if(chartButton)chartButton.setAttribute('aria-pressed',String(isChart));}
  for(const [id,prefix,mode] of [['vocabularyViewTable','vocabulary','table'],['vocabularyViewChart','vocabulary','chart'],['dailyViewTable','daily','table'],['dailyViewChart','daily','chart']])if($(id))$(id).addEventListener('click',()=>setStatisticsView(prefix,mode));
  if($('dailyChartMetric'))$('dailyChartMetric').addEventListener('change',()=>void loadStatistics());
  if($('vocabularyDistributionMetric'))$('vocabularyDistributionMetric').addEventListener('change',()=>renderVocabularyDistribution(currentVocabularyRows));
  let currentVocabularyRows=[];
  function renderLearningGoals(data){
    const root=$('learningGoalsProgress');if(!root)return;root.replaceChildren();
    const addGoal=(id,title,current,target,formatActual,formatTarget=formatActual)=>{
      const card=document.createElement('section');card.className='learning-goal-card';
      const heading=document.createElement('h4');heading.textContent=title;card.append(heading);
      const value=document.createElement('p');value.className='learning-goal-value';
      const actual=formatActual(current);value.textContent=target==null?`現在 ${actual} · 目標未設定`:`現在 ${actual} / 目標 ${formatTarget(target)} · 残り ${formatActual(Math.max(0,target-current))}`;card.append(value);
      if(target!=null){const percent=Math.min(100,Math.max(0,Math.round(current/target*100)));const progress=document.createElement('progress');progress.id=id;progress.max=100;progress.value=percent;progress.setAttribute('aria-label',`${title}の達成率`);card.append(progress);const percentText=document.createElement('span');percentText.className='learning-goal-percent';percentText.textContent=`${percent}%`;card.append(percentText);}
      root.append(card);
    };
    addGoal('overlapGoalProgress','オーバーラッピング',Number(data.overlap_seconds||0)/3600,data.goals.overlap_hours,value=>`${Number(value).toFixed(2)}時間`,value=>`${Number(value).toFixed(1)}時間`);
    addGoal('vocabularyGoalProgress','語彙学習',Number(data.learned_vocabulary_count||0),data.goals.vocabulary_count,value=>`${Math.floor(Number(value))}語`);
  }
  async function loadLearningGoals(syncInputs=false){
    const status=$('learningGoalsStatus');
    try{const data=await request('/api/learning-goals');renderLearningGoals(data);if(syncInputs){$('overlapGoalHours').value=data.goals.overlap_hours??'';$('vocabularyGoalCount').value=data.goals.vocabulary_count??'';}return data;}
    catch(error){if(status)status.textContent=`目標の進捗を読み込めませんでした: ${error.message}`;return null;}
  }
  const goalsForm=$('learningGoalsForm');if(goalsForm)goalsForm.addEventListener('submit',async event=>{event.preventDefault();const status=$('learningGoalsStatus'),button=$('saveLearningGoals');if(button)button.disabled=true;if(status)status.textContent='目標を保存しています…';
    try{const data=await request('/api/learning-goals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({overlap_hours:$('overlapGoalHours').value===''?null:Number($('overlapGoalHours').value),vocabulary_count:$('vocabularyGoalCount').value===''?null:Number($('vocabularyGoalCount').value)})});renderLearningGoals(data);$('overlapGoalHours').value=data.goals.overlap_hours??'';$('vocabularyGoalCount').value=data.goals.vocabulary_count??'';if(status)status.textContent='学習目標を保存しました。';}
    catch(error){if(status)status.textContent=`目標を保存できませんでした: ${error.message}`;}
    finally{if(button)button.disabled=false;}
  });
  let adventureSnapshot=null,adventureRequest=0;
  $('questDockSummary')?.addEventListener('click',()=>{if(document.body.classList.contains('vocabulary-focus-mode'))setFocusMode(false);});
  async function loadAdventure(){
    const root=$('adventureQuests');if(!root)return;
    const requestId=++adventureRequest;
    try{
      const data=await request('/api/adventure');
      if(requestId!==adventureRequest)return;
      $('adventureLevel').textContent=`Lv.${data.level}`;
      $('adventureTotalXp').textContent=`${Number(data.total_xp).toLocaleString()} XP`;
      $('adventureTodayXp').textContent=`今日 +${Number(data.today_xp)} XP`;
      $('adventureStreak').textContent=`🔥 連続 ${Number(data.streak_days)}日`;
      $('adventureBestStreak').textContent=`最長 ${Number(data.best_streak_days)}日`;
      const remaining=Math.max(0,Number(data.xp_to_next_level)-Number(data.xp_in_level));
      $('adventureNextLevel').textContent=`あと${remaining} XPでレベルアップ`;
      const levelProgress=$('adventureLevelProgress');levelProgress.max=Math.max(1,Number(data.xp_to_next_level));levelProgress.value=Math.min(levelProgress.max,Number(data.xp_in_level));
      const battle=data.battle,character=data.character;
      $('battleCharacter').dataset.stage=String(character.stage);
      $('characterTitle').textContent=character.title;
      $('characterEvolution').textContent=character.next_evolution_level?`Lv.${character.next_evolution_level}で${character.next_evolution_title}に成長`:'最終形態 · さらにレベルを高めよう';
      $('battleEnemy').dataset.style=String(battle.enemy_style);
      $('battleEnemy').dataset.boss=String(battle.is_boss);
      $('battleEnemyName').textContent=(battle.is_boss?'BOSS · ':'')+battle.enemy_name;
      $('battleEnemyReward').textContent=`撃破で +${battle.next_reward_xp} XP`;
      $('battleChapter').textContent=`第${battle.chapter}章 · ${battle.encounter}体目`;
      $('battleHpText').textContent=`${battle.hp} / ${battle.max_hp}`;
      for(const id of ['battleHp','questDockHp']){const bar=$(id);bar.max=battle.max_hp;bar.value=battle.hp;}
      $('battleDefeated').textContent=`撃破 ${battle.defeated}体（ボス ${battle.bosses_defeated}体）`;
      $('battleRewardTotal').textContent=`撃破ボーナス ${battle.reward_xp.toLocaleString()} XP`;
      $('questDockSummary').textContent=`⚔ Lv.${data.level} ${character.title} / ${battle.is_boss?'BOSS ':''}${battle.enemy_name} HP ${battle.hp}/${battle.max_hp}`;
      if(adventureSnapshot&&data.training_xp>adventureSnapshot.training_xp){
        const damage=data.training_xp-adventureSnapshot.training_xp;
        const defeated=battle.defeated-adventureSnapshot.battle.defeated;
        const reward=battle.reward_xp-adventureSnapshot.battle.reward_xp;
        let message=defeated>0?`${defeated}体撃破！ ボーナス +${reward} XP。`:`${battle.enemy_name}に${damage}ダメージ！`;
        message+=` 経験値 +${data.total_xp-adventureSnapshot.total_xp} XP。`;
        if(data.level>adventureSnapshot.level)message+=` Lv.${data.level}にレベルアップ！`;
        if(character.stage>adventureSnapshot.character.stage)message+=` ${character.title}に成長！`;
        $('battleFeedback').textContent=message;
        if(!window.matchMedia('(prefers-reduced-motion: reduce)').matches){
          $('battleEnemy').animate([{transform:'translateX(0)'},{transform:'translateX(8px)'},{transform:'translateX(-5px)'},{transform:'translateX(0)'}],{duration:350});
          $('battleFeedback').animate([{opacity:.3},{opacity:1}],{duration:350});
        }
      }
      adventureSnapshot=data;
      root.replaceChildren();
      for(const quest of data.quests||[]){
        const card=document.createElement('section');card.className='quest-card'+(quest.completed?' quest-complete':'');
        const main=document.createElement('div');main.className='quest-main';
        const title=document.createElement('strong');title.textContent=quest.title;
        const progressText=document.createElement('span');progressText.textContent=`${Math.min(Number(quest.current),Number(quest.target))} / ${quest.target}${quest.id==='overlap'?'分':'問'}`;
        main.append(title,progressText);
        const bar=document.createElement('progress');bar.max=Number(quest.target);bar.value=Math.min(Number(quest.current),Number(quest.target));bar.setAttribute('aria-label',`${quest.title}の進捗`);
        const reward=document.createElement('span');reward.className='quest-reward';reward.textContent=quest.completed?'達成':`+${quest.reward_xp} XP`;
        card.append(main,bar,reward);root.append(card);
      }
    }catch(error){if(requestId!==adventureRequest)return;root.textContent=`冒険の進捗を読み込めませんでした: ${error.message}`;$('questDockSummary').textContent='冒険の進捗を取得できませんでした';}
  }
  window.addEventListener('english-overlap-tab-change',event=>{if(event.detail?.tabId==='dashboard')void loadAdventure();});
  void loadLearningGoals(true);window.addEventListener('english-overlap-activity-saved',()=>void loadLearningGoals());
  async function loadStatistics(){
    const root=$('statisticsPanel');if(!root)return;
    try{
      void loadAdventure();
      const range=$('statisticsRange')?.value||'30';const x=await request('/api/statistics?days='+encodeURIComponent(range));void loadLearningGoals();const inventory=$('databaseStatistics');
      if(inventory){inventory.replaceChildren();const stats=x.database_stats;if(stats&&typeof stats==='object'){const same=stats.vocabulary_count===stats.active_vocabulary_count&&stats.vocabulary_count===stats.sense_count;const inventoryCards=same?[['語彙',stats.vocabulary_count]]:[['登録語彙',stats.vocabulary_count],['学習対象',stats.active_vocabulary_count],['語義',stats.sense_count]];const cards=[...inventoryCards,['登場数',stats.attempt_count],['正解数',stats.known_count],['不正解数',stats.again_count],['累積正解率',stats.accuracy==null?'?':Math.round(stats.accuracy*100)+'%'],['未登場語',stats.unseen_vocabulary_count]];for(const [label,value] of cards){const card=document.createElement('div');card.className='stat-card';const caption=document.createElement('span');caption.textContent=label;const strong=document.createElement('strong');strong.textContent=String(value??'?');card.append(caption,strong);inventory.append(card);}}else inventory.textContent='データベース全体の統計を取得できません。';}
      const performanceRoot=$('vocabularyPerformance');if(performanceRoot){performanceRoot.replaceChildren();const allRows=Array.isArray(x.vocabulary_performance)?x.vocabulary_performance:null;const search=($('performanceSearch')?.value||'').trim().toLocaleLowerCase();const sort=$('performanceSort')?.value||'again';const rows=(allRows||[]).filter(item=>item&&typeof item==='object'&&(!search||`${item.english||''} ${item.japanese||''}`.toLocaleLowerCase().includes(search)));currentVocabularyRows=rows;renderVocabularyDistribution(rows);rows.sort((a,b)=>{if(sort==='attempts')return (b.attempts||0)-(a.attempts||0)||(a.english||'').localeCompare(b.english||'');if(sort==='known')return (b.known||0)-(a.known||0)||(a.english||'').localeCompare(b.english||'');if(sort==='english')return (a.english||'').localeCompare(b.english||'');return (a.known_rate??2)-(b.known_rate??2)||(b.attempts||0)-(a.attempts||0)||(a.english||'').localeCompare(b.english||'');});const count=$('performanceCount');if(count)count.textContent=allRows?`${rows.length} 語 / ${allRows.length} 語`:'語彙別の学習実績を取得できません。';
        if(allRows){const table=document.createElement('table');table.className='performance-table';const head=document.createElement('tr');for(const label of ['英語','日本語','登場数','正解','不正解','正解率']){const th=document.createElement('th');th.textContent=label;head.append(th);}const thead=document.createElement('thead');thead.append(head);table.append(thead);const body=document.createElement('tbody');for(const item of rows){const tr=document.createElement('tr');for(const value of [item.english||'?',item.japanese||'?',item.attempts??0,item.known??0,item.again??0,item.known_rate==null?'未学習':`${Math.round(item.known_rate*100)}%`]){const td=document.createElement('td');td.textContent=String(value);tr.append(td);}body.append(tr);}table.append(body);performanceRoot.append(table);}else performanceRoot.textContent='語彙別の学習実績を取得できません。';
        const chart=$('vocabularyPerformanceChart');if(chart)renderLearningChart(chart,rows,{description:'語彙別の回答数。緑が正解、赤が再学習。各行に正解率を表示します。',label:item=>item.english||'?',detail:item=>`${item.japanese||''} · ${item.attempts??0}回 · 正解率 ${item.known_rate==null?'未学習':Math.round(item.known_rate*100)+'%'}`,series:[{name:'正解',value:item=>item.known??0,color:'known'},{name:'再学習',value:item=>item.again??0,color:'again'}]});
      }
      root.replaceChildren();const totalMinutes=seconds=>Math.round(Number(seconds||0)/60);const periodLabel=range==='all'?'全期間':`${range}日間`;const summary=document.createElement('p');summary.textContent=`${periodLabel} (日本時間 ${x.period_start_tokyo||'履歴開始'} ～ ${x.period_end_tokyo||'?'}) 語彙練習時間 ${totalMinutes(x.vocabulary_active_seconds)}分、オーバーラッピング時間 ${totalMinutes(x.overlap_active_seconds)}分、合計 ${totalMinutes(x.active_seconds)}分、学習日数 ${x.study_days??0}日、復習予定 ${x.due_count??0}件、新規語彙 ${x.new_vocabulary_count??0}件、正答率 ${x.known_rate==null?'?':Math.round(x.known_rate*100)+'%'}`;root.append(summary);const legacy=document.createElement('p');legacy.className='muted';legacy.textContent=`旧形式の学習記録 ${x.legacy_history_count_excluded??0}件は時間統計に含めません。`;root.append(legacy);if(Array.isArray(x.due_items)&&x.due_items.length){const due=document.createElement('ul');x.due_items.slice(0,20).forEach(item=>{const li=document.createElement('li');li.textContent=item.english+' · '+item.meaning+' ('+(item.direction==='ja_to_en'?'JA→EN':'EN→JA')+') '+item.due_date+' due';due.append(li);});root.append(due);}
      const entries=Object.entries(x.daily&&typeof x.daily==='object'?x.daily:{}).sort((a,b)=>b[0].localeCompare(a[0]));const dailyRows=entries.map(([date,day])=>({date,...day}));const dailyTable=$('dailyLearningTable');if(dailyTable){dailyTable.replaceChildren();if(!entries.length){const empty=document.createElement('p');empty.textContent='この期間の学習記録はありません。';dailyTable.append(empty);}else{const table=document.createElement('table'),head=document.createElement('tr');for(const title of ['日付','回答数','正解','再学習','語彙練習（分）','オーバーラッピング（分）','合計（分）']){const th=document.createElement('th');th.textContent=title;head.append(th);}table.append(head);entries.forEach(([date,day])=>{const tr=document.createElement('tr');for(const value of [date,day.answers??0,day.known??0,day.again??0,totalMinutes(day.vocabulary_active_seconds),totalMinutes(day.overlap_active_seconds),totalMinutes(day.active_seconds)]){const td=document.createElement('td');td.textContent=String(value);tr.append(td);}table.append(tr);});dailyTable.append(table);}}
      const dailyChart=$('dailyLearningChart');if(dailyChart){const metric=$('dailyChartMetric')?.value||'answers';const studyMinutes=seconds=>Math.round(Number(seconds||0)/6)/10;renderLearningChart(dailyChart,[...dailyRows].reverse(),{description:metric==='answers'?'日付ごとの回答数。緑が正解、赤が再学習。':'日付ごとの学習時間（分）。青が語彙練習、紫がオーバーラッピング。',label:item=>item.date,detail:item=>metric==='answers'?`${item.answers??0}回答`:`${studyMinutes(item.active_seconds)}分`,series:metric==='answers'?[{name:'正解',value:item=>item.known??0,color:'known'},{name:'再学習',value:item=>item.again??0,color:'again'}]:[{name:'語彙練習',value:item=>studyMinutes(item.vocabulary_active_seconds),color:'vocabulary'},{name:'オーバーラッピング',value:item=>studyMinutes(item.overlap_active_seconds),color:'overlap'}]});}
    }catch(error){root.textContent=error.message;}
  }
  if($('statisticsRange'))$('statisticsRange').onchange=()=>void loadStatistics();if($('performanceSearch'))$('performanceSearch').oninput=()=>void loadStatistics();if($('performanceSort'))$('performanceSort').onchange=()=>void loadStatistics();  window.addEventListener('english-overlap-activity-saved',()=>void loadStatistics());
  loadStatistics();
  loadSettings(); loadVocabulary(); updateEmbeddingEstimate();restoreStudySetJob();loadAutomaticDifficulty(true);
})();
