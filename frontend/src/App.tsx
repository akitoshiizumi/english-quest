import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { setupOverlapControls } from './overlap';

type TabId = 'overlap' | 'practice' | 'manage' | 'add' | 'database';
type PageId = TabId | 'dashboard';
type Tab = { id: TabId; label: string; content: ReactNode };

const scriptLoads = new Map<string, Promise<void>>();
function loadScript(src: string): Promise<void> {
  const pending = scriptLoads.get(src);
  if (pending) return pending;
  const load = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src;
    script.defer = true;
    script.dataset.legacySrc = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`画面機能を読み込めませんでした: ${src}`));
    document.body.append(script);
  });
  scriptLoads.set(src, load);
  return load;
}

function OverlapPage() {
  return <>
    <details className="card collapsible-section" open>
      <summary><h2>練習する英文</h2></summary>
      <p id="storageLocation" className="muted" aria-live="polite">教材の保存先を確認しています…</p>
      <textarea id="overlapSource" defaultValue="" aria-label="オーバーラッピング用英文" />
      <div id="textStats" className="muted" />
      <p className="muted">英文から音声と字幕を作ります。音声生成にはAPIを使用します。</p>
      <div className="row">
        <label className="field">音声<select id="voice"><option value="marin">Marin（推奨）</option></select></label>
        <label className="field">話し方<select id="style"><option value="natural">自然・標準</option></select></label>
        <button className="primary" id="generate">音声と字幕を生成</button>
      </div>
      <p id="voiceInfo" className="muted" />
      <div id="generationProgress" className="generation-progress" hidden>
        <div className="generation-progress-heading"><strong id="generationProgressPercent">0%</strong><span>目安</span><span id="generationProgressPhase">準備中</span></div>
        <div className="generation-progress-track" role="progressbar" aria-label="音声と字幕の生成進捗" aria-valuemin={0} aria-valuemax={100} aria-valuenow={0}><div id="generationProgressFill" /></div>
      </div>
      <p id="status" className="status" aria-live="polite" />
    </details>
    <details className="card collapsible-section" id="studySetCard" open><summary><h2>フィルタした語彙で重ね読み用英文を作成</h2></summary>
      <p className="muted">対象語を確認し、英文を作成・保存してオーバーラッピングします。</p>
      <div className="practice-controls"><div className="row">
        <label>カテゴリ <select id="studySetCategory"><option value="">すべて</option></select></label>
        <label>方向 <select id="studySetDirection"><option value="en_to_ja">英語 → 日本語</option><option value="ja_to_en">日本語 → 英語</option></select></label>
        <label>件数 <input id="studySetCount" type="number" min="1" max="50" defaultValue="50" /></label>
        <label>習熟状況 <select id="studySetMasteryStatus"><option value="all">すべて</option><option value="unlearned">未学習</option><option value="review">要復習</option><option value="known">覚えた</option></select></label>
        <label><input id="studySetIncludeUnstudied" type="checkbox" defaultChecked />未学習語も含める</label>
        <label>判定に使う出題数（直近N回） <input id="studySetRecentAttempts" type="number" min="1" max="100" placeholder="指定なし" /></label>
        <label>直近正解率の上限% <input id="studySetMaxRecentAccuracy" type="number" min="0" max="100" placeholder="指定なし" /></label>
        <label><input id="studySetIncludeInsufficientHistory" type="checkbox" />N回未満・履歴なしも対象</label>
        <p className="muted full-width">通常はN回以上の履歴がある語だけを対象にします。チェックすると履歴が0回の語も含めます。正答率は履歴がある語だけ指定した直近N回で計算し、履歴0回の語には適用しません。</p>
        <label>CEFR <select id="studySetDifficulty"><option value="">指定なし</option>{['A1','A2','B1','B2','C1','C2'].map(level=><option key={level}>{level}</option>)}</select></label>
        <label>英文の作り方 <select id="studySetMode"><option value="per_vocabulary">語彙ごとに1文</option><option value="article">対象語彙をすべて使って記事</option></select></label>
        <label>長さ <select id="setLength"><option value="short">短め</option><option value="medium">標準</option><option value="long">長め</option></select></label>
        <label>テーマ（カテゴリ） <select id="setTheme"><option value="">指定なし</option></select></label>
        <button id="planStudySet">対象語を選ぶ</button>
      </div></div>
      <div id="studySetPlan" />
      <label className="field full-width">生成した英文<textarea id="source" aria-label="生成英文の編集" /></label>
      <div className="row"><button id="generateStudySet" disabled>英文を作成</button><button id="resumeStudySet" hidden disabled>失敗した生成を再開</button></div>
      <p id="studySetStatus" className="status" aria-live="polite" />
    </details>
    <details className="card collapsible-section" open>
      <summary><h2>保存済み教材</h2></summary>
      <div className="row"><p className="muted">&#20445;&#23384;&#28168;&#12415;&#25945;&#26448;: <span id="savedMaterialCount">&#35501;&#12415;&#36796;&#12415;&#20013;&#8230;</span></p><button id="refreshSavedMaterials" type="button">&#19968;&#35239;&#12434;&#26356;&#26032;</button></div>
      <select id="savedList" className="saved" size={6} aria-label="保存済み教材"><option value="">読み込み中…</option></select>
      <div id="savedMeta" className="meta">教材を選ぶと内容と音声を読み込みます。</div>
    </details>
    <details className="card collapsible-section" open>
      <summary><h2>音声に合わせて発話</h2></summary>
      <div className="overlap-workspace">
        <div className="overlap-transcript"><p id="sentenceProgress" className="muted" aria-live="polite" hidden /><div id="reader" className="reader" aria-live="off">先に音声を生成するか、保存済み教材を選んでください。</div>
          <p id="sentenceTimingNotice" className="muted" role="status" hidden>この教材には一部の文の時刻情報がありません。時刻がない文は繰り返せません。</p>
        </div>
        <aside className="overlap-sidebar" aria-label="音声コントロールと設定">
          <p className="muted">Space: 再生・停止。文の R キーで繰り返し、A で現在文、W で前の文を再生。</p>
          <div className="row overlap-play-controls">
            <button id="play" disabled>再生 / 停止</button><button id="back" disabled>3秒戻る</button><button id="restart" disabled>最初から</button>
            <label>速度 <span id="speedLabel">1.00×</span><input id="speed" type="range" min="0.2" max="3" step="0.05" defaultValue="1" /></label>
            <label><input id="loop" type="checkbox" />繰り返し</label><label><input id="scroll" type="checkbox" defaultChecked />字幕に追従</label>
          </div>
          <details className="overlap-settings" open><summary>音声設定</summary><div className="row">
            <label>文間の無音（秒）<input id="sentenceGapSeconds" type="number" min="0" max="10" step="0.1" defaultValue="0" /></label>
            <label>文リピート間の無音（秒）<input id="repeatGapSeconds" type="number" min="0" max="10" step="0.1" defaultValue="1.5" /></label>
            <label>文リピートキー<input id="sentenceRepeatKey" type="text" maxLength={1} defaultValue="r" /></label>
            <label>現在の文キー<input id="currentSentenceKey" type="text" maxLength={1} defaultValue="a" /></label>
            <label>前の文キー<input id="previousSentenceKey" type="text" maxLength={1} defaultValue="w" /></label>
            <button id="saveOverlapSettings" type="button">設定を保存</button>
          </div><p id="overlapSettingsStatus" className="muted" aria-live="polite" /></details>
          <audio id="player" />
        </aside>
      </div>
    </details>
  </>;
}

