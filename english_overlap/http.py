"""HTTP handlers for the English Learning Studio."""

from .app import (
    API_KEY,
    BaseHTTPRequestHandler,
    MAX_TEXT_CHARS,
    MODEL,
    EMBEDDING_MODEL,
    TEXT_MODEL,
    TRANSCRIPTION_MODEL,
    Path,
    ROOT,
    SAVE_DIR,
    STYLE_ORDER,
    VOICES,
    api_error,
    base64,
    calculate_cost,
    calculate_text_cost,
    complete_word_timings,
    generate_study_material,
    html,
    json,
    load_speech_styles,
    parse_practice_text,
    parse_qs,
    re,
    realtime_speech,
    transcribe_audio_chunks,
    urlparse,
    wav_to_mp3
)
from .storage import (load_saved_audio, practice_data_dir, practice_data_role,
                      remove_material_artifacts, unimported_material_files, save_audio_artifact)
from .pages import read_static_asset, render_practice_page
from . import database
from .openai_api import OpenAIError, request_json, response_text
from .generation import generate_vocabulary_sentences, VocabularyCoverageError
from .embeddings import compare_candidate, compare_candidates, index_missing
from .difficulty import process_difficulty_job
import threading
import sqlite3
from datetime import datetime, timezone
from .summaries import generate_material_summary, SummaryGenerationError

SAVE_DIR = practice_data_dir()
DATA_ROLE = practice_data_role()
AUTO_DIFFICULTY_DEFAULTS = {'enabled': True, 'per_run_limit': 10, 'daily_budget_usd': 0.05}
_AUTO_DIFFICULTY_LOCK = threading.Lock()
_AUTO_DIFFICULTY_RUNNING: set[str] = set()
_SAVED_MATERIAL_SYNC_LOCK = threading.Lock()
_LEGACY_IMPORT_WARNINGS: list[dict] = []


def _sync_saved_materials() -> list[dict]:
    """Import each legacy subtitle JSON once, then use the DB as the only source."""
    global _LEGACY_IMPORT_WARNINGS
    with _SAVED_MATERIAL_SYNC_LOCK:
        imported=database.imported_material_source_names()
        items,errors=unimported_material_files(SAVE_DIR,imported)
        results=[]
        for item in items:
            try:results.append(database.import_legacy_material(item))
            except (OSError,ValueError,sqlite3.DatabaseError) as error:
                errors.append({'file':item.get('file'),'error':str(error)})
    _LEGACY_IMPORT_WARNINGS=errors
    return errors


def _material_api_item(material: dict) -> dict:
    item=dict(material)
    content=database.material_content(material)
    try:metadata=json.loads(material.get('metadata_json') or '{}')
    except (TypeError,ValueError):metadata={}
    item.update({key:value for key,value in content.items() if key not in ('title','text','audio_file')})
    item['text']=material.get('text_content') or ''
    item['audio_file']=material.get('audio_path')
    item['file']=material.get('audio_path') if _saved_audio_exists(material.get('audio_path')) else None
    item['summary']=content.get('summary','')
    item['ai_summary']=content.get('summary') if content.get('summary_model') else None
    item['created_at']=material.get('created_at_utc')
    item['file_status']='ready' if item['file'] else 'not_generated'
    item['metadata']=metadata if isinstance(metadata,dict) else {}
    return item


def _saved_material_items(query: str = '') -> list[dict]:
    """Return saved materials from SQLite, importing only previously unseen legacy files."""
    errors=_sync_saved_materials()
    needle = (query or '').strip().casefold()
    result = []
    for material in database.list_materials(query=query):
        item=_material_api_item(material)
        if needle and not any(needle in str(item.get(key) or '').casefold() for key in ('title','text_content','summary','material_id')):continue
        result.append(item)
    return result


def _saved_audio_exists(name: str | None) -> bool:
    return bool(name and Path(name).name == name and (SAVE_DIR / name).is_file())


def _overlap_material_items() -> list[dict]:
    return _saved_material_items()


def automatic_difficulty_status() -> dict:
    settings={**AUTO_DIFFICULTY_DEFAULTS,**(database.get_setting('automatic_difficulty',{}) or {})}
    return {'settings':settings,'api_key_configured':bool(API_KEY),
            'pending_senses':database.count_pending_difficulty(),
            'spent_today_usd':database.api_usage_spent_today('difficulty_assessment'),
            'job':database.latest_api_job('automatic_difficulty_assessment')}


def _run_automatic_difficulty(job_id: str) -> None:
    try:
        process_difficulty_job(job_id,api_key=API_KEY)
    except Exception as ex:
        database.update_api_job(job_id,status='failed',error=api_error(ex))
    finally:
        with _AUTO_DIFFICULTY_LOCK:
            _AUTO_DIFFICULTY_RUNNING.discard(job_id)
    current=database.get_api_job(job_id)
    if current and current['status']=='completed':
        schedule_automatic_difficulty()


def schedule_automatic_difficulty() -> str | None:
    settings={**AUTO_DIFFICULTY_DEFAULTS,**(database.get_setting('automatic_difficulty',{}) or {})}
    if not settings.get('enabled',True):
        return None
    with _AUTO_DIFFICULTY_LOCK:
        job=database.latest_api_job('automatic_difficulty_assessment')
        if job and job['status'] in ('queued','running','paused'):
            if not API_KEY:
                if job['status']=='running':database.update_api_job(job['job_id'],status='queued',error='waiting_for_api_key')
                return job['job_id']
            if job['status']=='queued':database.update_api_job(job['job_id'],status='running',error=None)
            if job['status']=='paused':
                reason=(job.get('result') or {}).get('pause_reason')
                if reason=='disabled':
                    database.update_api_job(job['job_id'],status='running',error=None)
                elif reason=='daily_budget':
                    spent=database.api_usage_spent_today('difficulty_assessment')
                    if spent>=float(settings['daily_budget_usd']):return job['job_id']
                    database.update_api_job(job['job_id'],status='running',error=None)
                else:return job['job_id']
            if job['job_id'] not in _AUTO_DIFFICULTY_RUNNING:
                _AUTO_DIFFICULTY_RUNNING.add(job['job_id'])
                threading.Thread(target=_run_automatic_difficulty,args=(job['job_id'],),daemon=True).start()
            return job['job_id']
        if job and job['status']=='failed':
            return job['job_id']
        items=database.senses_for_difficulty(limit=int(settings['per_run_limit']))
        if not items:return None
        ids=[item['sense_id'] for item in items]
        job_id=database.create_api_job('automatic_difficulty_assessment',{
            'automatic':True,'sense_ids':ids,'per_run_limit':int(settings['per_run_limit']),
            'daily_budget_usd':float(settings['daily_budget_usd'])},len(ids),TEXT_MODEL)
        database.update_api_job(job_id,status='running')
        if not API_KEY:
            database.update_api_job(job_id,status='queued',error='waiting_for_api_key')
            return job_id
        _AUTO_DIFFICULTY_RUNNING.add(job_id)
        threading.Thread(target=_run_automatic_difficulty,args=(job_id,),daemon=True).start()
        return job_id


