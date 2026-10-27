import {sentenceClip} from './audio-clip';

type WordTime = { word: string; start: number; end: number };
type SentenceBlock = { english: string; japanese?: string; vocabulary?: Array<{word: string; meaning: string}> };
type SavedMaterial = {
  material_id: string; title: string; text_content: string; status: string; file?: string | null;
  file_status?: string; ai_summary?: string | null; created_at?: string; text?: string; voice?: string; style?: string;
  audio_file?: string; audio_path?: string; summary?: string; word_count?: number; character_count?: number; audio_seconds?: number;
  cost?: { total_usd?: number; realtime_usd?: number; transcription_usd?: number };
};
type SavedData = SavedMaterial & { words?: WordTime[]; blocks?: SentenceBlock[] };

const SENTENCE_LEAD_IN_SECONDS = 0.25;
type OverlapSettings = {sentenceGapSeconds:number;repeatGapSeconds:number;sentenceRepeatKey:string;currentSentenceKey:string;previousSentenceKey:string};
const OVERLAP_SETTINGS_KEY='englishOverlapAudioSettings';

function element<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id) as T | null;
  if (!node) throw new Error(`Missing overlap UI element: ${id}`);
  return node;
}

function normalize(value: string): string {
  return value.toLowerCase().replace(/[’‘]/g, "'").replace(/[^a-z0-9']/g, '');
}

function formatJstTimestamp(value?: string): string {
  if (!value) return '－';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const formatted = new Intl.DateTimeFormat('ja-JP', {
    timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(date);
  return `${formatted} JST`;
}

export function setupOverlapControls(): void {
  const player = document.getElementById('player') as HTMLAudioElement | null;
  if (!player || player.dataset.reactBound === '1') return;
  player.dataset.reactBound = '1';
  const source = element<HTMLTextAreaElement>('overlapSource');
  const reader = element<HTMLDivElement>('reader');
  let settings: OverlapSettings = {sentenceGapSeconds:0,repeatGapSeconds:1.5,sentenceRepeatKey:'r',currentSentenceKey:'a',previousSentenceKey:'w'};
  let savedItems: SavedMaterial[] = [];
  let frame = 0;
  let nodes: HTMLSpanElement[] = [];
  let times: Array<number | null> = [];
  let lastSentenceIndex = -1;
  let sentenceSections: HTMLElement[] = [];
  let sentenceButtons: HTMLButtonElement[] = [];
  let sentenceAnchors: Array<{start: number | null; lastEnd: number | null}> = [];
  let sentenceProgressLabels: HTMLSpanElement[] = [];
  let sentenceRanges: Array<{start: number; end: number} | null> = [];
  let sentenceLoopIndex: number | null = null;
  let repeatGapTimer: number | null = null;
  let sentenceGapTimer: number | null = null;
  let sentenceGapIndex: number | null = null;
  let repeatGapPaused = false;
  let fullAudioBlob: Blob | null = null;
  let fullAudioUrl: string | null = null;
  let clipUrl: string | null = null;
  let clipStart = 0;
  let clipGeneration = 0;
  let decodedAudio: AudioBuffer | null = null;
  let fullDuration: number | null = null;
  let overlapActive = window.location.hash.slice(1) === 'overlap' || !window.location.hash;
  window.addEventListener('english-overlap-tab-change', event => { overlapActive = (event as CustomEvent).detail?.tabId === 'overlap'; });

  const status = (message: string, error = false) => {
    const target = element<HTMLParagraphElement>('status');
    target.textContent = message;
    target.classList.toggle('error', error);
    target.hidden = !message;
  };

  const generationPhaseLabels: Record<string,string> = {preparing:'準備中',text:'文と和訳の準備',audio:'音声を生成中',transcription:'字幕の時刻を解析中',saving:'保存中',done:'完了',error:'失敗'};
  let generationProgressValue=0,generationProgressTarget=0,generationProgressStage='preparing',generationProgressTimer=0;
  const renderGenerationProgress = (value:number,stage:string) => {
    element<HTMLDivElement>('generationProgress').hidden=false;
    element<HTMLElement>('generationProgressPercent').textContent=`${value}%`;
    element<HTMLElement>('generationProgressPhase').textContent=generationPhaseLabels[stage]??stage;
    const track=element<HTMLDivElement>('generationProgress').querySelector<HTMLElement>('[role="progressbar"]');
    track?.setAttribute('aria-valuenow',String(value));
    element<HTMLDivElement>('generationProgressFill').style.width=`${value}%`;
  };
  const setGenerationProgress = (percent:number, stage:string) => {
    generationProgressTarget=Math.max(generationProgressTarget,Math.max(0,Math.min(stage==='done'?100:99,Math.floor(percent))));
    generationProgressValue=Math.max(generationProgressValue,generationProgressTarget);
    generationProgressStage=stage;renderGenerationProgress(generationProgressValue,stage);
    if(stage==='done'||stage==='error'){window.clearInterval(generationProgressTimer);generationProgressTimer=0;}
  };
  const startGenerationProgressEstimate = () => {
    generationProgressValue=0;generationProgressTarget=0;generationProgressStage='preparing';
    window.clearInterval(generationProgressTimer);
    generationProgressTimer=window.setInterval(()=>{
      const ceiling:Record<string,number>={preparing:8,text:20,audio:70,transcription:91,saving:99};
      const limit=Math.min(ceiling[generationProgressStage]??99,generationProgressTarget+6);
      if(generationProgressValue<limit){generationProgressValue++;renderGenerationProgress(generationProgressValue,generationProgressStage);}
    },400);
    setGenerationProgress(1,'preparing');
  };

  const readSettings = (): OverlapSettings => {
    try {
      const saved=JSON.parse(localStorage.getItem(OVERLAP_SETTINGS_KEY)||'{}') as Partial<OverlapSettings>;
      const number=(value:unknown,fallback:number)=>typeof value==='number'&&Number.isFinite(value)?Math.max(0,Math.min(10,value)):fallback;
      const key=(value:unknown,fallback:string)=>typeof value==='string'&&/^[a-z]$/i.test(value)?value.toLowerCase():fallback;
      return {sentenceGapSeconds:number(saved.sentenceGapSeconds,0),repeatGapSeconds:number(saved.repeatGapSeconds,1.5),sentenceRepeatKey:key(saved.sentenceRepeatKey,'r'),currentSentenceKey:key(saved.currentSentenceKey,'a'),previousSentenceKey:key(saved.previousSentenceKey,'w')};
    } catch { return {sentenceGapSeconds:0,repeatGapSeconds:1.5,sentenceRepeatKey:'r',currentSentenceKey:'a',previousSentenceKey:'w'}; }
  };
  const applySettingsToUI = () => {
    element<HTMLInputElement>('sentenceGapSeconds').value=String(settings.sentenceGapSeconds);
    element<HTMLInputElement>('repeatGapSeconds').value=String(settings.repeatGapSeconds);
    element<HTMLInputElement>('sentenceRepeatKey').value=settings.sentenceRepeatKey;
    element<HTMLInputElement>('currentSentenceKey').value=settings.currentSentenceKey;
    element<HTMLInputElement>('previousSentenceKey').value=settings.previousSentenceKey;
  };

  const cancelRepeatGap = () => {
    if (repeatGapTimer !== null) window.clearTimeout(repeatGapTimer);
    repeatGapTimer = null;
    repeatGapPaused = false;
  };
  const cancelSentenceGap = () => { if(sentenceGapTimer!==null)window.clearTimeout(sentenceGapTimer);sentenceGapTimer=null;sentenceGapIndex=null; };

  const updateSentenceLoopControls = () => {
    const duration = fullDuration ?? (Number.isFinite(player.duration) && player.duration > 0 ? player.duration : null);
    sentenceRanges = sentenceAnchors.map((anchor, index) => {
      const nextStart = sentenceAnchors[index + 1]?.start;
      const end = anchor.lastEnd === null ? null : index < sentenceAnchors.length - 1 ?
        (nextStart === null || nextStart === undefined ? null : Math.min(anchor.lastEnd, nextStart)) :
        Math.min(duration ?? Infinity, anchor.lastEnd);
      return anchor.start !== null && end !== null && end > anchor.start + 0.08 ? {start: anchor.start, end} : null;
    });
    if (sentenceLoopIndex !== null && !sentenceRanges[sentenceLoopIndex]) sentenceLoopIndex = null;
    sentenceButtons.forEach((button, index) => {
      const active = sentenceLoopIndex === index;
      button.disabled = !sentenceRanges[index];
      let label = 'この文を繰り返す';
      if (active) label = repeatGapTimer !== null ? `${settings.repeatGapSeconds}秒待機中・解除` :
        repeatGapPaused ? '停止中・解除' : '繰り返し中・解除';
      button.textContent = label;
      button.setAttribute('aria-pressed', String(active));
      button.dataset.repeatState = active ? repeatGapTimer !== null ? 'waiting' : repeatGapPaused ? 'paused' : 'playing' : 'off';
      button.setAttribute('aria-label', button.disabled ? `文 ${index+1} は時刻情報がないため繰り返せません` :
        active ? `文 ${index+1} の繰り返しを解除` : `文 ${index+1} を繰り返す`);
      button.title = button.disabled ? 'この教材には文の時刻情報がありません' : `クリックまたは ${settings.sentenceRepeatKey.toUpperCase()} キーで切り替え`;
      sentenceSections[index]?.classList.toggle('sentence-looping', active);
    });
    element<HTMLParagraphElement>('sentenceTimingNotice').hidden = !sentenceRanges.some(range => !range);
  };

  const sentencePlaybackStart = (range: {start: number}) => Math.max(0, range.start - SENTENCE_LEAD_IN_SECONDS);

  const materialTime = () => clipUrl ? clipStart + player.currentTime : player.currentTime;

  const currentSentenceIndex = () => {
    let current = -1;
    sentenceRanges.forEach((range, index) => { if (range && sentencePlaybackStart(range) <= materialTime() + 0.05) current = index; });
    return current >= 0 ? current : sentenceRanges.findIndex(Boolean);
  };

  const restoreFullAudio = (position: number, play: boolean) => {
    if (!clipUrl || !fullAudioUrl) return;
    const oldClip = clipUrl;
    clipUrl = null;
    player.pause();
    player.src = fullAudioUrl;
    player.load();
    player.addEventListener('loadedmetadata', () => {
      URL.revokeObjectURL(oldClip);
      if (player.src !== fullAudioUrl) return;
      fullDuration = player.duration;
      player.currentTime = Math.min(position, player.duration);
      if (play) void player.play();
    }, {once: true});
  };

  const decodedMaterial = async () => {
    if (!fullAudioBlob) throw new Error('音声が読み込まれていません。');
    if (decodedAudio) return decodedAudio;
    const context = new AudioContext();
    try { decodedAudio = await context.decodeAudioData(await fullAudioBlob.arrayBuffer()); return decodedAudio; }
    finally { await context.close(); }
  };

  const toggleSentenceLoop = async (index: number) => {
    const range = sentenceRanges[index];
    if (!range) return;
    cancelRepeatGap();
    cancelSentenceGap();
    if (sentenceLoopIndex === index) {
      clipGeneration++;
      sentenceLoopIndex = null;
      restoreFullAudio(materialTime(), !player.paused);
    } else {
      const generation = ++clipGeneration;
      try {
        const decoded = await decodedMaterial();
        if (generation !== clipGeneration) return;
        fullDuration = decoded.duration;
        const start = sentencePlaybackStart(range);
        const nextClip = URL.createObjectURL(sentenceClip(decoded, start, range.end));
        const oldClip = clipUrl;
        clipUrl = nextClip;
        clipStart = start;
        sentenceLoopIndex = index;
        player.pause();
        player.src = nextClip;
        player.load();
        if (oldClip) URL.revokeObjectURL(oldClip);
        await player.play();
      } catch (error) { if (generation === clipGeneration) status(String(error), true); }
    }
    updateSentenceLoopControls();
  };

  const playSentence = (index:number) => {
    const range=sentenceRanges[index];if(!range)return;
    cancelSentenceGap();cancelRepeatGap();
    if(clipUrl)restoreFullAudio(range.start,true);
    else {player.currentTime=range.start;void player.play();}
    updateSentenceLoopControls();
  };

  const startRepeatGap = () => {
    if (sentenceLoopIndex === null || repeatGapTimer !== null || repeatGapPaused) return;
    const index = sentenceLoopIndex;
    const range = sentenceRanges[index];
    if (!range) return;
    player.pause();
    repeatGapTimer = window.setTimeout(async () => {
      repeatGapTimer = null;
      if (sentenceLoopIndex !== index || repeatGapPaused) return;
      if (!clipUrl) {
        try {
          const decoded = await decodedMaterial();
          if (sentenceLoopIndex !== index || repeatGapPaused) return;
          fullDuration = decoded.duration;
          const start = sentencePlaybackStart(range);
          clipUrl = URL.createObjectURL(sentenceClip(decoded, start, range.end));
          clipStart = start;
          player.src = clipUrl;
          player.load();
          await player.play();
        } catch (error) { status(String(error), true); }
      } else {
        player.currentTime = 0;
        void player.play();
      }
      updateSentenceLoopControls();
    }, settings.repeatGapSeconds*1000);
    updateSentenceLoopControls();
  };

  const togglePlayback = () => {
    if (repeatGapTimer !== null) {
      window.clearTimeout(repeatGapTimer);
      repeatGapTimer = null;
      repeatGapPaused = true;
      updateSentenceLoopControls();
      return;
    }
    if (repeatGapPaused) {
      repeatGapPaused = false;
      if (clipUrl) player.currentTime = 0;
      void player.play();
      updateSentenceLoopControls();
      return;
    }
    if (player.paused) {
      if (clipUrl && player.ended) player.currentTime = 0;
      void player.play();
    } else player.pause();
  };

  const render = (text: string, words: WordTime[] = [], blocks: SentenceBlock[] = []) => {
    clipGeneration++;
    if (clipUrl) { URL.revokeObjectURL(clipUrl); clipUrl = null; }
    decodedAudio = null;
    fullDuration = null;
    cancelRepeatGap();
    reader.replaceChildren(); nodes = []; times = []; lastSentenceIndex = -1;
    sentenceSections = []; sentenceButtons = []; sentenceAnchors = []; sentenceRanges = []; sentenceProgressLabels = []; sentenceLoopIndex = null;
    const sentences: SentenceBlock[] = blocks.length ? blocks : text.split(/(?<=[.!?])\s+|\n+/).filter(Boolean).map(english => ({english}));
    let wordIndex = 0;
    for (const [sentenceIndex, sentence] of sentences.entries()) {
      const section=document.createElement('section');section.className='reader-sentence';
      sentenceSections.push(section);
      const toolbar=document.createElement('div');toolbar.className='sentence-toolbar';
      const number=document.createElement('span');number.textContent=`文 ${sentenceIndex+1}`;
      const progress=document.createElement('span');progress.className='sentence-progress';progress.textContent=`${sentenceIndex+1}/${sentences.length}`;progress.setAttribute('aria-label',`全${sentences.length}文中 ${sentenceIndex+1}文目`);sentenceProgressLabels.push(progress);
      const repeat=document.createElement('button');repeat.type='button';repeat.className='sentence-repeat';
      repeat.setAttribute('aria-label',`文 ${sentenceIndex+1} を繰り返す`);
      repeat.addEventListener('click',()=>toggleSentenceLoop(sentenceIndex));
      sentenceButtons.push(repeat);toolbar.append(number,progress,repeat);section.append(toolbar);
      let sentenceStart: number | null = null;
      let sentenceLastEnd: number | null = null;
      const english=document.createElement('div');english.className='reader-english';
      for (const part of (sentence.english.match(/\S+|\s+/g) ?? [])) {
        if (/^\s+$/.test(part)) { english.append(document.createTextNode(part)); continue; }
        const span=document.createElement('span');span.className='word';span.textContent=part;
        const match=words.findIndex((word,index)=>index>=wordIndex&&index<wordIndex+7&&normalize(word.word)===normalize(part));
        times.push(match>=0?words[match].start:null);nodes.push(span);
        if(match>=0){wordIndex=match+1;sentenceStart??=words[match].start;sentenceLastEnd=words[match].end;}
        span.addEventListener('click',()=>{cancelRepeatGap();clipGeneration++;sentenceLoopIndex=null;updateSentenceLoopControls();const time=times[nodes.indexOf(span)]??0;if(clipUrl)restoreFullAudio(time,true);else{player.currentTime=time;void player.play();}});
        english.append(span);
      }
      section.append(english);
      const japanese=document.createElement('p');japanese.className='reader-japanese';japanese.textContent=sentence.japanese||'\u548c\u8a33\u306a\u3057';section.append(japanese);
      const vocabulary=document.createElement('div');vocabulary.className='reader-vocabulary';
      for(const entry of sentence.vocabulary||[]){const note=document.createElement('span');note.textContent=`${entry.word}: ${entry.meaning}`;vocabulary.append(note);}
      if(!vocabulary.childElementCount)vocabulary.textContent='\u8a9e\u5f59\u30e1\u30e2\u306a\u3057';
      section.append(vocabulary);reader.append(section);
      sentenceAnchors.push({start:sentenceStart,lastEnd:sentenceLastEnd});
    }
    const known = times.map((value, index) => value === null ? -1 : index).filter(index => index >= 0);
    if (known.length === 0) {
      const step = Math.max(1, text.length / 13) / Math.max(1, nodes.length);
      times = times.map((_, index) => index * step);
    } else {
      for (let index = 0; index < known[0]; index++) times[index] = Math.max(0, (times[known[0]] ?? 0) - (known[0] - index) * 0.24);
      for (let cursor = 0; cursor < known.length - 1; cursor++) {
        const left = known[cursor], right = known[cursor + 1];
        for (let index = left + 1; index < right; index++) times[index] = (times[left] ?? 0) + ((times[right] ?? 0) - (times[left] ?? 0)) * (index - left) / (right - left);
      }
      const tail = known.at(-1) ?? 0;
      for (let index = tail + 1; index < times.length; index++) times[index] = (times[tail] ?? 0) + (index - tail) * 0.23;
    }
    updateSentenceLoopControls();
  };

  const tick = () => {
    if (!nodes.length) return;
    let active = -1;
    times.forEach((time, index) => { if (time !== null && time <= materialTime() + 0.05) active = index; });
    active = Math.max(0, active);
    nodes.forEach((node, index) => { node.classList.toggle('past', index < active); node.classList.toggle('active', index === active); });
    reader.querySelectorAll('.reader-sentence').forEach(section=>section.classList.toggle('sentence-active',section.contains(nodes[active])));
    const sentenceIndex=sentenceSections.findIndex(section=>section.contains(nodes[active]));
    const progress=element<HTMLParagraphElement>('sentenceProgress');
    progress.hidden=sentenceIndex<0;
    if(sentenceIndex>=0)progress.textContent=`文 ${sentenceIndex+1}/${sentenceSections.length}`;
    sentenceProgressLabels.forEach((label,index)=>{label.classList.toggle('current',index===sentenceIndex);label.setAttribute('aria-current',index===sentenceIndex?'step':'false');});
    if (element<HTMLInputElement>('scroll').checked && sentenceIndex >= 0 && sentenceIndex !== lastSentenceIndex) {
      const transcript = reader.parentElement;
      const section = sentenceSections[sentenceIndex];
      if (transcript && section) {
        const top = transcript.scrollTop + section.getBoundingClientRect().top - transcript.getBoundingClientRect().top;
        transcript.scrollTo({ top, behavior: 'smooth' });
      }
    }
    lastSentenceIndex = sentenceIndex;
    if (!player.paused) frame = requestAnimationFrame(tick);
  };

  const applySentenceGap = () => {
    if(clipUrl||sentenceLoopIndex!==null||sentenceGapTimer!==null||!sentenceRanges.length)return;
    const index=sentenceRanges.findIndex((range,i)=>range&&sentenceRanges[i+1]&&materialTime()>=range.end-0.025&&materialTime()<sentencePlaybackStart(sentenceRanges[i+1]!)-0.015);
    if(index<0||sentenceGapIndex===index)return;
    const next=sentenceRanges[index+1];if(!next)return;
    sentenceGapIndex=index;player.pause();
    sentenceGapTimer=window.setTimeout(()=>{
      sentenceGapTimer=null;
      if(clipUrl||sentenceLoopIndex!==null||!player.src)return;
      player.currentTime=sentencePlaybackStart(next);void player.play();
    },settings.sentenceGapSeconds*1000);
  };

  settings=readSettings();applySettingsToUI();
  element<HTMLButtonElement>('saveOverlapSettings').addEventListener('click',()=>{
    const sentenceGapSeconds=Number(element<HTMLInputElement>('sentenceGapSeconds').value),repeatGapSeconds=Number(element<HTMLInputElement>('repeatGapSeconds').value);
    const sentenceRepeatKey=element<HTMLInputElement>('sentenceRepeatKey').value.trim().toLowerCase();
    const currentSentenceKey=element<HTMLInputElement>('currentSentenceKey').value.trim().toLowerCase();
    const previousSentenceKey=element<HTMLInputElement>('previousSentenceKey').value.trim().toLowerCase();
    const keySet=[sentenceRepeatKey,currentSentenceKey,previousSentenceKey];
    if(!Number.isFinite(sentenceGapSeconds)||sentenceGapSeconds<0||sentenceGapSeconds>10||!Number.isFinite(repeatGapSeconds)||repeatGapSeconds<0||repeatGapSeconds>10||keySet.some(key=>!/^[a-z]$/.test(key))||new Set(keySet).size!==keySet.length){
      element<HTMLParagraphElement>('overlapSettingsStatus').textContent='無音時間は0〜10秒、各キーは重複しない英字1文字で設定してください。';return;
    }
    settings={sentenceGapSeconds,repeatGapSeconds,sentenceRepeatKey,currentSentenceKey,previousSentenceKey};localStorage.setItem(OVERLAP_SETTINGS_KEY,JSON.stringify(settings));
    updateSentenceLoopControls();element<HTMLParagraphElement>('overlapSettingsStatus').textContent=`保存しました（現在文: ${currentSentenceKey.toUpperCase()}、前の文: ${previousSentenceKey.toUpperCase()}、繰り返し: ${sentenceRepeatKey.toUpperCase()}）。`;
  });

  const showMeta = (item: SavedData) => {
    const cost = item.cost ?? {};
    const aiSummary = item.ai_summary?.trim() || '\u307e\u3060\u3042\u308a\u307e\u305b\u3093';
    const lines = [
      `\u6559\u6750\u540d: ${item.title ?? '\u2014'}`,
      `教材ID: ${item.material_id ?? '\u2014'}`,
      `AI\u8981\u7d04: ${aiSummary}`,
      `\u5358\u8a9e\u6570: ${item.word_count ?? '\u2014'} / \u6587\u5b57\u6570: ${item.character_count ?? '\u2014'} / \u97f3\u58f0: ${item.audio_seconds ?? '\u2014'}\u79d2`,
      `\u4f5c\u6210\u65e5\u6642: ${formatJstTimestamp(item.created_at)}`,
      `\u97f3\u58f0: ${item.voice ?? '\u2014'} / \u8a71\u3057\u65b9: ${item.style ?? '\u2014'}`,
      `\u6599\u91d1: $${Number(cost.total_usd ?? 0).toFixed(6)}`,
      `\u97f3\u58f0\u30d5\u30a1\u30a4\u30eb: ${item.audio_file ?? '\u2014'}`,
    ].filter(Boolean);
    element<HTMLDivElement>('savedMeta').textContent = lines.join('\n');
  };

  const refreshSaved = async () => {
    const locationResponse = await fetch('/api/storage/status');
    if (locationResponse.ok) {
      const location = await locationResponse.json() as { role: string; directory: string };
      const target = document.getElementById('storageLocation');
      if (target) target.textContent = `音声ファイル保存先（${location.role === 'test' ? 'テスト用' : '本番用'}）: ${location.directory}`;
    }
    const response = await fetch('/api/materials/overlap-list');
    if (!response.ok) throw new Error('Could not load saved materials.');
    const result = await response.json() as {items: SavedMaterial[]; count: number; legacy_import_warnings?:Array<{file:string;error:string}>};
    if(result.legacy_import_warnings?.length)status(`Legacy material import failed for ${result.legacy_import_warnings.length} file(s). Check the vocabulary management status for details.`);
    savedItems = result.items;
    const list = element<HTMLSelectElement>('savedList');
    list.replaceChildren();
    const count = document.getElementById('savedMaterialCount');
    if (count) count.textContent = `${result.count}\u4ef6`;
    if (!savedItems.length) { list.add(new Option('No saved materials', '')); return; }
    for (const item of savedItems) {
      const key = item.material_id;
      const excerpt = (item.summary ?? item.text ?? item.text_content ?? '').slice(0, 55);
      list.add(new Option(`${item.title} \u2014 ${excerpt}${item.file ? '' : ' [no audio]'}`, key));
    }
  };

  element<HTMLButtonElement>('refreshSavedMaterials').addEventListener('click', () => { void refreshSaved().then(async () => { const selected = savedItems.find(item => item.material_id === element<HTMLSelectElement>('savedList').value); if (selected) await loadSaved(selected); }).catch(error => status(String(error), true)); });
  window.addEventListener('english-overlap-tab-change', event => { if ((event as CustomEvent).detail?.tabId === 'overlap') void refreshSaved().then(async () => { const selected = savedItems.find(item => item.material_id === element<HTMLSelectElement>('savedList').value); if (selected) await loadSaved(selected); }).catch(error => status(String(error), true)); });

  const loadSaved = async (item: SavedMaterial) => {
    if (!item.file) {
      document.body.dataset.materialId = item.material_id;
      source.value = item.text_content ?? '';
      if (fullAudioUrl) URL.revokeObjectURL(fullAudioUrl);
      fullAudioUrl = null; fullAudioBlob = null; player.pause(); player.removeAttribute('src'); player.load();
      render(source.value, [], []);
      for (const id of ['play','back','restart']) element<HTMLButtonElement>(id).disabled = true;
      showMeta({ ...item, text: item.text_content, audio_file: '', ai_summary: item.ai_summary });
      status('No audio is available for this material. Generate audio to play it.');
      return;
    }
    const response = await fetch(`/saved-data?material_id=${encodeURIComponent(item.material_id)}`);
    if (!response.ok) throw new Error('Could not load material data.');
    const data = await response.json() as SavedData;
    if (!data.audio_file) throw new Error('This material has no audio file.');
    const audioResponse = await fetch(`/saved-audio?name=${encodeURIComponent(data.audio_file)}`);
    if (!audioResponse.ok) throw new Error('Could not load saved materials.');
    source.value = data.text ?? '';
    (document.getElementById('voice') as HTMLSelectElement).value = data.voice ?? 'marin';
    (document.getElementById('style') as HTMLSelectElement).value = data.style ?? 'natural';
    if (fullAudioUrl) URL.revokeObjectURL(fullAudioUrl);
    fullAudioBlob = await audioResponse.blob(); fullAudioUrl = URL.createObjectURL(fullAudioBlob);
    player.src = fullAudioUrl; player.load(); render(data.text ?? '', data.words ?? [],data.blocks??[]);
    for (const id of ['play','back','restart']) element<HTMLButtonElement>(id).disabled = false;
    showMeta({ ...data, ai_summary: item.ai_summary }); status('Loaded saved material.');
  };

  element<HTMLSelectElement>('savedList').addEventListener('change', () => {
    const item = savedItems.find(candidate => candidate.material_id === element<HTMLSelectElement>('savedList').value);
    if (item) void loadSaved(item).catch(error => status(String(error), true));
  });
  element<HTMLTextAreaElement>('overlapSource').addEventListener('input', () => {
    element<HTMLDivElement>('textStats').textContent = `単語 ${source.value.trim() ? source.value.trim().split(/\s+/).length : 0} / 文字 ${source.value.length} / 上限 20000`;
  });
  element<HTMLButtonElement>('generate').addEventListener('click', async () => {
    const text = source.value.trim(); if (!text) { status('英文を入力してください。', true); return; }
    const button = element<HTMLButtonElement>('generate'); button.disabled = true; status('音声と字幕を作成しています…');
    try {
      startGenerationProgressEstimate();
      const response = await fetch('/generate', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ text, voice: element<HTMLSelectElement>('voice').value, style: element<HTMLSelectElement>('style').value, material_id: document.body.dataset.materialId ?? null }) });
      type GenerationResult={error?:string;audio:string;words?:WordTime[];blocks?:SentenceBlock[];audio_file:string;cost?:{total_usd?:number};material_id?:string};
      let result:GenerationResult|undefined;
      if(response.headers.get('content-type')?.includes('application/x-ndjson')){
        const reader=response.body?.getReader();if(!reader)throw new Error('生成進捗を読み取れませんでした。');
        const decoder=new TextDecoder();let pending='';
        while(true){
          const {value,done}=await reader.read();pending+=decoder.decode(value??new Uint8Array(),{stream:!done});
          const lines=pending.split('\n');pending=lines.pop()??'';
          for(const line of lines){if(!line.trim())continue;const event=JSON.parse(line) as {type:string;percent?:number;stage?:string;result?:GenerationResult;error?:string};
            if(event.type==='progress'){setGenerationProgress(event.percent??0,event.stage??'');status(`音声と字幕を生成しています。進捗率は目安です（${event.percent??0}%）。`);}
            else if(event.type==='complete')result=event.result;
            else if(event.type==='error')throw new Error(event.error??'生成に失敗しました。');
          }
          if(done)break;
        }
        if(pending.trim()){const event=JSON.parse(pending) as {type:string;result?:GenerationResult;error?:string};if(event.type==='complete')result=event.result;else if(event.type==='error')throw new Error(event.error??'生成に失敗しました。');}
      }else result=await response.json() as GenerationResult;
      if (!response.ok) throw new Error(result?.error ?? '音声を生成できませんでした。');
      if(!result)throw new Error('生成結果を受信できませんでした。');
      if (!response.ok) throw new Error(result.error ?? '音声を生成できませんでした。');
      if (result.material_id) document.body.dataset.materialId = result.material_id;
      if (fullAudioUrl) URL.revokeObjectURL(fullAudioUrl);
      fullAudioBlob = await (await fetch(result.audio)).blob(); fullAudioUrl = URL.createObjectURL(fullAudioBlob);
      player.src = fullAudioUrl; player.load(); render(text, result.words ?? [],result.blocks??[]);
      for (const id of ['play','back','restart']) element<HTMLButtonElement>(id).disabled = false;
      setGenerationProgress(100,'done');
      status(`完了。概算 $${Number(result.cost?.total_usd ?? 0).toFixed(6)}。教材を保存しました。`);
      await refreshSaved();
    } catch (error) { setGenerationProgress(Number.parseInt(element<HTMLElement>('generationProgressPercent').textContent??'0',10)||0,'error');status(String(error), true); } finally { button.disabled = false; }
  });
  element<HTMLButtonElement>('play').addEventListener('click', togglePlayback);
  document.addEventListener('keydown',event=>{
    const key=event.key.toLowerCase(),repeatKey=key===settings.sentenceRepeatKey,currentKey=key===settings.currentSentenceKey,previousKey=key===settings.previousSentenceKey;
    if(!(event.code==='Space'||repeatKey||currentKey||previousKey)||event.repeat||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey||event.isComposing||!overlapActive||!player.src)return;
    const target=event.target as HTMLElement|null;
    if(target?.closest('input,textarea,select,[contenteditable="true"]'))return;
    if(event.code==='Space'&&target?.closest('button:not(.sentence-repeat)'))return;
    if(repeatKey){
      const index=sentenceLoopIndex ?? currentSentenceIndex();
      if(index<0||!sentenceRanges[index])return;
      event.preventDefault();void toggleSentenceLoop(index);return;
    }
    if(currentKey||previousKey){
      const current=currentSentenceIndex();if(current<0)return;
      const target=currentKey?current:Math.max(0,current-1);if(!sentenceRanges[target])return;
      event.preventDefault();playSentence(target);return;
    }
    event.preventDefault();togglePlayback();
  });
  element<HTMLButtonElement>('back').addEventListener('click', () => { cancelSentenceGap();cancelRepeatGap();clipGeneration++;sentenceLoopIndex=null;updateSentenceLoopControls();const time=Math.max(0,materialTime()-3);if(clipUrl)restoreFullAudio(time,false);else player.currentTime=time; });
  element<HTMLButtonElement>('restart').addEventListener('click', () => { cancelSentenceGap();cancelRepeatGap();clipGeneration++;sentenceLoopIndex=null;updateSentenceLoopControls();if(clipUrl)restoreFullAudio(0,true);else{player.currentTime=0;void player.play();} });
  element<HTMLInputElement>('speed').addEventListener('input', event => {
    const speed = Number((event.currentTarget as HTMLInputElement).value); player.playbackRate = speed;
    element<HTMLSpanElement>('speedLabel').textContent = `${speed.toFixed(2)}×`;
  });
  player.addEventListener('play', () => { cancelAnimationFrame(frame); tick(); });
  player.addEventListener('timeupdate',applySentenceGap);
  player.addEventListener('loadedmetadata', () => {
    if (!clipUrl && Number.isFinite(player.duration)) fullDuration = player.duration;
    updateSentenceLoopControls();
  });
  player.addEventListener('ended', () => {
    const range = sentenceLoopIndex === null ? null : sentenceRanges[sentenceLoopIndex];
    if(range)startRepeatGap();
    else if (element<HTMLInputElement>('loop').checked) { player.currentTime = 0; void player.play(); }
  });
  void refreshSaved().catch(error => status(String(error), true));
}