function PracticePage() {
  return <>
    <section className="card learning-shell" id="learningCard">
      <div className="learning-heading"><div><p className="eyebrow">VOCABULARY PRACTICE</p><h2>語彙練習</h2></div><span id="shortcutHint" className="shortcut-hint" aria-live="polite">問題中：A / U / S / I で答えを見る。答え表示後：A / U でもう一度、S / I で覚えていた。</span><button id="focusModeToggle" type="button" aria-pressed="false">&#x96c6;&#x4e2d;&#x30e2;&#x30fc;&#x30c9;</button></div>
      <details className="practice-controls collapsible-section" open><summary>出題条件</summary><div><div className="row"><label>方向 <label>&#x51fa;&#x984c;&#x65b9;&#x6cd5; <select id="reviewMode"><option value="standard">&#x901a;&#x5e38;&#x306e;&#x7df4;&#x7fd2;</option><option value="due">&#x671f;&#x9650;&#x5230;&#x6765;&#x8a9e;&#x3092;&#x81ea;&#x52d5;&#x9078;&#x5b9a;</option></select></label><span id="dueReviewHint" className="muted" hidden>&#x6700;&#x65b0;&#x306e;&#x5b66;&#x7fd2;&#x5c65;&#x6b74;&#x304b;&#x3089;&#x3001;&#x671f;&#x9650;&#x304c;&#x6765;&#x305f;&#x8a9e;&#x5f59;&#x306e;&#x307f;&#x3092;&#x9078;&#x3073;&#x307e;&#x3059;&#x3002;</span><select id="learningDirection"><option value="en_to_ja">英語 → 日本語</option><option value="ja_to_en">日本語 → 英語</option></select></label>
        <label>カテゴリ <select id="learningCategory"><option value="">すべて</option></select></label>
        <label>件数 <input id="setCount" type="number" min="1" max="1000" defaultValue="50" /></label>
        <label>習熟状況 <select id="masteryStatus"><option value="all">すべて</option><option value="unlearned">未学習</option><option value="review">要復習</option><option value="known">覚えた</option></select></label>
        <label className="standard-only"><input id="includeUnstudied" type="checkbox" defaultChecked />未学習語も含める</label>
        <label>直近N回 <input id="recentAttempts" type="number" min="1" max="100" placeholder="指定なし" /></label>
        <label>直近正解率の上限% <input id="maxRecentAccuracy" type="number" min="0" max="100" placeholder="指定なし" /></label>
        <label className="standard-only"><input id="includeInsufficientHistory" type="checkbox" />N回未満の履歴も対象</label>
        <label>全回間違い <select id="allAttemptsIncorrect"><option value="false">指定なし</option><option value="true">全回間違えた語のみ</option></select></label>
        <label className="standard-only"><input id="lastAttemptIncorrect" type="checkbox" />{'\u524d\u56de\u9593\u9055\u3048\u305f\u8a9e\u306e\u307f'}</label>
        <label>CEFR <select id="setDifficulty"><option value="">指定なし</option>{['A1','A2','B1','B2','C1','C2'].map(level=><option key={level}>{level}</option>)}</select></label>
        <button className="primary" id="startLearning">練習を始める</button></div></div></details>
      <section id="vocabularyStage" className="vocabulary-stage" aria-label="出題語"><button id="exitFocusMode" className="focus-exit" type="button">&#x96c6;&#x4e2d;&#x30e2;&#x30fc;&#x30c9;&#x3092;&#x7d42;&#x4e86;</button>
        <div className="stage-topline"><p className="stage-label">今回の出題</p><p id="learningProgress" className="progress-label" aria-live="polite">練習開始前</p></div>
        <div id="vocabularyHistory" className="vocabulary-history" aria-label={'\u904e\u53bb\u306e\u56de\u7b54\u5c65\u6b74'} />
        <div id="vocabularyQuestion" className="vocabulary-prompt" aria-live="polite">カテゴリと方向を選んで開始してください。</div>
        <div id="vocabularyAnswer" className="vocabulary-answer" hidden />
      </section>
      <div className="row learning-actions"><button className="primary" id="revealAnswer" disabled>答えを見る (A / U / S / I)</button><button className="again-action" id="rateAgain" disabled>もう一度 (A / U)</button><button className="known-action" id="rateKnown" disabled>覚えていた (S / I)</button></div>
      <p id="learningStatus" className="status" aria-live="polite" />
    </section>
    <details className="card collapsible-section" open><summary><h2>キー設定</h2></summary><p>操作ごとに複数の英字キーを割り当てられます。</p>
      <label>答えを見る <input id="revealKeys" defaultValue="a,u,s,i" /></label><label>もう一度 <input id="againKeys" defaultValue="a,u" /></label><label>覚えていた <input id="knownKeys" defaultValue="s,i" /></label>
      <button id="saveKeySettings">保存</button><button id="resetKeySettings">初期値</button>
    </details>
  </>;
}