def process_study_set_job(job_id: str, api_key: str, *, provider=None) -> dict:
    """Generate each bounded vocabulary passage in the background and checkpoint it."""
    job=database.get_api_job(job_id)
    if not job or job['job_type']!='study_set_generation':raise LookupError('Study set job not found')
    payload=job['payload'];previous=job.get('result') or {}
    all_ids=list(dict.fromkeys(payload.get('vocab_ids',[])))
    already=set(previous.get('used_vocab_ids',[]))
    by_id={item['vocab_id']:item for item in database.vocabulary_by_ids(all_ids)}
    remaining=[by_id[value] for value in all_ids if value in by_id and value not in already]
    previous_usage=previous.get('usage') or {'input_tokens':0,'output_tokens':0}
    last_new_usage={'input_tokens':0,'output_tokens':0}
    def progress(update):
        nonlocal last_new_usage
        usage=update.get('usage') or {}
        delta_in=max(0,int(usage.get('input_tokens',0))-int(last_new_usage['input_tokens']))
        delta_out=max(0,int(usage.get('output_tokens',0))-int(last_new_usage['output_tokens']))
        if delta_in or delta_out:
            price=calculate_text_cost({'input_tokens':delta_in,'output_tokens':delta_out})
            database.add_api_usage(operation='study_set_generation',model=update.get('model',TEXT_MODEL),input_tokens=delta_in,output_tokens=delta_out,estimated_usd=price['usd'],job_id=job_id,rate_version=price['rate_version'])
        last_new_usage={'input_tokens':int(usage.get('input_tokens',0)),'output_tokens':int(usage.get('output_tokens',0))}
        merged={**previous,'groups':previous.get('groups',[])+update['groups'],'sentences':previous.get('sentences',[])+update['sentences'],'usages':previous.get('usages',[])+update['usages'],'used_vocab_ids':sorted(already|set(update['used_vocab_ids'])),'usage':{'input_tokens':int(previous_usage.get('input_tokens',0))+int(usage.get('input_tokens',0)),'output_tokens':int(previous_usage.get('output_tokens',0))+int(usage.get('output_tokens',0))},'request_count':int(previous.get('request_count',0))+int(update['request_count']),'model':update.get('model',TEXT_MODEL),'generation_mode':payload.get('generation_mode','per_vocabulary')}
        database.update_api_job(job_id,status='running',completed_items=len(merged['used_vocab_ids']),result=merged)
    try:
        generated=generate_vocabulary_sentences(remaining,difficulty=payload.get('difficulty',''),theme=payload.get('theme',''),length=payload.get('length','short'),generation_mode=payload.get('generation_mode','per_vocabulary'),provider=provider,api_key=api_key,on_progress=progress) if remaining else {'groups':[],'sentences':[],'usages':[],'used_vocab_ids':[],'usage':{'input_tokens':0,'output_tokens':0},'request_count':0,'model':TEXT_MODEL}
        merged=database.get_api_job(job_id)['result'] or previous
        missing=[item for item in all_ids if item not in set(merged.get('used_vocab_ids',[]))]
        if missing:raise ValueError('未使用語彙を含むジョブは完了できません。')
        cost=calculate_text_cost(merged.get('usage'))
        merged.update({'text':'\n\n'.join('\n'.join(group) for group in merged.get('groups',[])),'unused_vocab_ids':[],'cost':cost})
        database.update_api_job(job_id,status='completed',completed_items=len(all_ids),result=merged)
    except VocabularyCoverageError as ex:
        delta_in=max(0,int(ex.usage.get('input_tokens',0))-int(last_new_usage['input_tokens']))
        delta_out=max(0,int(ex.usage.get('output_tokens',0))-int(last_new_usage['output_tokens']))
        if delta_in or delta_out:
            price=calculate_text_cost({'input_tokens':delta_in,'output_tokens':delta_out})
            database.add_api_usage(operation='study_set_generation',model=ex.model,input_tokens=delta_in,output_tokens=delta_out,estimated_usd=price['usd'],job_id=job_id,rate_version=price['rate_version'])
        state=database.get_api_job(job_id)['result'] or previous
        state['missing_targets']=ex.missing;state['request_count']=int(previous.get('request_count',0))+ex.request_count
        database.update_api_job(job_id,status='failed',error=api_error(ex),result=state)
    except Exception as ex:
        database.update_api_job(job_id,status='failed',error=api_error(ex))
    return database.get_api_job(job_id)