function DashboardPage() {
  return <section className="card dashboard" id="dashboardPage">
    <p className="eyebrow">ENGLISH QUEST</p><h2>学習ダッシュボード</h2>
    <section className="adventure-card" aria-label="English Questの成長状況">
      <div className="adventure-heading"><div><p className="eyebrow">YOUR ADVENTURE</p><h3>今日のクエスト</h3><p className="adventure-tagline">挑戦を重ねて、次のレベルへ。</p></div><div className="adventure-level"><span>LEVEL</span><strong id="adventureLevel">Lv.1</strong></div></div>
      <div className="adventure-progress-row"><span><strong id="adventureTotalXp">0 XP</strong> 累計</span><span id="adventureNextLevel">あと100 XPでレベルアップ</span></div>
      <progress id="adventureLevelProgress" max={100} value={0} aria-label="次のレベルまでの進捗" />
      <div className="adventure-meta"><span id="adventureStreak">🔥 連続 0日</span><span id="adventureBestStreak">最長 0日</span><span id="adventureTodayXp">今日 +0 XP</span></div>
      <div id="adventureQuests" className="adventure-quests" aria-live="polite"><p>冒険の進捗を読み込み中…</p></div>
      <p className="adventure-note">語彙に答える・声に出して練習することでXPを獲得。正解かどうかは問いません。</p>
    </section>
    <label>学習期間 <select id="statisticsRange" defaultValue="30"><option value="7">7日間</option><option value="30">30日間</option><option value="90">90日間</option><option value="all">全期間</option></select></label>
    <details id="learningGoalsSection" className="dashboard-disclosure collapsible-section" open><summary>累計学習目標</summary>
      <p className="muted">目標の進捗は表示期間に関係なく累計で表示します。語彙数は1回以上回答した異なる語彙数です。</p>
      <form id="learningGoalsForm" className="learning-goals-form">
        <label>オーバーラッピング目標（時間）<input id="overlapGoalHours" type="number" min="0.1" max="10000" step="0.1" placeholder="未設定" /></label>
        <label>語彙学習目標（語）<input id="vocabularyGoalCount" type="number" min="1" max="1000000" step="1" placeholder="未設定" /></label>
        <button id="saveLearningGoals" type="submit">目標を保存</button>
      </form>
      <p id="learningGoalsStatus" className="muted" role="status" aria-live="polite" />
      <div id="learningGoalsProgress" className="learning-goals-progress" aria-live="polite"><p>累計を読み込み中…</p></div>
    </details>
    <details className="dashboard-disclosure collapsible-section" open><summary>データベース全体の累計</summary><p className="muted">語彙は登録数、学習対象はアーカイブを除いた数、語義は意味ごとの数です。数が同じ場合は語彙数にまとめます。学習実績は新形式で記録された累積回答で、正解率は自己評価による値です。</p><div id="databaseStatistics" className="stat-grid" /></details>
    <details id="vocabularyPerformanceDetails" className="dashboard-disclosure"><summary>語彙別の学習実績（全期間）</summary><h3>語彙別の学習実績</h3><div className="row"><label>語彙を検索 <input id="performanceSearch" placeholder="英語・日本語" /></label><label>並べ替え <select id="performanceSort"><option value="again">正解率が低い順</option><option value="attempts">登場数が多い順</option><option value="known">正解数が多い順</option><option value="english">英語順</option></select></label></div><div id="performanceCount" className="muted" /><section className="distribution-section"><h4>語彙の分布</h4><p className="muted">縦軸は語彙数です。横軸の指標を切り替えて学習状態の分布を確認できます。語彙検索の条件も反映されます。</p><label>横軸 <select id="vocabularyDistributionMetric"><option value="accuracy">自己評価正解率</option><option value="attempts">登場回数</option><option value="known">正解数</option><option value="again">再学習数</option></select></label><div id="vocabularyDistributionSummary" className="muted" aria-live="polite" /><div id="vocabularyDistributionChart" className="distribution-chart" /></section><div className="view-switch" role="group" aria-label="語彙別実績の表示形式"><button id="vocabularyViewTable" type="button" aria-pressed="true">一覧</button><button id="vocabularyViewChart" type="button" aria-pressed="false">グラフ</button></div><div id="vocabularyPerformance" /><div id="vocabularyPerformanceChart" className="learning-chart" hidden /></details>
    <div id="statisticsPanel" aria-live="polite" />
    <details className="daily-performance-section dashboard-disclosure collapsible-section" open><summary>日付ごとの学習実績</summary><div className="view-switch" role="group" aria-label="日付別実績の表示形式"><button id="dailyViewTable" type="button" aria-pressed="true">一覧</button><button id="dailyViewChart" type="button" aria-pressed="false">グラフ</button><label>グラフの項目 <select id="dailyChartMetric"><option value="answers">回答数</option><option value="duration">学習時間（分）</option></select></label></div><div id="dailyLearningTable" /><div id="dailyLearningChart" className="learning-chart" hidden /></details>
  </section>;
}

function ManagePage() {
  return <section className="card" id="manageCard"><h2>語彙管理（閲覧・編集）</h2>
    <details id="vocabularyManagementSection" className="dashboard-disclosure collapsible-section" open><summary>語彙一覧・編集</summary>
    <div className="row"><input id="vocabularySearch" placeholder="英語または日本語で検索" /><label><input id="includeArchived" type="checkbox" />アーカイブも表示</label><button id="searchVocabulary">検索</button></div>
    <div className="vocabulary-pager"><button id="vocabularyFirstPage">先頭</button><button id="vocabularyPreviousPage">前へ</button><span id="vocabularyPageRange">読み込み中…（</span><label className="sr-only" htmlFor="vocabularyPageInput">ページ番号</label><input id="vocabularyPageInput" className="vocabulary-page-input" type="number" min="1" step="1" aria-label="ページ番号" defaultValue="1" /><span> / <span id="vocabularyPageCount">1</span>ページ）</span><button id="vocabularyNextPage">次へ</button><button id="vocabularyLastPage">末尾</button></div><span id="vocabularyPageStatus" className="sr-only" aria-live="polite">読み込み中…</span>
    <table className="vocabulary-table"><thead><tr><th data-sort-header="english"><button data-vocab-sort="english" aria-label="英語で並べ替え">英語</button></th><th data-sort-header="japanese"><button data-vocab-sort="japanese" aria-label="日本語の意味で並べ替え">日本語</button></th><th data-sort-header="part_of_speech"><button data-vocab-sort="part_of_speech" aria-label="品詞で並べ替え">品詞</button></th><th data-sort-header="tags"><button data-vocab-sort="tags" aria-label="タグで並べ替え">タグ</button></th><th data-sort-header="difficulty"><button data-vocab-sort="difficulty" aria-label="CEFRで並べ替え">CEFR</button></th><th>操作</th></tr></thead><tbody id="vocabularyRows" /></table>
    <button id="exportVocabulary">語彙CSVを保存</button></details>
    <details id="managedMaterialsSection" className="dashboard-disclosure collapsible-section" open><summary>教材</summary><button id="exportMaterials">教材CSVを保存</button>
    <div className="row"><p className="muted">Materials: <span id="materialCount">Loading?</span></p><button id="refreshMaterials" type="button">&#19968;&#35239;&#12434;&#26356;&#26032;</button></div>
    <table><thead><tr><th>教材・JSONファイル・AI要約</th><th>語彙数</th><th>状態</th><th>操作</th></tr></thead><tbody id="materialRows" /></table>
    <p className="muted">AI要約の生成・更新はOpenAI APIを使用し、利用料が発生します。教材一覧を表示しただけではAPIを呼び出しません。</p></details>
    <details id="difficultyCard" className="dashboard-disclosure collapsible-section" open><summary>CEFR自動評価</summary>
      <p className="muted">未評価の語義を自動で採点します。APIキーがある場合にのみAPIを呼び、日次費用上限で停止します。</p>
      <div className="row"><label><input id="automaticDifficultyEnabled" type="checkbox" defaultChecked />自動評価を有効にする</label>
        <label>1回の件数上限 <input id="automaticDifficultyLimit" type="number" min="1" max="100" defaultValue="10" /></label>
        <label>日次費用上限 (USD) <input id="automaticDifficultyBudget" type="number" min="0.001" max="10" step="0.001" defaultValue="0.05" /></label>
        <button id="saveAutomaticDifficulty">自動設定を保存</button></div>
      <p id="automaticDifficultyStatus" aria-live="polite" />
      <button id="pauseAutomaticDifficulty" disabled>自動評価を一時停止</button><button id="resumeAutomaticDifficulty" disabled>自動評価を再開</button>
      <h3>手動の一括評価</h3><p id="difficultyEstimate" />
      <button id="planDifficulty">対象と概算を確認</button><button id="startDifficulty" disabled>評価を開始</button><button id="pauseDifficulty" disabled>一時停止</button><button id="resumeDifficulty" disabled>再開</button><p id="difficultyJobStatus" aria-live="polite" /></details>
  </section>;
}