class Handler(BaseHTTPRequestHandler):
    def send(self,code, payload, content_type='application/json; charset=utf-8'):
        if isinstance(payload,(dict,list)): payload=json.dumps(payload,ensure_ascii=False).encode('utf-8')
        elif isinstance(payload, str): payload=payload.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(payload)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers(); self.wfile.write(payload)
    def send_stream_event(self, event):
        if not getattr(self,'_generation_stream_started',False):
            self.send_response(200)
            self.send_header('Content-Type','application/x-ndjson; charset=utf-8')
            self.send_header('Cache-Control','no-store, no-transform')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Connection','close')
            self.end_headers()
            self._generation_stream_started=True
        self.wfile.write((json.dumps(event,ensure_ascii=False)+'\n').encode('utf-8'))
        self.wfile.flush()
    def do_GET(self):
        route = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        if route == '/api/vocabulary':
            try:
                if 'page' in query or 'page_size' in query or 'sort_by' in query:
                    result=database.list_vocabulary_page(query=query.get('q',[''])[0],direction=query.get('direction',['en_to_ja'])[0],include_archived=query.get('include_archived',['0'])[0]=='1',page=int(query.get('page',['1'])[0]),page_size=int(query.get('page_size',['50'])[0]),sort_by=query.get('sort_by',['english'])[0],sort_direction=query.get('sort_direction',['asc'])[0])
                    return self.send(200,{**result,'categories':database.vocabulary_categories()})
                items = database.list_vocabulary(query=query.get('q', [''])[0], category=query.get('category', [None])[0], direction=query.get('direction', ['en_to_ja'])[0], limit=int(query.get('limit', ['100'])[0]), include_archived=query.get('include_archived',['0'])[0]=='1')
                return self.send(200, {'items': items, 'categories': database.vocabulary_categories()})
            except (ValueError, TypeError) as ex:
                return self.send(400, {'error': str(ex)})
        if route == '/api/next-question':
            try:
                raw_count=query.get('count',['50'])[0]
                if not raw_count.isdigit() or not 1 <= int(raw_count) <= 1000:return self.send(400,{'error':'count must be 1..1000'})
                raw_n=query.get('recent_attempts',[''])[0]
                raw_accuracy=query.get('max_recent_accuracy',[''])[0]
                items = database.list_practice_questions(query.get('direction', ['en_to_ja'])[0], category=query.get('category', [None])[0], include_unstudied=query.get('include_unstudied',['true'])[0]=='true', mastery_status=query.get('mastery_status',['all'])[0], difficulty=query.get('difficulty',[None])[0], recent_attempts=int(raw_n) if raw_n else None, max_recent_accuracy=float(raw_accuracy) if raw_accuracy else None, include_insufficient_history=query.get('include_insufficient_history',['false'])[0]=='true', all_attempts_incorrect=query.get('all_attempts_incorrect',['false'])[0]=='true', last_attempt_incorrect=query.get('last_attempt_incorrect',['false'])[0]=='true', due_only=query.get('due_only',['false'])[0]=='true', limit=int(raw_count))
                return self.send(200, {'item': items[0] if items else None, 'items': items, 'total': len(items)})
            except (ValueError,TypeError) as ex:
                return self.send(400, {'error': str(ex)})
        if route == '/api/statistics':
            try:
                raw_days=parse_qs(urlparse(self.path).query).get('days',['all'])[0]
                days=None if raw_days in ('','all') else max(1,min(3650,int(raw_days)))
                return self.send(200, database.review_and_statistics(days=days))
            except (TypeError,ValueError):
                return self.send(400,{'error':'days must be 1..3650 or all'})
        if route == '/api/learning-goals':
            return self.send(200, database.learning_goals_status())
        if route == '/api/database/status':
            return self.send(200, database.database_status())
        if route == '/api/database/backups':
            return self.send(200, {'items':database.list_database_backups()})
        if route == '/api/difficulty/auto/status':
            return self.send(200,automatic_difficulty_status())
        if route == '/api/settings/keys':
            return self.send(200, {'bindings': database.get_setting('key_bindings')})
        if route == '/api/vocabulary/export':
            rows = database.list_vocabulary(limit=5000,include_archived=True)
            lines = ['vocab_id,english,meaning,part_of_speech,tags,sources']
            for item in rows:
                values = [item.get(key) or '' for key in ('vocab_id','english','meaning','part_of_speech','tags','sources')]
                lines.append(','.join('"' + str(value).replace('"','""') + '"' for value in values))
            return self.send(200, '\ufeff' + '\r\n'.join(lines), 'text/csv; charset=utf-8')
        if route == '/api/materials':
            items=_saved_material_items(query.get('q',[''])[0])
            return self.send(200, {'items':items,'legacy_import_warnings':_LEGACY_IMPORT_WARNINGS})
        if route == '/api/materials/overlap-list':
            items = _overlap_material_items()
            return self.send(200, {'items':items, 'count':len(items),'legacy_import_warnings':_LEGACY_IMPORT_WARNINGS})
        if route == '/api/study-set/last':
            return self.send(200,{'conditions':database.get_setting('last_study_set_conditions',{}) or {}})
        if route == '/api/materials/export':
            rows=database.list_materials(query=query.get('q',[''])[0])
            lines=['material_id,title,status,source,difficulty_level,text_content,metadata_json,content_json,audio_path']
            for item in rows:
                values=[item.get(key) or '' for key in ('material_id','title','status','source','difficulty_level','text_content','metadata_json','content_json','audio_path')]
                lines.append(','.join('"'+str(value).replace('"','""')+'"' for value in values))
            return self.send(200,'\ufeff'+'\r\n'.join(lines),'text/csv; charset=utf-8')
        if route == '/api/jobs':
            job=database.get_api_job(query.get('id',[''])[0])
            return self.send(200,job) if job else self.send(404,{'error':'Job not found'})
        if route == '/api/candidates':
            batch_id=query.get('batch_id',[''])[0]
            return self.send(200, {'items':database.list_candidates(batch_id)}) if batch_id else self.send(400,{'error':'batch_id is required'})
        if route == '/api/embeddings/plan':
            model=EMBEDDING_MODEL
            with database.connect() as conn:
                count=conn.execute("""SELECT count(*) FROM vocab v JOIN senses s ON s.vocab_id=v.vocab_id WHERE trim(s.meaning)<>'' AND NOT EXISTS(
                    SELECT 1 FROM embeddings e WHERE e.vocab_id=v.vocab_id AND e.sense_id=s.sense_id AND e.model=? AND e.input_version='english-meaning-v1')""",(model,)).fetchone()[0]
            return self.send(200,{'model':model,'missing_count':count,'estimated_input_tokens':count*12,'estimated_usd':count*12*.02/1_000_000,'batch_size':100,'note':'概算は1語義あたり12 tokenで計算。100件ごとにインデックスを作成します。'})
        if urlparse(self.path).path.startswith('/static/'):
            asset = read_static_asset(urlparse(self.path).path.removeprefix('/static/'),root=ROOT/'english_overlap'/'static')
            if asset is None:
                return self.send(404, {'error': 'Not found'})
            payload, content_type = asset
            return self.send(200, payload, content_type)
        if self.path in ('/', '/index.html'):
            page = render_practice_page(ROOT, MAX_TEXT_CHARS)
            return self.send(200, page.encode('utf-8'), 'text/html; charset=utf-8')
        elif self.path=='/health':
            self.send(200,{'ready':bool(API_KEY)})
        elif self.path=='/api/storage/status':
            self.send(200,{'role':DATA_ROLE,'directory':str(SAVE_DIR.resolve())})
        elif self.path=='/app-config':
            styles=load_speech_styles()
            default_text='I thought we were ready, but the plan changed at the last minute. Honestly, I was not expecting it to work this well—and now I am wondering what we should try next. If you can give me a little more time, I will walk you through it.'
            try:
                configured=json.loads((ROOT/'config.json').read_text(encoding='utf-8-sig')).get('DEFAULT_TEXT')
                if isinstance(configured,str) and configured.strip(): default_text=configured.strip()
            except (OSError,ValueError):
                pass
            self.send(200,{'speech_styles':{key:{'label':styles[key].get('label',key),'note':styles[key].get('note','')} for key in STYLE_ORDER if key in styles},'default_text':default_text})
        elif self.path=='/saved':
            items=_saved_material_items()
            self.send(200,items)
        elif urlparse(self.path).path in ('/saved-data','/saved-audio'):
            query=parse_qs(urlparse(self.path).query)
            if urlparse(self.path).path=='/saved-data':
                _sync_saved_materials()
                material_id=query.get('material_id',[''])[0]
                name=query.get('name',[''])[0]
                if not material_id and name and Path(name).name==name and name.startswith('english_overlap_'):
                    legacy=database.material_for_legacy_source(name)
                    material_id=legacy.get('material_id') if legacy else ''
                if not material_id:return self.send(400,{'error':'material_id is required'})
                material=database.get_material(material_id)
                if not material:return self.send(404,{'error':'Saved material not found'})
                try:
                    data=database.material_content(material)
                    data.update({'material_id':material_id,'title':material['title'],'text':material['text_content'],'audio_file':material.get('audio_path'),'created_at':material.get('created_at_utc')})
                    spoken_text=data.get('spoken_text') or data.get('text','')
                    source_count=len(re.findall(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*",spoken_text))
                    if data.get('audio_seconds') and len(data.get('words',[]))<source_count:
                        data['words']=complete_word_timings(spoken_text,data.get('words',[]),float(data['audio_seconds']))
                    return self.send(200,data)
                except (ValueError,TypeError):
                    return self.send(500,{'error':'Saved material content is invalid'})
            name=query.get('name',[''])[0]
            if not name or Path(name).name!=name or not name.startswith('english_overlap_'):
                return self.send(400,{'error':'Invalid saved audio filename'})
            path=SAVE_DIR/name
            if not path.is_file():return self.send(404,{'error':'Saved audio file not found'})
            if urlparse(self.path).path=='/saved-audio' and path.suffix in ('.mp3','.wav'):
                payload, content_type=load_saved_audio(SAVE_DIR,name)
                return self.send(200,payload,content_type)
            self.send(404,{'error':'Unsupported saved file'})
        else:self.send(404,{'error':'Not found'})
    def do_POST(self):
        route = urlparse(self.path).path
        api_job_id=None
        if route.startswith('/api/'):
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length > 100000:
                    return self.send(413, {'error': 'Request is too large'})
                req = json.loads(self.rfile.read(length) or b'{}')
                if route == '/api/learning-goals':
                    if not isinstance(req, dict) or 'overlap_hours' not in req or 'vocabulary_count' not in req:
                        return self.send(400, {'error': '両方の目標欄を確認してください。'})
                    try:
                        database.set_learning_goals(overlap_hours=req['overlap_hours'], vocabulary_count=req['vocabulary_count'])
                    except ValueError as ex:
                        return self.send(400, {'error': str(ex)})
                    return self.send(200, {'saved': True, **database.learning_goals_status()})
                if route == '/api/answer':
                    saved = database.vocabulary_answer(req['vocab_id'], int(req['sense_id']), req['direction'], req['rating'], float(req.get('duration_seconds', 0)), req['idempotency_key'])
                    return self.send(200, {'saved': saved})
                if route == '/api/settings/keys':
                    database.set_setting('key_bindings', req['bindings'])
                    return self.send(200, {'saved': True})
                if route == '/api/database/backup':
                    backup=database.backup_database(database.database_path())
                    return self.send(201,{'created':backup.name,'backups':database.list_database_backups()})
                if route == '/api/database/restore':
                    name=str(req.get('backup_name',''))
                    db_path=database.database_path().resolve()
                    if not name or Path(name).name!=name or not name.startswith(db_path.stem+'.backup-') or not name.endswith('.sqlite3'):
                        return self.send(400,{'error':'バックアップを選択してください。'})
                    backup=(db_path.parent/name).resolve()
                    if backup.parent!=db_path.parent.resolve() or not backup.is_file():
                        return self.send(404,{'error':'指定したバックアップが見つかりません。'})
                    try:
                        before=set(item['name'] for item in database.list_database_backups(db_path))
                        database.restore_database(backup,db_path)
                        version,migration_backup=database.migrate_database(db_path)
                    except (ValueError,OSError,sqlite3.DatabaseError) as ex:
                        return self.send(400,{'error':str(ex)})
                    after=database.list_database_backups(db_path)
                    safety=next((item['name'] for item in after if item['name'] not in before),migration_backup.name if migration_backup else None)
                    return self.send(200,{'restored':name,'safety_backup':safety,'schema_version':version,'status':database.database_status(db_path)})
                if route == '/api/vocabulary/update':
                    database.update_vocabulary(vocab_id=req['vocab_id'], english=req['english'], meaning=req['meaning'], part_of_speech=req.get('part_of_speech', ''), tags=req.get('tags', ''), sources=req.get('sources', ''))
                    return self.send(200, {'saved': True})
                if route == '/api/vocabulary/archive':
                    database.set_vocabulary_archived(req['vocab_id'], bool(req.get('archived', True)))
                    return self.send(200, {'saved': True})
                if route == '/api/overlap/activity':
                    saved = database.record_overlap_activity(session_id=req['session_id'], material_id=req['material_id'], duration_seconds=float(req['duration_seconds']), idempotency_key=req['idempotency_key'])
                    return self.send(200, {'saved': saved})
                if route == '/api/overlap/session':
                    return self.send(200, {'session_id':database.create_study_session('overlap')})
                if route == '/api/candidates/create':
                    source=str(req.get('source','')).strip()
                    source_type=req.get('source_type','vocabulary_list')
                    if not source:return self.send(400,{'error':'英文または語彙リストを入力してください。'})
                    batch_id=database.create_import_batch(source_type,source)
                    if source_type=='vocabulary_list':
                        candidates=[]
                        for line in source.splitlines():
                            parts=[part.strip() for part in re.split(r'\s*[|｜\t]\s*',line) if part.strip()]
                            if parts:candidates.append({'english':parts[0],'meaning':parts[1] if len(parts)>1 else '', 'part_of_speech':parts[2] if len(parts)>2 else '', 'source':'user list'})
                    elif source_type=='english_text':
                        prompt={'model':TEXT_MODEL,'instructions':'Extract useful English vocabulary from the supplied English passage. Return a JSON object with candidates, each having the exact English headword or phrase, a concise Japanese meaning, and part of speech. The English headword must be in the passage.','input':source,'text':{'format':{'type':'json_schema','name':'vocabulary_candidates','strict':True,'schema':{'type':'object','additionalProperties':False,'properties':{'candidates':{'type':'array','items':{'type':'object','additionalProperties':False,'properties':{'english':{'type':'string'},'meaning':{'type':'string'},'part_of_speech':{'type':'string'}},'required':['english','meaning','part_of_speech']}}},'required':['candidates']}}}}
                        job=database.create_api_job('candidate_extraction',{'batch_id':batch_id,'source_type':source_type},1,TEXT_MODEL)
                        database.update_api_job(job,status='running')
                        try:
                            result=request_json('responses',prompt,api_key=API_KEY)
                            candidates=json.loads(response_text(result)).get('candidates',[])
                            usage=result.get('usage',{})
                            cost=calculate_text_cost({'input_tokens':usage.get('input_tokens',0),'output_tokens':usage.get('output_tokens',0)})
                            database.add_api_usage(operation='candidate_extraction',model=result.get('model',TEXT_MODEL),input_tokens=cost['input_tokens'],output_tokens=cost['output_tokens'],estimated_usd=cost['usd'],job_id=job,rate_version=cost['rate_version'])
                            database.update_api_job(job,status='completed',completed_items=1,result={'batch_id':batch_id,'candidate_count':len(candidates),'usage':usage,'cost':cost})
                        except Exception as ex:
                            database.update_api_job(job,status='failed',error=api_error(ex))
                            raise
                    else:return self.send(400,{'error':'source_type is invalid'})
                    ids=database.add_candidates(batch_id,candidates)
                    return self.send(200,{'batch_id':batch_id,'candidate_ids':ids,'items':database.list_candidates(batch_id)})
                if route == '/api/candidates/select':
                    created=database.select_candidates(req['batch_id'],req.get('candidate_ids',[]))
                    job_id=schedule_automatic_difficulty() if created else None
                    return self.send(200,{'created_vocab_ids':created,'automatic_difficulty_job_id':job_id})
                if route == '/api/candidates/compare-batch':
                    batch_id=req.get('batch_id')
                    candidate_ids=req.get('candidate_ids')
                    if not isinstance(candidate_ids,list) or not candidate_ids:return self.send(400,{'error':'candidate_ids must be a non-empty list'})
                    candidate_ids=list(dict.fromkeys(str(value) for value in candidate_ids))
                    if len(candidate_ids)>100:return self.send(400,{'error':'A similarity batch is limited to 100 candidates'})
                    try:threshold=float(req.get('threshold',.8))
                    except (TypeError,ValueError):return self.send(400,{'error':'threshold must be between 0 and 1'})
                    if not 0<=threshold<=1:return self.send(400,{'error':'threshold must be between 0 and 1'})
                    try:candidates=database.list_candidates(batch_id)
                    except sqlite3.OperationalError as ex:
                        self.log_error(f'Candidate similarity lookup could not access SQLite: {ex}')
                        return self.send(503,{'error':'Database is busy. Wait briefly and retry the vocabulary preview.'})
                    by_id={item['candidate_id']:item for item in candidates}
                    if any(candidate_id not in by_id for candidate_id in candidate_ids):return self.send(404,{'error':'Candidate not found in this batch'})
                    selected=[by_id[candidate_id] for candidate_id in candidate_ids]
                    try:
                        job=database.create_api_job('candidate_similarity',{'batch_id':batch_id,'candidate_ids':candidate_ids,'threshold':threshold},len(selected),EMBEDDING_MODEL)
                        database.update_api_job(job,status='running')
                    except sqlite3.OperationalError as ex:
                        self.log_error(f'Candidate similarity job could not access SQLite: {ex}')
                        return self.send(503,{'error':'Database is busy. Wait briefly and retry the vocabulary preview.'})
                    try:
                        comparison=compare_candidates(selected,api_key=API_KEY,threshold=threshold)
                        assessments=comparison['items'];usage=comparison.get('usage') or {}
                        input_tokens=int(usage.get('prompt_tokens') or usage.get('total_tokens') or 0)
                        embedding_rate=float(__import__('os').environ.get('OPENAI_EMBEDDING_USD_PER_MILLION','0.02'))
                        safe_items=[{key:value for key,value in item.items() if key not in ('candidate_embedding','usage')} for item in assessments]
                        job_result={'items':safe_items,'model':comparison.get('model'),'usage':usage,
                            'exact_comparisons':comparison.get('exact_comparisons',0),'dataset_size':comparison.get('dataset_size',0)}
                        database.complete_candidate_similarity_job(job,assessments,model=comparison.get('model') or EMBEDDING_MODEL,
                            input_tokens=input_tokens,estimated_usd=input_tokens*embedding_rate/1_000_000,
                            rate_version=__import__('os').environ.get('OPENAI_PRICE_RATE_VERSION','2026-10-24-v1'),
                            result=job_result,record_usage=any(item.get('candidate_embedding') is not None for item in assessments))
                        return self.send(200,{'job_id':job,'items':safe_items,'model':comparison.get('model'),
                            'exact_comparisons':comparison.get('exact_comparisons',0),'dataset_size':comparison.get('dataset_size',0)})
                    except Exception as ex:
                        try:database.update_api_job(job,status='failed',error=api_error(ex))
                        except sqlite3.OperationalError as db_error:self.log_error(f'Could not persist candidate similarity failure: {db_error}')
                        code=503 if isinstance(ex,sqlite3.OperationalError) else 502
                        message='Database is busy. Wait briefly and retry the vocabulary preview.' if code==503 else api_error(ex)
                        return self.send(code,{'error':message,'job_id':job})
                if route == '/api/candidates/compare':
                    candidates=database.list_candidates(req['batch_id'])
                    candidate=next((item for item in candidates if item['candidate_id']==req['candidate_id']),None)
                    if candidate is None:return self.send(404,{'error':'Candidate not found'})
                    job=database.create_api_job('candidate_similarity',{'batch_id':req['batch_id'],'candidate_id':req['candidate_id'],'threshold':float(req.get('threshold',.8))},1,EMBEDDING_MODEL)
                    database.update_api_job(job,status='running')
                    try:
                        assessment=compare_candidate(candidate,api_key=API_KEY,threshold=float(req.get('threshold',.8)))
                        usage=assessment.get('usage',{})
                        input_tokens=int(usage.get('prompt_tokens') or usage.get('total_tokens') or 0)
                        embedding_rate=float(__import__('os').environ.get('OPENAI_EMBEDDING_USD_PER_MILLION','0.02'))
                        database.add_api_usage(operation='candidate_similarity',model=assessment.get('model') or EMBEDDING_MODEL,input_tokens=input_tokens,estimated_usd=input_tokens*embedding_rate/1_000_000,job_id=job,rate_version=__import__('os').environ.get('OPENAI_PRICE_RATE_VERSION','2026-10-24-v1'))
                        database.update_api_job(job,status='completed',completed_items=1,result={key:value for key,value in assessment.items() if key!='candidate_embedding'})
                    except Exception as ex:
                        database.update_api_job(job,status='failed',error=api_error(ex))
                        raise
                    database.update_candidate_assessment(candidate['candidate_id'],assessment)
                    response={key:value for key,value in assessment.items() if key not in ('candidate_embedding','usage')}
                    response['job_id']=job
                    return self.send(200,response)
                if route == '/api/embeddings/index':
                    job=database.create_api_job('embedding_index',{'limit':int(req.get('limit',100))},int(req.get('limit',100)),EMBEDDING_MODEL)
                    database.update_api_job(job,status='running')
                    try:
                        result=index_missing(api_key=API_KEY,limit=int(req.get('limit',100)))
                        usage=result.get('usage',{})
                        embedding_tokens=int(usage.get('prompt_tokens') or usage.get('total_tokens') or 0)
                        embedding_rate=float(__import__('os').environ.get('OPENAI_EMBEDDING_USD_PER_MILLION','0.02'))
                        database.add_api_usage(operation='embedding_index',model=result['model'],input_tokens=embedding_tokens,estimated_usd=embedding_tokens*embedding_rate/1_000_000,job_id=job,rate_version=__import__('os').environ.get('OPENAI_PRICE_RATE_VERSION','2026-10-24-v1'))
                        database.update_api_job(job,status='completed',completed_items=result['indexed'],result=result)
                    except VocabularyCoverageError as ex:
                        cost=calculate_text_cost(ex.usage)
                        database.add_api_usage(operation='study_set_generation',model=ex.model,input_tokens=int(ex.usage.get('input_tokens') or 0),output_tokens=int(ex.usage.get('output_tokens') or 0),estimated_usd=cost['usd'],job_id=job_id,rate_version=cost['rate_version'])
                        database.update_api_job(job_id,status='failed',error=api_error(ex),result={'missing_targets':ex.missing,'request_count':ex.request_count})
                        raise
                    except Exception as ex:
                        database.update_api_job(job,status='failed',error=api_error(ex));raise
                    return self.send(200,{'job_id':job,**result})
                if route == '/api/difficulty/manual':
                    database.update_difficulty(int(req['sense_id']),req.get('level') or None,req.get('evidence',''),manual=True)
                    return self.send(200,{'saved':True})
                if route == '/api/difficulty/auto/settings':
                    settings={'enabled':bool(req.get('enabled',True)),
                              'per_run_limit':max(1,min(100,int(req.get('per_run_limit',10)))),
                              'daily_budget_usd':max(0.001,min(10.0,float(req.get('daily_budget_usd',0.05))))}
                    database.set_setting('automatic_difficulty',settings)
                    job_id=schedule_automatic_difficulty() if settings['enabled'] else None
                    return self.send(200,{'settings':settings,'job_id':job_id,'status':automatic_difficulty_status()})
                if route == '/api/difficulty/plan':
                    items=database.senses_for_difficulty(limit=int(req.get('limit',100)))
                    estimate=len(items)*220*.10/1_000_000+len(items)*50*.50/1_000_000
                    return self.send(200,{'items':len(items),'sense_ids':[item['sense_id'] for item in items], 'model':TEXT_MODEL,'estimated_usd':estimate,'rate_version':'2026-10-24-v1'})
                if route in ('/api/difficulty/start','/api/difficulty/resume'):
                    job_id=req.get('job_id')
                    automatic_job=False
                    if route.endswith('/resume'):
                        job=database.get_api_job(job_id)
                        if not job or job['job_type'] not in ('difficulty_assessment','automatic_difficulty_assessment') or job['status'] not in ('paused','failed'):return self.send(409,{'error':'Paused or failed difficulty job not found'})
                        automatic_job=job['job_type']=='automatic_difficulty_assessment'
                        if automatic_job:
                            settings={**AUTO_DIFFICULTY_DEFAULTS,**(database.get_setting('automatic_difficulty',{}) or {})}
                            if not settings['enabled']:return self.send(409,{'error':'自動評価が停止中です。先に有効にしてください。'})
                            if database.api_usage_spent_today('difficulty_assessment')>=float(settings['daily_budget_usd']):return self.send(409,{'error':'本日の日次上限に達しています。上限を増やすか、翌日に再開してください。'})
                    else:
                        ids=[int(value) for value in req.get('sense_ids',[])][:100]
                        if not ids:return self.send(400,{'error':'No senses to assess'})
                        job_id=database.create_api_job('difficulty_assessment',{'sense_ids':ids},len(ids),TEXT_MODEL)
                    database.update_api_job(job_id,status='running')
                    if automatic_job:
                        with _AUTO_DIFFICULTY_LOCK:
                            if job_id in _AUTO_DIFFICULTY_RUNNING:return self.send(409,{'error':'Difficulty job is already running'})
                            _AUTO_DIFFICULTY_RUNNING.add(job_id)
                        threading.Thread(target=_run_automatic_difficulty,args=(job_id,),daemon=True).start()
                    else:
                        threading.Thread(target=process_difficulty_job,args=(job_id,),kwargs={'api_key':API_KEY},daemon=True).start()
                    return self.send(202,{'job_id':job_id})
                if route == '/api/jobs/pause':
                    job=database.get_api_job(req.get('job_id',''))
                    if not job or job['job_type'] not in ('difficulty_assessment','automatic_difficulty_assessment') or job['status']!='running':return self.send(409,{'error':'Running difficulty job not found'})
                    database.update_api_job(job['job_id'],status='paused')
                    return self.send(200,{'saved':True})
                if route == '/api/materials/create':
                    material_id=database.create_material(title=req['title'],text_content=req['text_content'],source=req.get('source',''),difficulty_level=req.get('difficulty_level'),metadata=req.get('metadata',{}))
                    database.attach_material_vocabulary(material_id,req.get('usages',[]))
                    return self.send(200,{'material_id':material_id})
                if route == '/api/materials/summarize':
                    material_id=str(req.get('material_id','')).strip()
                    material=database.get_material(material_id)
                    if material is None:return self.send(404,{'error':'保存済み教材が見つかりません。'})
                    json_text=str(material.get('text_content') or '').strip()
                    if not json_text:return self.send(400,{'error':'教材に要約対象の本文がありません。'})
                    if not API_KEY:return self.send(400,{'error':'AI要約にはOpenAI APIキーが必要です。サーバーのAPIキー設定を確認してください。'})
                    job_id=database.create_api_job('material_summary_generation',{'material_id':material_id},1,TEXT_MODEL)
                    database.update_api_job(job_id,status='running')
                    usage_recorded=False
                    try:
                        generated=generate_material_summary({'title':material['title'],'text_content':json_text},api_key=API_KEY)
                        usage=generated.get('usage') or {}
                        price=calculate_text_cost({'input_tokens':usage.get('input_tokens',0),'output_tokens':usage.get('output_tokens',0)})
                        database.add_api_usage(operation='material_summary_generation',model=generated['model'],input_tokens=price['input_tokens'],output_tokens=price['output_tokens'],estimated_usd=price['usd'],job_id=job_id,rate_version=price['rate_version'])
                        usage_recorded=True
                        generated_at=datetime.now(timezone.utc).isoformat(timespec='seconds')
                        database.update_material_summary(material_id,generated['title'],generated['summary'],
                            model=generated['model'],prompt_version=generated['prompt_version'],generated_at_utc=generated_at)
                        database.update_api_job(job_id,status='completed',completed_items=1,result={'material_id':material_id,'title':generated['title'],'model':generated['model'],'usage':usage,'cost':price})
                        return self.send(200,{'material_id':material_id,'title':generated['title'],'summary':generated['summary'],'model':generated['model'],'generated_at_utc':generated_at,'usage':usage,'cost':price,'job_id':job_id})
                    except SummaryGenerationError as ex:
                        usage=ex.usage or {}
                        if not usage_recorded and (usage.get('input_tokens') or usage.get('output_tokens')):
                            price=calculate_text_cost({'input_tokens':usage.get('input_tokens',0),'output_tokens':usage.get('output_tokens',0)})
                            database.add_api_usage(operation='material_summary_generation',model=ex.model,input_tokens=price['input_tokens'],output_tokens=price['output_tokens'],estimated_usd=price['usd'],job_id=job_id,rate_version=price['rate_version'])
                        database.update_api_job(job_id,status='failed',error=str(ex))
                        raise
                    except Exception as ex:
                        database.update_api_job(job_id,status='failed',error=api_error(ex))
                        raise
                if route == '/api/materials/update':
                    material=database.get_material(req['material_id'])
                    if material is None:return self.send(404,{'error':'保存済み教材が見つかりません。'})
                    database.update_material(req['material_id'],req['title'],req['text_content'])
                    return self.send(200,{'saved':True})
                if route == '/api/materials/archive':
                    database.archive_material(req['material_id'],bool(req.get('archived',True)))
                    return self.send(200,{'saved':True})
                if route == '/api/materials/delete':
                    try:deleted=database.delete_material(req['material_id'])
                    except LookupError:return self.send(404,{'error':'Material not found'})
                    cleanup=remove_material_artifacts(deleted['artifact_paths'],directory=SAVE_DIR)
                    return self.send(200,{'deleted':True,'material_id':deleted['material']['material_id'],'title':deleted['material']['title'],'removed_files':cleanup['removed'],'missing_files':cleanup['missing'],'skipped_files':cleanup['skipped'],'file_cleanup_errors':cleanup['errors'],'shared_files_kept':deleted['shared_artifacts']})
                if route == '/api/study-set/plan':
                    direction=req.get('direction','en_to_ja'); count=max(1,min(50,int(req.get('count',50))))
                    raw_recent=req.get('recent_attempts');recent_attempts=int(raw_recent) if raw_recent not in (None,'') else None
                    raw_accuracy=req.get('max_recent_accuracy');max_recent_accuracy=float(raw_accuracy) if raw_accuracy not in (None,'') else None
                    include_insufficient_history=bool(req.get('include_insufficient_history',False))
                    items=database.weak_vocabulary(direction=direction,category=req.get('category'),limit=count,include_unstudied=bool(req.get('include_unstudied',True)),mastery_status=req.get('mastery_status','all'),recent_attempts=recent_attempts,max_recent_accuracy=max_recent_accuracy,include_insufficient_history=include_insufficient_history)
                    history_summary=database.study_set_history_summary(direction=direction,category=req.get('category'))
                    difficulty=req.get('difficulty','');
                    if difficulty: items=[item for item in items if item.get('difficulty_level')==difficulty]
                    estimated_text=len(items)*(60*.10+40*.50)/1_000_000
                    estimated_audio_seconds=sum(len(item['english'].split())+10 for item in items)/2.5
                    estimated_realtime=(estimated_audio_seconds*40*20)/1_000_000
                    estimated_transcription=estimated_audio_seconds/60*.006
                    generation_mode=req.get('generation_mode','per_vocabulary')
                    if generation_mode not in ('per_vocabulary','article'):
                        return self.send(400,{'error':'Invalid generation mode'})
                    conditions={'category':req.get('category'),'direction':direction,'count':count,'include_unstudied':bool(req.get('include_unstudied',True)),'mastery_status':req.get('mastery_status','all'),'difficulty':difficulty,'theme':req.get('theme',''),'length':req.get('length','short'),'generation_mode':generation_mode,'recent_attempts':recent_attempts,'max_recent_accuracy':max_recent_accuracy,'include_insufficient_history':include_insufficient_history,'algorithm_version':'weakness-v1'}
                    database.set_setting('last_study_set_conditions',conditions)
                    return self.send(200,{'conditions':conditions,'selected_count':len(items),'items':items,'history_summary':history_summary,'estimated_text_usd':estimated_text,'estimated_realtime_usd':estimated_realtime,'estimated_transcription_usd':estimated_transcription,'estimated_total_usd':estimated_text+estimated_realtime+estimated_transcription,'estimated_audio_seconds':estimated_audio_seconds,'model':TEXT_MODEL,'rate_version':'2026-10-24-v1','estimate_note':'音声時間は一語あたり概算。実料金はAPI応答の使用量で確定します。'})
                if route == '/api/study-set/generate':
                    vocab_ids=[str(value) for value in req.get('vocab_ids',[])][:50]
                    generation_mode=req.get('generation_mode','per_vocabulary')
                    if generation_mode not in ('per_vocabulary','article'):
                        return self.send(400,{'error':'Invalid generation mode'})
                    items=database.vocabulary_by_ids(vocab_ids)
                    if len({item['vocab_id'] for item in items})!=len(set(vocab_ids)):
                        return self.send(400,{'error':'一部の選択語彙が見つかりません。'})
                    if not items:return self.send(400,{'error':'英文作成に使う語彙を選択してください。'})
                    job_id=database.create_api_job('study_set_generation',{'vocab_ids':vocab_ids,'difficulty':req.get('difficulty',''),'theme':req.get('theme',''),'length':req.get('length','short'),'generation_mode':generation_mode},len(items),TEXT_MODEL)
                    database.update_api_job(job_id,status='running')
                    threading.Thread(target=process_study_set_job,args=(job_id,API_KEY),daemon=True).start()
                    return self.send(202,{'job_id':job_id})
                if route == '/api/study-set/resume':
                    job=database.get_api_job(req.get('job_id',''))
                    if not job or job['job_type']!='study_set_generation' or job['status']!='failed':return self.send(409,{'error':'Failed study set job not found'})
                    database.update_api_job(job['job_id'],status='running',error=None)
                    threading.Thread(target=process_study_set_job,args=(job['job_id'],API_KEY),daemon=True).start()
                    return self.send(202,{'job_id':job['job_id']})
                if route == '/api/study-set/save':
                    text_content=str(req.get('text_content','')).strip()
                    if not text_content:return self.send(400,{'error':'教材の英文が空です。'})
                    metadata=req.get('metadata',{})
                    selected=database.vocabulary_by_ids(metadata.get('selected_vocab_ids',[]))
                    from .vocabulary import find_usage
                    usages=[]
                    for item in selected:
                        matches=find_usage(text_content,item['english'])
                        if not matches:return self.send(400,{'error':f"編集後の英文に対象語がありません: {item['english']}"})
                        usages.extend({'vocab_id':item['vocab_id'],'sense_id':item['sense_id'],'usage_text':m['text'],'usage_start':m['start'],'usage_end':m['end']} for m in matches)
                    parts=[part.strip() for part in re.split(r'\n\s*\n',text_content) if part.strip()]
                    group_id=__import__('uuid').uuid4().hex
                    parent_metadata={**metadata,'study_set_id':group_id,'aggregate_material':True,'part_count':len(parts)}
                    material_id=database.create_material(title=req.get('title','Vocabulary practice'),text_content=text_content,source=req.get('source','dataset'),difficulty_level=req.get('difficulty_level'),metadata=parent_metadata)
                    database.attach_material_vocabulary(material_id,usages)
                    material_ids=[material_id]
                    for index,part in enumerate(parts,1):
                        part_usages=[];part_ids=[]
                        for item in selected:
                            matches=find_usage(part,item['english'])
                            if matches:
                                part_ids.append(item['vocab_id'])
                                part_usages.extend({'vocab_id':item['vocab_id'],'sense_id':item['sense_id'],'usage_text':m['text'],'usage_start':m['start'],'usage_end':m['end']} for m in matches)
                        part_metadata={**metadata,'study_set_id':group_id,'part_index':index,'part_count':len(parts),'selected_vocab_ids':part_ids}
                        part_id=database.create_material(title=f"{req.get('title','Vocabulary practice')} — {index}/{len(parts)}",text_content=part,source=req.get('source','dataset'),difficulty_level=req.get('difficulty_level'),metadata=part_metadata)
                        database.attach_material_vocabulary(part_id,part_usages);material_ids.append(part_id)
                    return self.send(200,{'material_id':material_id,'material_ids':material_ids,'study_set_id':group_id,'part_count':len(parts)})
                return self.send(404, {'error': 'Not found'})
            except OpenAIError as ex:
                return self.send(502, {'error':str(ex),'retryable':ex.retryable})
            except (KeyError, ValueError, TypeError, json.JSONDecodeError) as ex:
                return self.send(400, {'error': str(ex)})
        if self.path!='/generate':return self.send(404,{'error':'Not found'})
        if not API_KEY:return self.send(400,{'error':'config.json の OPENAI_API_KEY にAPIキーを設定してください。'})
        self._generation_stream_started=False
        api_job_id=None
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>30000:return self.send(413,{'error':'入力が大きすぎます。'})
            req=json.loads(self.rfile.read(length))
            text=req.get('text','').strip()
            voice=req.get('voice','marin')
            if not text:return self.send(400,{'error':'英文を入力してください。'})
            if len(text)>MAX_TEXT_CHARS:return self.send(400,{'error':f'英文が長すぎます。現在{len(text)}文字です。{MAX_TEXT_CHARS}文字以内にしてください。'})
            if voice not in VOICES:return self.send(400,{'error':'音声の選択が不正です。'})
            style=req.get('style','natural')
            emit=lambda percent,stage:self.send_stream_event({'type':'progress','percent':max(1,min(99,int(percent))),'stage':stage})
            emit(2,'preparing')
            api_job_id=database.create_api_job('overlap_generation',{'text':text,'voice':voice,'style':style},3,MODEL)
            database.update_api_job(api_job_id,status='running')
            material_id=req.get('material_id')
            if not material_id:
                material_id=database.create_material(title=text[:72] or 'Overlap practice',text_content=text,source='manual',metadata={'voice':voice,'style':style})
            blocks,spoken_text=parse_practice_text(text)
            emit(8,'text')
            blocks,text_usage=generate_study_material(spoken_text)
            emit(22,'audio')
            audio, transcript, usage = realtime_speech(spoken_text,voice,style,on_progress=lambda fraction:emit(22+int(48*fraction),'audio'))
            audio_seconds=len(audio)/(24000*2)
            # Long, single-pass Whisper requests can lose or shift an early block of
            # word timestamps.  Transcribe short WAV sections, then add each section's
            # offset so every timestamp remains on the original audio timeline.
            emit(72,'transcription')
            words=complete_word_timings(spoken_text,transcribe_audio_chunks(audio,on_progress=lambda current,total:emit(72+int(19*current/max(1,total)),'transcription')),audio_seconds)
            emit(92,'saving')
            cost=calculate_cost(usage,audio_seconds)
            text_cost=calculate_text_cost(text_usage)
            cost['text_generation']=text_cost
            cost['text_generation_usd']=text_cost['usd']
            cost['total_usd']=round(cost['total_usd']+text_cost['usd'],8)
            database.add_api_usage(operation='overlap_text_generation',model=text_cost['model'],input_tokens=text_cost['input_tokens'],output_tokens=text_cost['output_tokens'],estimated_usd=text_cost['usd'],job_id=api_job_id,rate_version=text_cost['rate_version'])
            database.add_api_usage(operation='overlap_audio_generation',model=MODEL,audio_seconds=audio_seconds,estimated_usd=cost['realtime_usd'],job_id=api_job_id,rate_version='2026-10-24-v1')
            database.add_api_usage(operation='overlap_transcription',model=TRANSCRIPTION_MODEL,audio_seconds=audio_seconds,estimated_usd=cost['transcription_usd'],job_id=api_job_id,rate_version='2026-10-24-v1')
            audio_mp3=wav_to_mp3(audio)
            audio_file=save_audio_artifact(audio_mp3,directory=SAVE_DIR)
            content={'spoken_text':spoken_text,'blocks':blocks,'transcript':transcript,'words':words,
                     'voice':voice,'style':style,'model':MODEL,'audio_seconds':round(audio_seconds,2),
                     'word_count':len(re.findall(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*",spoken_text)),
                     'character_count':len(text),'cost':cost}
            database.store_material_generation(material_id,text_content=text,audio_path=audio_file,content=content)
            database.update_api_job(api_job_id,status='completed',completed_items=3,result={'audio_file':audio_file,'cost':cost})
            self.send_stream_event({'type':'complete','result':{'audio':'data:audio/mpeg;base64,'+base64.b64encode(audio_mp3).decode(), 'words':words,'blocks':blocks,'spoken_text':spoken_text,'transcript':transcript,'model':MODEL,'audio_file':audio_file,'cost':cost,'material_id':material_id}})
        except Exception as ex:
            if api_job_id:
                database.update_api_job(api_job_id,status='failed',error=api_error(ex))
            if self._generation_stream_started:self.send_stream_event({'type':'error','error':api_error(ex)})
            else:self.send(502,{'error':api_error(ex)})