function AddPage() {
  return <details className="card collapsible-section" id="importCard" open><summary><h2>語彙追加</h2></summary><p>英文または「英語 | 日本語の意味 | 品詞」のリストから候補を作成します。</p>
    <div className="row"><label>保存済み教材 <select id="practiceDataSource"><option value="">保存済み教材を読み込み中…</option></select></label><button id="previewPracticeVocabulary" disabled>語彙をプレビュー</button></div>
    <p id="practiceImportStatus" className="muted" aria-live="polite" />
    <progress id="practiceVocabularyProgress" max="100" value="0" hidden aria-label="類似度確認の進捗" /><p id="practiceVocabularyProgressText" aria-live="polite" hidden />
    <textarea id="candidateSource" placeholder="A comprehensive guide helps new employees." />
    <div className="row"><label>類似度閾値（以下を追加）<input id="similarityThreshold" type="number" min="0" max="1" step="0.01" defaultValue="0.80" /></label><button id="extractCandidates">候補を作る</button><button id="registerCandidates" disabled>選択した候補を登録</button></div>
    <div id="candidateRows" /><h3>類似判定用インデックス</h3><p id="embeddingEstimate">索引状況を読み込み中…</p><button id="indexEmbeddings">&#x672A;&#x4F5C;&#x6210;&#x5206;&#x3092;&#x3059;&#x3079;&#x3066;&#x7D22;&#x5F15;&#x5316;</button><progress id="embeddingProgress" max="100" value="0" hidden aria-label="&#x985E;&#x4F3C;&#x5224;&#x5B9A;&#x7528;&#x30A4;&#x30F3;&#x30C7;&#x30C3;&#x30AF;&#x30B9;&#x306E;&#x9032;&#x6357;" /><p id="embeddingProgressText" aria-live="polite" hidden />
  </details>;
}

function DatabasePage() {
  type Backup = { name: string; size_bytes: number; modified_at_utc: string };
  type DbStatus = { exists: boolean; path: string; schema_version: number; size_bytes: number; integrity: string; latest_backup: Backup | null };
  const [db, setDb] = useState<DbStatus | null>(null);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [selectedBackup, setSelectedBackup] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('状態を確認しています…');
  const refresh = async () => {
    const [statusResponse, backupResponse] = await Promise.all([fetch('/api/database/status'), fetch('/api/database/backups')]);
    if (!statusResponse.ok || !backupResponse.ok) throw new Error('データベース状態を取得できませんでした。');
    const statusData = await statusResponse.json() as DbStatus;
    const backupData = await backupResponse.json() as { items: Backup[] };
    setDb(statusData); setBackups(backupData.items); setSelectedBackup(current => current || backupData.items[0]?.name || '');
    setMessage(statusData.integrity === 'ok' ? 'データベースは正常です。' : `確認が必要です: ${statusData.integrity}`);
  };
  useEffect(() => { void refresh().catch(error => setMessage(String(error))); }, []);
  const createBackup = async () => {
    setBusy(true);
    try { const response = await fetch('/api/database/backup',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}); const body=await response.json() as {error?:string;created?:string}; if(!response.ok)throw new Error(body.error||'バックアップに失敗しました。'); setSelectedBackup(body.created||''); await refresh(); setMessage(`バックアップを作成しました: ${body.created}`); }
    catch(error){setMessage(String(error));} finally{setBusy(false);}
  };
  const restore = async () => {
    if (!selectedBackup || !window.confirm(`「${selectedBackup}」から復元します。現在のデータベースは安全バックアップとして保存されます。続けますか？`)) return;
    setBusy(true);
    try { const response=await fetch('/api/database/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({backup_name:selectedBackup})}); const body=await response.json() as {error?:string;restored?:string;safety_backup?:string}; if(!response.ok)throw new Error(body.error||'復元に失敗しました。'); await refresh(); setMessage(`復元しました: ${body.restored}。復元前の安全バックアップ: ${body.safety_backup||'作成済み'}`); }
    catch(error){setMessage(String(error));} finally{setBusy(false);}
  };
  return <details className="card collapsible-section" open><summary><h2>データベース管理</h2></summary>
    <p className="muted">復元前に選択内容を確認します。復元前のデータも安全バックアップとして残ります。</p>
    <dl className="db-facts"><dt>保存先</dt><dd>{db?.path ?? '読み込み中…'}</dd><dt>スキーマ版</dt><dd>{db?.schema_version ?? '—'}</dd><dt>データサイズ</dt><dd>{db ? `${(db.size_bytes / 1024 / 1024).toFixed(2)} MB` : '—'}</dd><dt>整合性</dt><dd>{db?.integrity ?? '—'}</dd><dt>最新バックアップ</dt><dd>{db?.latest_backup ? `${db.latest_backup.name} (${new Date(db.latest_backup.modified_at_utc).toLocaleString()})` : 'なし'}</dd></dl>
    <div className="row"><button onClick={() => void createBackup()} disabled={busy || !db?.exists}>バックアップを作成</button><button onClick={() => void refresh()} disabled={busy}>状態を更新</button></div>
    <h3>バックアップから復元</h3><div className="row"><label>バックアップ<select aria-label="復元するバックアップ" value={selectedBackup} onChange={event=>setSelectedBackup(event.currentTarget.value)}><option value="">選択してください</option>{backups.map(item=><option key={item.name} value={item.name}>{item.name} — {(item.size_bytes/1024/1024).toFixed(2)} MB</option>)}</select></label><button onClick={()=>void restore()} disabled={busy||!selectedBackup}>確認して復元</button></div>
    <p id="databaseStatus" aria-live="polite">{message}</p>
  </details>;
}

const initialTab = (window.location.hash.replace('#', '') as PageId) || 'overlap';

export function App() {
  const [selected, setSelected] = useState<PageId>(['overlap','practice','manage','add','database','dashboard'].includes(initialTab) ? initialTab : 'overlap');
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const dirtyRef = useRef(false);
  const tabs: Tab[] = [
    { id: 'overlap', label: 'オーバーラッピング', content: <OverlapPage /> },
    { id: 'practice', label: '語彙練習', content: <PracticePage /> },
    { id: 'manage', label: '語彙管理（閲覧・編集）', content: <ManagePage /> },
    { id: 'add', label: '語彙追加', content: <AddPage /> },
    { id: 'database', label: 'データベース管理', content: <DatabasePage /> },
  ];

  useEffect(() => {
    const markEdited = (event: Event) => {
      if ((event.target as HTMLElement | null)?.matches('textarea')) dirtyRef.current = true;
    };
    const warnBeforeLeave = (event: BeforeUnloadEvent) => {
      if (!dirtyRef.current) return;
      event.preventDefault();
      event.returnValue = '';
    };
    document.addEventListener('input', markEdited);
    window.addEventListener('beforeunload', warnBeforeLeave);
    const onHashChange = () => {
      const requested = window.location.hash.slice(1) as TabId;
      if (['overlap','practice','manage','add','database','dashboard'].includes(requested)) setSelected(requested);
    };
    window.addEventListener('hashchange', onHashChange);
    const openOverlap = () => { setSelected('overlap'); window.location.hash = 'overlap'; };
    window.addEventListener('english-overlap-open', openOverlap);
    const apiConfig = fetch('/app-config').then(response => response.json() as Promise<{default_text?: string; speech_styles?: Record<string, {label: string; note: string}>}>).then(config => {
      const source = document.getElementById('overlapSource') as HTMLTextAreaElement | null;
      if (source && config.default_text) source.value = config.default_text;
      const style = document.getElementById('style') as HTMLSelectElement | null;
      if (style && config.speech_styles) {
        style.replaceChildren(...Object.entries(config.speech_styles).map(([key, value]) => new Option(`${value.label} — ${value.note}`, key)));
      }
    });
    void apiConfig.catch(() => undefined);
    setupOverlapControls();
    void loadScript('/static/statistics_distribution.js').then(() => loadScript('/static/shortcuts.js')).then(() => loadScript('/static/learning.js')).catch(error => { const status = document.getElementById('learningStatus'); if (status) status.textContent = String(error); });
    void loadScript('/static/overlap.js');
    return () => { document.removeEventListener('input', markEdited); window.removeEventListener('beforeunload', warnBeforeLeave); window.removeEventListener('hashchange', onHashChange); window.removeEventListener('english-overlap-open', openOverlap); };
  }, []);

  useEffect(() => {
    window.dispatchEvent(new CustomEvent('english-overlap-tab-change', { detail: { tabId: selected } }));
  }, [selected]);

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    tabRefs.current[next]?.focus();
    setSelected(tabs[next].id);
    window.location.hash = tabs[next].id;
  }

  return <>
    <header><h1>English Quest</h1><p>単語を覚える。英語を使う。次のレベルへ。</p></header>
    <main>
      <div className="page-actions"><button id="openDashboard" aria-current={selected === 'dashboard' ? 'page' : undefined} onClick={() => { setSelected('dashboard'); window.location.hash = 'dashboard'; }}>学習ダッシュボード</button></div>
      <nav className="tabs" role="tablist" aria-label="機能">
        {tabs.map((tab, index) => <button key={tab.id} ref={element => { tabRefs.current[index] = element; }} id={`tab-${tab.id}`} role="tab" aria-selected={selected === tab.id} aria-controls={`panel-${tab.id}`} tabIndex={selected === tab.id ? 0 : -1}
          onClick={() => { setSelected(tab.id); window.location.hash = tab.id; }} onKeyDown={event => onTabKeyDown(event, index)}>{tab.label}</button>)}
      </nav>
      {tabs.map(tab => <section key={tab.id} id={`panel-${tab.id}`} role="tabpanel" aria-labelledby={`tab-${tab.id}`} hidden={selected !== tab.id}>
        {tab.content}
      </section>)}
      <section id="dashboard-panel" aria-label="学習ダッシュボード" hidden={selected !== 'dashboard'}><DashboardPage /></section>
      <footer>既存教材の再生・語彙練習はAPIキーなしで利用できます。</footer>
    </main>
  </>;
}
