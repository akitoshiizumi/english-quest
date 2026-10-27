import json
import struct
import tempfile
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from english_overlap.http import Handler
from english_overlap import database
from english_overlap.database import connect, migrate_database

def generation_stream(response):
    return [json.loads(line) for line in response.read().decode('utf-8').splitlines() if line.strip()]


class HttpIntegrationTests(unittest.TestCase):
    def test_practice_score_api_supports_seed_and_validates_random_range(self):
        url='/api/next-question?direction=en_to_ja&random_range=20&random_seed=stable'
        _,_,first=self.get(url);_,_,second=self.get(url)
        self.assertEqual(json.loads(first),json.loads(second))
        item=json.loads(first)['item']
        self.assertEqual((item['correct_count'],item['answer_count']),(0,0))
        self.assertEqual(item['score'],item['random_adjustment'])
        self.assertLessEqual(abs(item['random_adjustment']),20)
        for value in ['-1','101','nan','inf']:
            with self.subTest(value=value):
                with self.assertRaises(HTTPError) as caught:self.get('/api/next-question?random_range='+value)
                self.assertEqual(caught.exception.code,400)

    def test_sentence_damage_api_is_idempotent_and_rejects_fractional_counts(self):
        _,_,session=self.post_json('/api/overlap/session',{})
        payload={'session_id':session['session_id'],'material_id':'fixture-material','duration_seconds':3,
                 'completed_sentences':1,'idempotency_key':'sentence-damage'}
        self.post_json('/api/overlap/activity',payload)
        self.post_json('/api/overlap/activity',payload)
        _,_,progress=self.get('/api/adventure')
        self.assertEqual(json.loads(progress)['total_damage'],1)
        with self.assertRaises(HTTPError) as caught:
            self.post_json('/api/overlap/activity',{**payload,'completed_sentences':1.5,'idempotency_key':'bad-count'})
        self.assertEqual(caught.exception.code,400)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        from english_overlap import http
        self.http = http
        self.original_root = http.ROOT
        self.original_save_dir = http.SAVE_DIR
        http.ROOT = self.folder
        http.SAVE_DIR = self.folder / 'materials'
        http.SAVE_DIR.mkdir()
        self.db_path = self.folder / 'test.sqlite3'
        self.original_database_path = http.database.database_path
        http.database.database_path = lambda: self.db_path
        migrate_database(self.db_path)
        with connect(self.db_path) as conn:
            conn.execute("INSERT INTO vocab(vocab_id,english,japanese,genre_tags) VALUES (?,?,?,?)", ('fixture-vocab','take part','参加する','WorkAndCareer'))
            conn.execute("INSERT INTO senses(vocab_id,sense_index,meaning,part_of_speech) VALUES (?,?,?,?)", ('fixture-vocab',0,'参加する','verb'))
            conn.execute("INSERT INTO categories(category_id,name) VALUES ('WorkAndCareer','WorkAndCareer')")
            conn.execute("INSERT INTO vocabulary_categories(vocab_id,category_id) VALUES ('fixture-vocab','WorkAndCareer')")
        app_build=self.folder/'english_overlap'/'static'/'app'/'assets'
        app_build.mkdir(parents=True)
        (self.folder/'english_overlap'/'static'/'app'/'index.html').write_text('<div id="root"></div><script type="module" src="/static/app/assets/main.js"></script>',encoding='utf-8')
        (app_build/'main.js').write_text('React fixture bundle',encoding='utf-8')
        (self.folder / 'config.json').write_text(json.dumps({'DEFAULT_TEXT': 'A fixture sentence.'}), encoding='utf-8')
        (http.SAVE_DIR / 'english_overlap_fixture.json').write_text(json.dumps({
            'text': 'A fixture sentence.', 'spoken_text': 'A fixture sentence.', 'words': [], 'blocks': [],
            'audio_file':'english_overlap_fixture.mp3','summary':'Fixture summary','summary_model':'fixture-model',
            'summary_prompt_version':'fixture-v2','summary_generated_at_utc':'2026-10-24T00:00:00+00:00'
        }), encoding='utf-8')
        (http.SAVE_DIR / 'english_overlap_fixture.mp3').write_bytes(b'fixture-audio')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.http.ROOT = self.original_root
        self.http.SAVE_DIR = self.original_save_dir
        self.http.database.database_path = self.original_database_path
        self.temp.cleanup()

    def get(self, path):
        with urlopen(self.base + path) as response:
            return response.status, response.headers.get_content_type(), response.read()

    def post_json(self, path, payload):
        request=Request(self.base+path,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
        with urlopen(request) as response:
            return response.status,response.headers.get_content_type(),json.loads(response.read())

    def saved_file_material_id(self, filename='english_overlap_fixture.json'):
        self.get('/api/materials')
        material=database.material_for_legacy_source(filename,path=self.db_path)
        self.assertIsNotNone(material)
        return material['material_id']

    def test_material_lists_are_database_authoritative_after_one_time_legacy_import(self):
        db_only_id=database.create_material(title='DB only fixture',text_content='Not in practice_data.',path=self.db_path)
        orphan_path=self.http.SAVE_DIR/'english_overlap_orphan.json'
        orphan_path.write_text(json.dumps({'text':'An orphan file sentence.','summary':'Orphan fixture'}),encoding='utf-8')
        invalid_path=self.http.SAVE_DIR/'english_overlap_invalid.json'
        invalid_path.write_text('{broken',encoding='utf-8')
        fixture_path=self.http.SAVE_DIR/'english_overlap_fixture.json'
        original_contents=fixture_path.read_bytes()
        status,_,management_raw=self.get('/api/materials')
        status2,_,overlap_raw=self.get('/api/materials/overlap-list')
        self.assertEqual((status,status2),(200,200))
        management=json.loads(management_raw)['items']
        overlap=json.loads(overlap_raw)
        self.assertEqual(overlap['count'],3)
        self.assertIn(db_only_id,{item['material_id'] for item in management})
        self.assertEqual({item['title'] for item in management if item['material_type']=='overlap'},{'Fixture summary','Orphan fixture'})
        self.assertEqual(json.loads(management_raw)['legacy_import_warnings'][0]['file'],'english_overlap_invalid.json')
        orphan=next(item for item in overlap['items'] if item['title']=='Orphan fixture')
        self.assertEqual(orphan['text_content'],'An orphan file sentence.')
        self.assertIsNone(orphan['file'])
        self.assertEqual(orphan['file_status'],'not_generated')
        self.assertEqual(len(database.list_materials(path=self.db_path)),3)
        self.get('/api/materials');self.get('/api/materials/overlap-list')
        self.assertEqual(len(database.list_materials(path=self.db_path)),3)
        fixture_path.write_text(json.dumps({'text':'Changed externally after import.'}),encoding='utf-8')
        fixture_after=next(item for item in json.loads(self.get('/api/materials')[2])['items'] if item['material_id']==self.saved_file_material_id())
        self.assertEqual(fixture_after['text_content'],'A fixture sentence.')
        self.assertNotEqual(fixture_path.read_bytes(),original_contents)
        _,_,filtered=self.get('/api/materials?q=orphan')
        self.assertEqual([item['title'] for item in json.loads(filtered)['items']],['Orphan fixture'])


    def test_overlap_material_metadata_exposes_database_provenanced_ai_summaries(self):
        db_only_id=database.create_material(title='AI summary fixture',text_content='Synthetic text.',path=self.db_path)
        database.update_material_summary(db_only_id,'AI summary fixture','A generated summary.',model='fixture-model',prompt_version='fixture-v2',generated_at_utc='2026-10-25T00:00:00+00:00',path=self.db_path)
        items=json.loads(self.get('/api/materials/overlap-list')[2])['items']
        self.assertIn(db_only_id,{item['material_id'] for item in items})
        generated=next(item for item in items if item['material_id']==db_only_id)
        self.assertEqual(generated['ai_summary'],'A generated summary.')
        updated=next(item for item in items if item['material_id']==self.saved_file_material_id())
        self.assertEqual(updated['ai_summary'],'Fixture summary')
        self.assertEqual(updated['summary'],'Fixture summary')
        self.assertEqual(updated['created_at'],generated['created_at'])
        self.assertEqual(json.loads(updated['content_json'])['summary_model'],'fixture-model')
        self.assertIsNotNone(generated['created_at'])


    def test_app_config_offers_advanced_native_speech_style(self):
        status, content_type, body = self.get('/app-config')
        self.assertEqual((status, content_type), (200, 'application/json'))
        styles = json.loads(body)['speech_styles']
        self.assertEqual(list(styles)[-2:], ['reduced_extreme', 'native_unfiltered'])
        self.assertIn('ネイティブ', styles['native_unfiltered']['label'])

    def test_learning_goals_api_persists_valid_targets_and_reports_lifetime_progress(self):
        status, content_type, raw = self.get('/api/learning-goals')
        self.assertEqual((status, content_type), (200, 'application/json'))
        initial=json.loads(raw)
        self.assertEqual(initial['goals'],{'overlap_hours':None,'vocabulary_count':None})
        saved_status,_,saved=self.post_json('/api/learning-goals',{'overlap_hours':0.5,'vocabulary_count':1})
        self.assertEqual(saved_status,200)
        self.assertEqual(saved['goals'],{'overlap_hours':0.5,'vocabulary_count':1})
        item=json.loads(self.get('/api/next-question?direction=en_to_ja')[2])['item']
        for key,rating in [('goal-answer-1','again'),('goal-answer-2','known')]:
            answer_status,_,answer=self.post_json('/api/answer',{'vocab_id':item['vocab_id'],'sense_id':item['sense_id'],'direction':'en_to_ja','rating':rating,'duration_seconds':1,'idempotency_key':key})
            self.assertEqual((answer_status,answer['saved']),(200,True))
        overlap_session=self.post_json('/api/overlap/session',{'material_id':'fixture-material'})[2]['session_id']
        activity_status,_,activity=self.post_json('/api/overlap/activity',{'session_id':overlap_session,'material_id':'fixture-material','duration_seconds':1800,'idempotency_key':'goal-overlap-1'})
        self.assertEqual((activity_status,activity['saved']),(200,True))
        _,_,progress_raw=self.get('/api/learning-goals')
        progress=json.loads(progress_raw)
        self.assertEqual(progress['overlap_seconds'],1800)
        self.assertEqual(progress['learned_vocabulary_count'],1)
        self.get('/api/statistics?days=1')
        _,_,same_period_progress=self.get('/api/learning-goals')
        self.assertEqual(json.loads(same_period_progress),progress)
        self.post_json('/api/learning-goals',{'overlap_hours':None,'vocabulary_count':1})
        _,_,cleared_raw=self.get('/api/learning-goals')
        self.assertEqual(json.loads(cleared_raw)['goals'],{'overlap_hours':None,'vocabulary_count':1})
        with self.assertRaises(HTTPError) as invalid:
            self.post_json('/api/learning-goals',{'overlap_hours':-1,'vocabulary_count':1})
        self.assertEqual(invalid.exception.code,400)
        self.post_json('/api/learning-goals',{'overlap_hours':None,'vocabulary_count':None})
        _,_,final_raw=self.get('/api/learning-goals')
        self.assertEqual(json.loads(final_raw)['goals'],{'overlap_hours':None,'vocabulary_count':None})

    def test_react_home_bundle_and_legacy_shortcut_asset_are_served(self):
        status, content_type, body = self.get('/')
        self.assertEqual(status, 200)
        self.assertEqual(content_type, 'text/html')
        self.assertIn(b'<div id="root"></div>', body)
        status, content_type, body = self.get('/static/shortcuts.js')
        self.assertEqual(status, 200)
        self.assertEqual(content_type, 'text/javascript')
        self.assertIn(b'EnglishOverlapKeys', body)
        status, content_type, body = self.get('/static/statistics_distribution.js')
        self.assertEqual(status, 200)
        self.assertEqual(content_type, 'text/javascript')
        self.assertIn(b'buildVocabularyDistribution', body)
        status, content_type, body = self.get('/static/app/assets/main.js')
        self.assertEqual(status,200)
        self.assertEqual(content_type,'text/javascript')
        self.assertIn(b'React fixture bundle',body)

    def test_material_delete_cleans_unshared_artifacts_and_preserves_vocabulary_and_history(self):
        material_id=database.create_material(title='Delete fixture',text_content='Take part.',path=self.db_path)
        with database.connect(self.db_path) as conn:
            sense_id=conn.execute("SELECT sense_id FROM senses WHERE vocab_id='fixture-vocab'").fetchone()[0]
        database.attach_material_vocabulary(material_id,[{'vocab_id':'fixture-vocab','sense_id':sense_id}],path=self.db_path)
        session_id=database.create_study_session('overlap',path=self.db_path)
        database.record_overlap_activity(session_id=session_id,material_id=material_id,duration_seconds=12,idempotency_key='delete-fixture',path=self.db_path)
        audio_name='english_overlap_delete_fixture.mp3';json_name='english_overlap_delete_fixture.json'
        (self.http.SAVE_DIR/audio_name).write_bytes(b'synthetic audio')
        (self.http.SAVE_DIR/json_name).write_text('{}',encoding='utf-8')
        (self.http.SAVE_DIR/'english_overlap_unrelated.mp3').write_bytes(b'keep')
        database.store_material_generation(material_id,text_content='Take part.',audio_path=audio_name,content={},path=self.db_path)
        with connect(self.db_path) as conn:conn.execute('UPDATE materials SET json_path=? WHERE material_id=?',(json_name,material_id))
        status,content_type,result=self.post_json('/api/materials/delete',{'material_id':material_id})
        self.assertEqual((status,content_type),(200,'application/json'))
        self.assertEqual(result['removed_files'],[audio_name])
        self.assertEqual(result['shared_files_kept'],[])
        self.assertFalse((self.http.SAVE_DIR/audio_name).exists())
        self.assertTrue((self.http.SAVE_DIR/json_name).exists(),'legacy JSON is retained as an inert import artifact')
        self.assertTrue((self.http.SAVE_DIR/'english_overlap_unrelated.mp3').exists())
        self.assertEqual(database.list_materials(path=self.db_path),[])
        with database.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM vocab WHERE vocab_id='fixture-vocab'").fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT count(*) FROM material_vocabulary').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM study_events').fetchone()[0],1)
        with self.assertRaises(HTTPError) as missing:
            self.post_json('/api/materials/delete',{'material_id':'does-not-exist'})
        self.assertEqual(missing.exception.code,404)

    def test_material_delete_keeps_shared_and_out_of_directory_files(self):
        first=database.create_material(title='First material',text_content='First.',path=self.db_path)
        second=database.create_material(title='Second material',text_content='Second.',path=self.db_path)
        outside_material=database.create_material(title='Outside material',text_content='Outside.',path=self.db_path)
        shared='english_overlap_shared.mp3';first_json='english_overlap_first.json';outside=self.folder/'outside.mp3'
        (self.http.SAVE_DIR/shared).write_bytes(b'shared')
        (self.http.SAVE_DIR/first_json).write_text('{}',encoding='utf-8')
        outside.write_bytes(b'outside')
        with database.connect(self.db_path) as conn:
            conn.execute('UPDATE materials SET audio_path=?,json_path=? WHERE material_id=?',(shared,first_json,first))
            conn.execute('UPDATE materials SET audio_path=? WHERE material_id=?',(shared,second))
            conn.execute('UPDATE materials SET audio_path=? WHERE material_id=?',('../outside.mp3',outside_material))
        status,_,result=self.post_json('/api/materials/delete',{'material_id':first})
        self.assertEqual(status,200)
        self.assertEqual(result['shared_files_kept'],[shared])
        self.assertTrue((self.http.SAVE_DIR/shared).exists())
        self.assertTrue((self.http.SAVE_DIR/first_json).exists())
        self.assertEqual(self.post_json('/api/materials/delete',{'material_id':outside_material})[2]['skipped_files'],['../outside.mp3'])
        self.assertTrue(outside.exists())

    def test_storage_status_reports_the_isolated_current_data_folder(self):
        status,_,body=self.get('/api/storage/status')
        info=json.loads(body)
        self.assertEqual(status,200)
        self.assertEqual(info,{'role':'production','directory':str(self.http.SAVE_DIR.resolve())})

    def test_database_admin_status_backup_restore_and_rejects_untrusted_paths(self):
        from urllib.request import Request
        status,_,body=self.get('/api/database/status')
        info=json.loads(body)
        self.assertEqual((status,info['schema_version'],info['integrity']),(200,7,'ok'))
        req=Request(self.base+'/api/database/backup',data=b'{}',headers={'Content-Type':'application/json'},method='POST')
        with urlopen(req) as response: backup=json.loads(response.read())
        self.assertTrue(backup['created'].startswith('test.backup-'))
        with database.connect(self.db_path) as conn: conn.execute("UPDATE vocab SET english='mutated' WHERE vocab_id='fixture-vocab'")
        body=json.dumps({'backup_name':backup['created']}).encode()
        req=Request(self.base+'/api/database/restore',data=body,headers={'Content-Type':'application/json'},method='POST')
        with urlopen(req) as response: restored=json.loads(response.read())
        self.assertEqual(restored['restored'],backup['created'])
        with database.connect(self.db_path) as conn:self.assertEqual(conn.execute("SELECT english FROM vocab WHERE vocab_id='fixture-vocab'").fetchone()[0],'take part')
        bad=json.dumps({'backup_name':'..\\outside.sqlite3'}).encode()
        req=Request(self.base+'/api/database/restore',data=bad,headers={'Content-Type':'application/json'},method='POST')
        with self.assertRaises(HTTPError) as error:urlopen(req)
        self.assertEqual(error.exception.code,400)

    def test_saved_data_and_audio_are_served_from_fixture_folder(self):
        _, _, listing = self.get('/saved')
        self.assertIn(b'A fixture sentence.', listing)
        _, _, data = self.get('/saved-data?name=english_overlap_fixture.json')
        material_id=self.saved_file_material_id()
        _, _, data = self.get('/saved-data?material_id='+material_id)
        self.assertEqual(json.loads(data)['text'], 'A fixture sentence.')
        self.assertEqual(json.loads(data)['created_at'],database.get_material(material_id,path=self.db_path)['created_at_utc'])
        _, content_type, audio = self.get('/saved-audio?name=english_overlap_fixture.mp3')
        self.assertEqual(content_type, 'audio/mpeg')
        self.assertEqual(audio, b'fixture-audio')

    def test_deleting_imported_material_does_not_resurrect_it_from_legacy_json(self):
        material_id=self.saved_file_material_id()
        legacy=self.http.SAVE_DIR/'english_overlap_fixture.json'
        self.assertTrue(legacy.is_file())
        self.post_json('/api/materials/delete',{'material_id':material_id})
        listed=json.loads(self.get('/api/materials')[2])['items']
        self.assertNotIn(material_id,{item['material_id'] for item in listed})
        self.assertTrue(legacy.is_file())
        with connect(self.db_path) as conn:
            audit=conn.execute('SELECT material_id FROM material_legacy_imports WHERE source_name=?',('english_overlap_fixture.json',)).fetchone()
        self.assertIsNotNone(audit)
        self.assertIsNone(database.get_material(material_id,path=self.db_path))

    def test_saved_route_rejects_path_traversal(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + '/saved-data?name=..%2Fenglish_overlap_fixture.json')
        self.assertEqual(error.exception.code, 400)

    def test_vocabulary_question_answer_and_key_settings_api(self):
        _, _, payload = self.get('/api/next-question?direction=en_to_ja&category=WorkAndCareer')
        question = json.loads(payload)['item']
        self.assertEqual(question['english'], 'take part')
        self.assertEqual(question['meaning'], '参加する')
        from urllib.request import Request
        body = json.dumps({'vocab_id': question['vocab_id'], 'sense_id': question['sense_id'], 'direction': 'en_to_ja', 'rating': 'known', 'duration_seconds': 2.5, 'idempotency_key': 'e2e-fixture-answer'}).encode()
        req = Request(self.base + '/api/answer', data=body, headers={'Content-Type':'application/json'}, method='POST')
        with urlopen(req) as response:
            self.assertTrue(json.loads(response.read())['saved'])
        with urlopen(req) as response:
            self.assertFalse(json.loads(response.read())['saved'])
        with database.connect(self.db_path) as conn:
            conn.execute("UPDATE study_events SET occurred_at_utc='2026-10-24T14:59:00+00:00' WHERE idempotency_key='e2e-fixture-answer'")
        self.assertIn(b'"known_rate": 1.0', self.get('/api/statistics')[2])
        statistics=json.loads(self.get('/api/statistics?days=7')[2])
        self.assertIn('vocabulary_active_seconds',statistics)
        self.assertIn('overlap_active_seconds',statistics)
        self.assertEqual(set(statistics['database_stats']), {'vocabulary_count','active_vocabulary_count','archived_vocabulary_count','sense_count','attempt_count','known_count','again_count','accuracy','unseen_vocabulary_count'})
        self.assertEqual(statistics['database_stats'], {'vocabulary_count':1,'active_vocabulary_count':1,'archived_vocabulary_count':0,'sense_count':1,'attempt_count':1,'known_count':1,'again_count':0,'accuracy':1.0,'unseen_vocabulary_count':0})
        self.assertEqual(len(statistics['vocabulary_performance']),1)
        self.assertEqual(statistics['vocabulary_performance'][0]['english'],'take part')
        self.assertEqual(statistics['vocabulary_performance'][0]['known_rate'],1.0)
        self.assertIn('daily',statistics)
        self.assertIn('2026-10-24',statistics['daily'])
        with self.assertRaises(HTTPError) as invalid_range:
            urlopen(self.base+'/api/statistics?days=invalid')
        self.assertEqual(invalid_range.exception.code,400)
        with database.connect(self.db_path) as conn:
            conn.execute("INSERT INTO vocab(vocab_id,english,japanese) VALUES ('fixture-unlearned','guide','案内')")
            conn.execute("INSERT INTO senses(vocab_id,sense_index,meaning) VALUES ('fixture-unlearned',0,'案内')")
        _, _, unlearned_payload = self.get('/api/next-question?direction=en_to_ja&category=WorkAndCareer&mastery_status=unlearned')
        self.assertIsNone(json.loads(unlearned_payload)['item'])
        _, _, unlearned_payload = self.get('/api/next-question?direction=en_to_ja&mastery_status=unlearned')
        self.assertEqual(json.loads(unlearned_payload)['item']['english'], 'guide')

    def test_recent_accuracy_all_incorrect_and_session_count_limits(self):
        from english_overlap.database import create_study_session, record_vocabulary_answer
        with connect(self.db_path) as conn:
            for vocab_id, english in [('all-wrong','all wrong'),('short-history','short history')]:
                conn.execute('INSERT INTO vocab(vocab_id,english,japanese) VALUES (?,?,?)',(vocab_id,english,english))
                conn.execute('INSERT INTO senses(vocab_id,sense_index,meaning) VALUES (?,0,?)',(vocab_id,english))
            conn.execute("INSERT INTO senses(vocab_id,sense_index,meaning) VALUES ('all-wrong',1,'another meaning')")
        sense_ids={}
        with connect(self.db_path) as conn:
            sense_ids={row['vocab_id']:row['sense_id'] for row in conn.execute("SELECT vocab_id,sense_id FROM senses")}
        session=create_study_session('vocabulary',path=self.db_path)
        for index,rating in enumerate(['known','again','known']):
            record_vocabulary_answer(session_id=session,vocab_id='fixture-vocab',sense_id=sense_ids['fixture-vocab'],direction='en_to_ja',rating=rating,duration_seconds=1,idempotency_key=f'mixed-{index}',path=self.db_path)
        session=create_study_session('vocabulary',path=self.db_path)
        for index in range(3):
            record_vocabulary_answer(session_id=session,vocab_id='all-wrong',sense_id=sense_ids['all-wrong'],direction='en_to_ja',rating='again',duration_seconds=1,idempotency_key=f'wrong-{index}',path=self.db_path)
        record_vocabulary_answer(session_id=session,vocab_id='all-wrong',sense_id=sense_ids['all-wrong'],direction='ja_to_en',rating='known',duration_seconds=1,idempotency_key='opposite-direction',path=self.db_path)
        session=create_study_session('vocabulary',path=self.db_path)
        record_vocabulary_answer(session_id=session,vocab_id='short-history',sense_id=sense_ids['short-history'],direction='en_to_ja',rating='again',duration_seconds=1,idempotency_key='short-one',path=self.db_path)
        # Deliberately tie timestamps: insertion order must resolve the latest answer.
        with connect(self.db_path) as conn:
            conn.execute("UPDATE study_events SET occurred_at_utc='2026-10-24T00:00:00+00:00' WHERE event_type='vocabulary_answer'")
        _, _, payload=self.get('/api/next-question?direction=en_to_ja&recent_attempts=3&max_recent_accuracy=0&all_attempts_incorrect=true')
        self.assertEqual(json.loads(payload)['item']['vocab_id'],'all-wrong')
        _, _, payload=self.get('/api/next-question?direction=en_to_ja&recent_attempts=3&max_recent_accuracy=0&include_insufficient_history=true')
        self.assertIn(json.loads(payload)['item']['vocab_id'],('all-wrong','short-history'))
        _, _, payload=self.get('/api/next-question?direction=en_to_ja&count=1000&last_attempt_incorrect=true')
        selected=json.loads(payload)
        self.assertEqual(selected['total'],2)
        self.assertEqual({item['vocab_id'] for item in selected['items']},{'all-wrong','short-history'})
        self.assertEqual(selected['items'][0]['history'],['again']*3)
        _, _, payload=self.get('/api/next-question?direction=en_to_ja&count=1000&category=WorkAndCareer')
        self.assertEqual(json.loads(payload)['total'],1)
        with self.assertRaises(HTTPError) as too_many:
            urlopen(self.base+'/api/next-question?count=1001')
        self.assertEqual(too_many.exception.code,400)
        with self.assertRaises(HTTPError) as invalid_recent:
            urlopen(self.base+'/api/next-question?recent_attempts=101')
        self.assertEqual(invalid_recent.exception.code,400)

    def test_next_question_due_only_uses_history_and_preserves_standard_mode(self):
        from english_overlap.database import create_study_session, record_vocabulary_answer
        with connect(self.db_path) as conn:
            conn.execute("INSERT INTO vocab(vocab_id,english,japanese) VALUES ('second-fixture','second','second')")
            conn.execute("INSERT INTO senses(vocab_id,sense_index,meaning) VALUES ('second-fixture',0,'second meaning')")
            ids={row['vocab_id']:row['sense_id'] for row in conn.execute('SELECT vocab_id,sense_id FROM senses')}
        session=create_study_session(path=self.db_path)
        record_vocabulary_answer(session_id=session,vocab_id='fixture-vocab',sense_id=ids['fixture-vocab'],direction='en_to_ja',rating='again',duration_seconds=1,idempotency_key='due-api',path=self.db_path)
        with connect(self.db_path) as conn:
            conn.execute("UPDATE study_events SET occurred_at_utc='2026-10-23T15:00:00+00:00' WHERE idempotency_key='due-api'")
        _,_,payload=self.get('/api/next-question?direction=en_to_ja&due_only=true&count=10')
        result=json.loads(payload)
        self.assertEqual(result['total'],1)
        self.assertEqual(result['item']['vocab_id'],'fixture-vocab')
        _,_,payload=self.get('/api/next-question?direction=en_to_ja&count=10')
        self.assertEqual(json.loads(payload)['total'],2)
        _,_,payload=self.get('/api/next-question?direction=ja_to_en&due_only=true')
        self.assertEqual(json.loads(payload)['total'],0)

    def test_study_set_plan_filters_recent_answer_count_accuracy_and_direction(self):
        from urllib.request import Request
        from english_overlap.database import create_study_session, record_vocabulary_answer
        fixtures={'low-rate':['again','again','known'],'high-rate':['known']*3,'short-history':['again'],'other-direction':['again']*3}
        sense_ids={}
        with connect(self.db_path) as conn:
            for vocab_id in fixtures:
                conn.execute('INSERT INTO vocab(vocab_id,english,japanese) VALUES (?,?,?)',(vocab_id,vocab_id,vocab_id))
                conn.execute('INSERT INTO senses(vocab_id,sense_index,meaning) VALUES (?,0,?)',(vocab_id,vocab_id))
            for index in range(500):
                vocab_id=f'bulk-{index:03d}'
                conn.execute('INSERT INTO vocab(vocab_id,english,japanese) VALUES (?,?,?)',(vocab_id,vocab_id,vocab_id))
                conn.execute('INSERT INTO senses(vocab_id,sense_index,meaning) VALUES (?,0,?)',(vocab_id,vocab_id))
            sense_ids={row['vocab_id']:row['sense_id'] for row in conn.execute('SELECT vocab_id,sense_id FROM senses')}
        for vocab_id,ratings in fixtures.items():
            session=create_study_session(path=self.db_path)
            direction='ja_to_en' if vocab_id=='other-direction' else 'en_to_ja'
            for index,rating in enumerate(ratings):
                record_vocabulary_answer(session_id=session,vocab_id=vocab_id,sense_id=sense_ids[vocab_id],direction=direction,rating=rating,duration_seconds=1,idempotency_key=f'{vocab_id}-{index}',path=self.db_path)
        def plan(include_insufficient):
            body=json.dumps({'direction':'en_to_ja','count':50,'recent_attempts':3,'max_recent_accuracy':50,'include_insufficient_history':include_insufficient,'theme':'WorkAndCareer','mastery_status':'review'}).encode()
            req=Request(self.base+'/api/study-set/plan',data=body,headers={'Content-Type':'application/json'},method='POST')
            with urlopen(req) as response:return json.loads(response.read())
        inclusive=plan(True)
        self.assertEqual({item['vocab_id'] for item in inclusive['items']},{'low-rate','short-history'})
        self.assertEqual(inclusive['conditions']['theme'],'WorkAndCareer')
        self.assertEqual(inclusive['conditions']['recent_attempts'],3)
        self.assertEqual(inclusive['conditions']['max_recent_accuracy'],50)
        self.assertTrue(inclusive['conditions']['include_insufficient_history'])
        strict=plan(False)
        self.assertEqual({item['vocab_id'] for item in strict['items']},{'low-rate'})
        self.assertFalse(strict['conditions']['include_insufficient_history'])

    def test_study_set_recent_filters_include_studied_words_and_all_categories(self):
        from urllib.request import Request
        from english_overlap.database import create_study_session, record_vocabulary_answer
        ids={}
        with connect(self.db_path) as conn:
            for index in range(510):
                vocab_id=f'all-categories-{index:03d}'
                conn.execute('INSERT INTO vocab(vocab_id,english,japanese) VALUES (?,?,?)',(vocab_id,vocab_id,vocab_id))
                conn.execute('INSERT INTO senses(vocab_id,sense_index,meaning) VALUES (?,0,?)',(vocab_id,vocab_id))
            for vocab_id in ('matching-category','matching-later'):
                conn.execute('INSERT INTO vocab(vocab_id,english,japanese) VALUES (?,?,?)',(vocab_id,vocab_id,vocab_id))
                conn.execute('INSERT INTO senses(vocab_id,sense_index,meaning) VALUES (?,0,?)',(vocab_id,vocab_id))
            conn.execute("INSERT INTO categories(category_id,name) VALUES ('StudySetCategory','Study Set Category')")
            conn.execute("INSERT INTO vocabulary_categories(vocab_id,category_id) VALUES ('matching-category','StudySetCategory')")
            ids={row['vocab_id']:row['sense_id'] for row in conn.execute('SELECT vocab_id,sense_id FROM senses')}
        for vocab_id in ('all-categories-509','matching-category','matching-later'):
            session=create_study_session(path=self.db_path)
            record_vocabulary_answer(session_id=session,vocab_id=vocab_id,sense_id=ids[vocab_id],direction='en_to_ja',rating='again',duration_seconds=1,idempotency_key=vocab_id,path=self.db_path)
        def plan(category=None):
            body=json.dumps({'direction':'en_to_ja','count':1,'include_unstudied':True,'mastery_status':'all','category':category,'recent_attempts':1,'max_recent_accuracy':0,'include_insufficient_history':False}).encode()
            req=Request(self.base+'/api/study-set/plan',data=body,headers={'Content-Type':'application/json'},method='POST')
            with urlopen(req) as response:return json.loads(response.read())
        all_result=plan()
        self.assertEqual([item['vocab_id'] for item in all_result['items']],['all-categories-509'])
        self.assertEqual(all_result['selected_count'],1)
        self.assertEqual(all_result['history_summary']['directional_answer_vocabulary_count'],3)
        self.assertEqual(all_result['history_summary']['legacy_history_count_excluded'],0)
        category_result=plan('StudySetCategory')
        self.assertEqual([item['vocab_id'] for item in category_result['items']],['matching-category'])
        self.assertEqual(category_result['selected_count'],1)
        self.assertEqual(category_result['history_summary']['directional_answer_vocabulary_count'],1)

    def test_study_set_insufficient_history_includes_vocabulary_with_no_answers(self):
        from urllib.request import Request
        with connect(self.db_path) as conn:
            for vocab_id in ('no-history-a','no-history-b'):
                conn.execute('INSERT INTO vocab(vocab_id,english,japanese) VALUES (?,?,?)',(vocab_id,vocab_id,vocab_id))
                conn.execute('INSERT INTO senses(vocab_id,sense_index,meaning) VALUES (?,0,?)',(vocab_id,vocab_id))
            conn.execute("INSERT INTO categories(category_id,name) VALUES ('NoHistoryCategory','No History Category')")
            conn.executemany("INSERT INTO vocabulary_categories(vocab_id,category_id) VALUES (?,'NoHistoryCategory')",[('no-history-a',),('no-history-b',)])
        def plan(include_insufficient):
            body=json.dumps({'direction':'en_to_ja','category':'NoHistoryCategory','count':10,'include_unstudied':False,'mastery_status':'all','recent_attempts':3,'max_recent_accuracy':0,'include_insufficient_history':include_insufficient}).encode()
            req=Request(self.base+'/api/study-set/plan',data=body,headers={'Content-Type':'application/json'},method='POST')
            with urlopen(req) as response:return json.loads(response.read())
        included=plan(True)
        self.assertEqual({item['vocab_id'] for item in included['items']},{'no-history-a','no-history-b'})
        self.assertEqual(included['selected_count'],2)
        self.assertEqual(included['history_summary']['directional_answer_vocabulary_count'],0)
        excluded=plan(False)
        self.assertEqual(excluded['selected_count'],0)

    def test_study_set_plan_reports_directional_and_legacy_history_coverage(self):
        from urllib.request import Request
        from english_overlap.database import create_study_session, record_vocabulary_answer
        with connect(self.db_path) as conn:
            conn.execute('CREATE TABLE history(id INTEGER PRIMARY KEY,vocab_id TEXT,result TEXT)')
            conn.executemany('INSERT INTO history(vocab_id,result) VALUES (?,?)',[('fixture-vocab','OK'),('fixture-vocab','NG')])
        session=create_study_session(path=self.db_path)
        with connect(self.db_path) as conn:sense_id=conn.execute("SELECT sense_id FROM senses WHERE vocab_id='fixture-vocab'").fetchone()[0]
        record_vocabulary_answer(session_id=session,vocab_id='fixture-vocab',sense_id=sense_id,direction='en_to_ja',rating='again',duration_seconds=1,idempotency_key='coverage',path=self.db_path)
        body=json.dumps({'direction':'en_to_ja','category':'WorkAndCareer','count':5,'include_unstudied':False,'mastery_status':'all'}).encode()
        req=Request(self.base+'/api/study-set/plan',data=body,headers={'Content-Type':'application/json'},method='POST')
        with urlopen(req) as response:payload=json.loads(response.read())
        self.assertEqual(payload['history_summary'],{'direction':'en_to_ja','category':'WorkAndCareer','directional_answer_vocabulary_count':1,'legacy_history_count_excluded':2})

    def test_vocabulary_management_pages_are_sorted_filtered_and_stable(self):
        with connect(self.db_path) as conn:
            for index in range(125):
                vocab_id=f'page-{index:03d}'
                conn.execute('INSERT INTO vocab(vocab_id,english,japanese,tags) VALUES (?,?,?,?)',(vocab_id,f'Page Item {index:03d}','共通の意味',f'tag-{index%5}'))
                conn.execute('INSERT INTO senses(vocab_id,sense_index,meaning) VALUES (?,0,?)',(vocab_id,'共通の意味'))
        _, _, body=self.get('/api/vocabulary?page=1&page_size=50&sort_by=english&sort_direction=asc')
        first=json.loads(body)
        self.assertEqual((first['total'],first['page'],len(first['items'])),(126,1,50))
        self.assertEqual(first['items'][0]['vocab_id'],'page-000')
        _, _, body=self.get('/api/vocabulary?page=2&page_size=50&sort_by=english&sort_direction=asc')
        second=json.loads(body)
        self.assertEqual((second['page'],len(second['items'])),(2,50))
        self.assertFalse({row['vocab_id'] for row in first['items']}&{row['vocab_id'] for row in second['items']})
        _, _, body=self.get('/api/vocabulary?page=99&page_size=50&sort_by=english&sort_direction=desc')
        last=json.loads(body)
        self.assertEqual((last['page'],len(last['items'])),(3,26))
        _, _, body=self.get('/api/vocabulary?q=Page+Item+12&page=1&page_size=50&sort_by=japanese&sort_direction=asc')
        filtered=json.loads(body)
        self.assertEqual(filtered['total'],5)
        _, _, body=self.get('/api/vocabulary?page=1&page_size=50&sort_by=tags&sort_direction=desc')
        self.assertEqual(json.loads(body)['items'][0]['genre_tags'],'WorkAndCareer')
        _, _, body=self.get('/api/vocabulary?page=1&page_size=50&sort_by=english&sort_direction=desc')
        self.assertEqual(json.loads(body)['items'][0]['english'],'take part')
        _, _, body=self.get('/api/vocabulary?page=1&page_size=50&sort_by=english&sort_direction=asc')
        self.assertEqual(json.loads(body)['items'][0]['english'],'Page Item 000')
        with self.assertRaises(HTTPError) as invalid_sort:
            urlopen(self.base+'/api/vocabulary?page=1&page_size=50&sort_by=english;DROP%20TABLE%20vocab')
        self.assertEqual(invalid_sort.exception.code,400)
        with self.assertRaises(HTTPError) as oversized_page:
            urlopen(self.base+'/api/vocabulary?page=1&page_size=51')
        self.assertEqual(oversized_page.exception.code,400)

    def test_candidate_list_registration_and_export_api(self):
        from unittest.mock import patch
        from urllib.request import Request
        body=json.dumps({'source':'TAKE PART | 参加する | verb\ncomprehensive | 包括的 | adjective','source_type':'vocabulary_list'}).encode()
        req=Request(self.base+'/api/candidates/create',data=body,headers={'Content-Type':'application/json'},method='POST')
        with urlopen(req) as response: candidates=json.loads(response.read())
        self.assertEqual(len(candidates['items']),2)
        selected=[item['candidate_id'] for item in candidates['items'] if item['english']=='comprehensive']
        body=json.dumps({'batch_id':candidates['batch_id'],'candidate_ids':selected}).encode()
        from concurrent.futures import ThreadPoolExecutor
        def register_same_candidates(_):
            req=Request(self.base+'/api/candidates/select',data=body,headers={'Content-Type':'application/json'},method='POST')
            with urlopen(req) as response: return json.loads(response.read())
        with patch.object(self.http,'API_KEY',''):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(register_same_candidates,range(2)))
        self.assertEqual(sum(len(result['created_vocab_ids']) for result in results),1)
        created=next(result for result in results if result['created_vocab_ids'])
        with database.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM vocab WHERE english='comprehensive'").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT count(*) FROM senses WHERE vocab_id=?",(created['created_vocab_ids'][0],)).fetchone()[0],1)
        auto_job=database.latest_api_job('automatic_difficulty_assessment',path=self.db_path)
        self.assertEqual(auto_job['status'],'queued')
        created_sense=next(item for item in database.senses_for_difficulty(limit=100,path=self.db_path) if item['vocab_id']==created['created_vocab_ids'][0])
        self.assertIn(created_sense['sense_id'],auto_job['payload']['sense_ids'])
        _,content_type,csv=self.get('/api/vocabulary/export')
        self.assertEqual(content_type,'text/csv')
        self.assertIn(b'comprehensive',csv)

    def test_automatic_difficulty_status_and_settings_are_database_backed_without_exposing_key(self):
        from unittest.mock import patch
        from urllib.request import Request
        with patch.object(self.http,'API_KEY','fixture-secret'):
            status=json.loads(self.get('/api/difficulty/auto/status')[2])
            self.assertTrue(status['api_key_configured'])
            self.assertNotIn('fixture-secret',json.dumps(status))
            body=json.dumps({'enabled':False,'per_run_limit':3,'daily_budget_usd':0.12}).encode()
            req=Request(self.base+'/api/difficulty/auto/settings',data=body,headers={'Content-Type':'application/json'},method='POST')
            with urlopen(req) as response: saved=json.loads(response.read())
        self.assertEqual(saved['settings'],{'enabled':False,'per_run_limit':3,'daily_budget_usd':0.12})

    def test_startup_reuses_queued_automatic_job_when_api_key_becomes_available(self):
        from unittest.mock import patch
        import time
        from english_overlap.difficulty import process_difficulty_job
        with patch.object(self.http,'API_KEY',''):
            first=self.http.schedule_automatic_difficulty()
            self.assertEqual(database.get_api_job(first,path=self.db_path)['status'],'queued')
            self.assertEqual(self.http.schedule_automatic_difficulty(),first)
        def fixed_worker(job_id,*,api_key):
            def provider(endpoint,payload,*,api_key):
                return {'model':'fixture-model','output_text':json.dumps({'level':'B1','evidence':'合成 fixture'}),'usage':{'input_tokens':15,'output_tokens':8}}
            return process_difficulty_job(job_id,api_key=api_key,provider=provider,path=self.db_path)
        with patch.object(self.http,'API_KEY','fixture-key'),patch.object(self.http,'process_difficulty_job',side_effect=fixed_worker):
            self.assertEqual(self.http.schedule_automatic_difficulty(),first)
            deadline=time.time()+2
            while time.time()<deadline:
                job=database.get_api_job(first,path=self.db_path)
                if job['status']!='running':break
                time.sleep(.01)
        self.assertEqual(job['status'],'completed')
        self.assertEqual(job['completed_items'],1)
        self.assertEqual(database.count_pending_difficulty(path=self.db_path),0)

    def test_candidate_extraction_and_similarity_are_job_and_usage_tracked(self):
        from unittest.mock import patch
        from urllib.request import Request
        extraction=json.dumps({'source':'A comprehensive guide helps learners.','source_type':'english_text'}).encode()
        req=Request(self.base+'/api/candidates/create',data=extraction,headers={'Content-Type':'application/json'},method='POST')
        provider_result={'model':'fixture-text','output_text':json.dumps({'candidates':[{'english':'comprehensive','meaning':'包括的','part_of_speech':'adjective'}]}),'usage':{'input_tokens':21,'output_tokens':8}}
        with patch.object(self.http,'API_KEY','fixture-key'),patch.object(self.http,'request_json',return_value=provider_result):
            with urlopen(req) as response: created=json.loads(response.read())
        candidate=created['items'][0]
        body=json.dumps({'batch_id':created['batch_id'],'candidate_id':candidate['candidate_id'],'threshold':.8}).encode()
        req=Request(self.base+'/api/candidates/compare',data=body,headers={'Content-Type':'application/json'},method='POST')
        with patch.object(self.http,'API_KEY','fixture-key'),patch.object(self.http,'compare_candidate',return_value={'excluded':False,'reason':None,'model':'text-embedding-3-small','candidate_embedding':[1.0,0.0],'usage':{'total_tokens':7}}):
            with urlopen(req) as response: compared=json.loads(response.read())
        self.assertTrue(compared['job_id'])
        with database.connect(self.db_path) as conn:
            jobs=conn.execute("SELECT job_type,status,completed_items FROM api_jobs WHERE job_type IN ('candidate_extraction','candidate_similarity') ORDER BY created_at_utc").fetchall()
            self.assertEqual([tuple(row) for row in jobs],[('candidate_extraction','completed',1),('candidate_similarity','completed',1)])
            usage=conn.execute("SELECT operation,model,input_tokens,output_tokens FROM api_usage ORDER BY rowid").fetchall()
            self.assertEqual([tuple(row) for row in usage],[('candidate_extraction','fixture-text',21,8),('candidate_similarity','text-embedding-3-small',7,0)])

    def test_candidate_similarity_batch_aggregates_usage_and_persists_assessments_atomically(self):
        from unittest.mock import patch
        from urllib.request import Request
        batch_id=database.create_import_batch('vocabulary_list','batch one | meaning\nbatch two | meaning',path=self.db_path)
        ids=database.add_candidates(batch_id,[{'english':'batch one','meaning':'meaning'},{'english':'batch two','meaning':'meaning'}],path=self.db_path)
        created={'batch_id':batch_id,'items':database.list_candidates(batch_id,path=self.db_path)}
        body=json.dumps({'batch_id':created['batch_id'],'candidate_ids':[item['candidate_id'] for item in created['items']],'threshold':.82}).encode()
        req=Request(self.base+'/api/candidates/compare-batch',data=body,headers={'Content-Type':'application/json'},method='POST')
        assessments=[{'candidate_id':item['candidate_id'],'excluded':index==0,'reason':'cosine_similarity' if index==0 else None,
            'matched_vocab_id':'fixture-vocab' if index==0 else None,'matched_english':'fixture' if index==0 else None,
            'similarity':.9 if index==0 else None,'threshold':.82,'model':'fixture-embedding',
            'similar_matches':[{'vocab_id':'fixture-vocab','english':'fixture','similarity':.9}] if index==0 else [],
            'candidate_embedding':[1.0,0.0],'input_hash':f'hash-{index}'} for index,item in enumerate(created['items'])]
        with patch.object(self.http,'API_KEY','fixture-key'),patch.object(self.http,'compare_candidates',return_value={'items':assessments,'model':'fixture-embedding','usage':{'total_tokens':11},'exact_comparisons':2,'dataset_size':8}) as compare:
            with urlopen(req) as response:result=json.loads(response.read())
        compare.assert_called_once()
        self.assertEqual(result['exact_comparisons'],2)
        self.assertEqual(len(result['items']),2)
        self.assertNotIn('candidate_embedding',result['items'][0])
        self.assertEqual(result['items'][0]['similar_matches'][0]['english'],'fixture')
        with database.connect(self.db_path) as conn:
            jobs=conn.execute("SELECT job_type,status,completed_items FROM api_jobs WHERE job_id=?",(result['job_id'],)).fetchone()
            self.assertEqual(tuple(jobs),('candidate_similarity','completed',2))
            usage=conn.execute("SELECT operation,model,input_tokens FROM api_usage WHERE job_id=?",(result['job_id'],)).fetchall()
            self.assertEqual([tuple(row) for row in usage],[('candidate_similarity','fixture-embedding',11)])
            rows=conn.execute("SELECT english,excluded_reason,similarity,embedding_dimensions FROM candidates WHERE batch_id=?",(created['batch_id'],)).fetchall()
            states={row['english']:(row['excluded_reason'],row['similarity'],row['embedding_dimensions']) for row in rows}
            self.assertEqual(states,{'batch one':('cosine_similarity',.9,2),'batch two':(None,None,2)})

    def test_candidate_similarity_batch_failure_returns_http_error_and_marks_job_failed(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
        from urllib.request import Request
        batch_id=database.create_import_batch('vocabulary_list','retry me | meaning',path=self.db_path)
        database.add_candidates(batch_id,[{'english':'retry me','meaning':'meaning'}],path=self.db_path)
        created={'batch_id':batch_id,'items':database.list_candidates(batch_id,path=self.db_path)}
        body=json.dumps({'batch_id':created['batch_id'],'candidate_ids':[created['items'][0]['candidate_id']],'threshold':.8}).encode()
        req=Request(self.base+'/api/candidates/compare-batch',data=body,headers={'Content-Type':'application/json'},method='POST')
        with patch.object(self.http,'API_KEY','fixture-key'),patch.object(self.http,'compare_candidates',side_effect=RuntimeError('fixture embedding failure')):
            with self.assertRaises(HTTPError) as raised:urlopen(req)
        self.assertEqual(raised.exception.code,502)
        with database.connect(self.db_path) as conn:
            job=conn.execute("SELECT job_type,status,error FROM api_jobs WHERE job_type='candidate_similarity' ORDER BY created_at_utc DESC LIMIT 1").fetchone()
            self.assertEqual(job['status'],'failed')
            self.assertIn('fixture embedding failure',job['error'])

    def test_candidate_similarity_batch_database_lock_returns_retryable_http_response(self):
        import sqlite3
        from unittest.mock import patch
        from urllib.error import HTTPError
        from urllib.request import Request
        batch_id=database.create_import_batch('vocabulary_list','retry me | meaning',path=self.db_path)
        database.add_candidates(batch_id,[{'english':'retry me','meaning':'meaning'}],path=self.db_path)
        candidate=database.list_candidates(batch_id,path=self.db_path)[0]
        body=json.dumps({'batch_id':batch_id,'candidate_ids':[candidate['candidate_id']],'threshold':.8}).encode()
        req=Request(self.base+'/api/candidates/compare-batch',data=body,headers={'Content-Type':'application/json'},method='POST')
        compared={'items':[{'candidate_id':candidate['candidate_id'],'excluded':False,'reason':None,'matched_vocab_id':None,'matched_english':None,
            'similarity':None,'threshold':.8,'model':'fixture-model','candidate_embedding':[1.,0.],'input_hash':'fixture-hash'}],
            'model':'fixture-model','usage':{'total_tokens':2},'exact_comparisons':0,'dataset_size':0}
        with patch.object(self.http,'API_KEY','fixture-key'),patch.object(self.http,'compare_candidates',return_value=compared), \
             patch.object(database,'complete_candidate_similarity_job',side_effect=sqlite3.OperationalError('database is locked')):
            with self.assertRaises(HTTPError) as raised:urlopen(req)
        self.assertEqual(raised.exception.code,503)
        self.assertIn('retry',raised.exception.read().decode('utf-8').lower())
        with database.connect(self.db_path) as conn:
            job=conn.execute("SELECT status,error FROM api_jobs WHERE job_type='candidate_similarity' ORDER BY created_at_utc DESC LIMIT 1").fetchone()
            self.assertEqual(job['status'],'failed')
            self.assertIn('database is locked',job['error'])

    def test_overlap_generation_job_cost_usage_and_material_link_with_fixed_providers(self):
        from unittest.mock import patch
        from urllib.request import Request
        legacy_json_before=set(self.http.SAVE_DIR.glob('*.json'))
        material=database.create_material(title='fixture material',text_content='Take part.',path=self.db_path)
        request_body=json.dumps({'text':'Take part.','voice':'marin','style':'natural','material_id':material}).encode()
        req=Request(self.base+'/generate',data=request_body,headers={'Content-Type':'application/json'},method='POST')
        fake_audio=b'\0\0'*24000
        with patch.object(self.http,'generate_study_material',return_value=([{'english':'Take part.','japanese':'参加する','vocabulary':[]}],{'input_tokens':10,'output_tokens':5})), \
             patch.object(self.http,'realtime_speech',return_value=(fake_audio,'Take part.',{'input_tokens':10,'output_tokens':20})), \
             patch.object(self.http,'transcribe_audio_chunks',return_value=[{'word':'Take','start':0,'end':.3},{'word':'part','start':.3,'end':.6}]), \
             patch.object(self.http,'wav_to_mp3',return_value=b'fixture mp3'):
            with urlopen(req) as response:
                events=generation_stream(response)
                self.assertEqual(response.headers.get_content_type(),'application/x-ndjson')
        result=next(event['result'] for event in events if event['type']=='complete')
        progress=[event for event in events if event['type']=='progress']
        self.assertEqual([event['stage'] for event in progress],['preparing','text','audio','transcription','saving'])
        self.assertEqual([event['percent'] for event in progress],sorted(event['percent'] for event in progress))
        self.assertTrue(all(event['percent']<100 for event in progress))
        self.assertTrue(result['audio_file'].endswith('.mp3'))
        self.assertNotIn('subtitle_file',result)
        with database.connect(self.db_path) as conn:
            row=conn.execute('SELECT audio_path,json_path,status FROM materials WHERE material_id=?',(material,)).fetchone()
            self.assertEqual((row['audio_path'],row['json_path'],row['status']),(result['audio_file'],None,'ready'))
            job=conn.execute("SELECT status,completed_items FROM api_jobs WHERE job_type='overlap_generation'").fetchone()
            self.assertEqual((job['status'],job['completed_items']),('completed',3))
            self.assertEqual(conn.execute("SELECT count(*) FROM api_usage WHERE operation LIKE 'overlap_%'").fetchone()[0],3)
        payload=database.material_content(database.get_material(material,path=self.db_path))
        self.assertEqual((payload['blocks'][0]['english'],payload['words'][0]['word'],payload['spoken_text']),('Take part.','Take','Take part.'))
        self.assertEqual(set(self.http.SAVE_DIR.glob('*.json')),legacy_json_before,'new generation must not create subtitle JSON')

    def test_jobs_endpoint_exposes_failed_study_set_reason_and_missing_targets(self):
        job_id=database.create_api_job('study_set_generation',{'vocab_ids':['fixture-vocab']},2,path=self.db_path)
        database.update_api_job(job_id,status='failed',completed_items=1,
            error='\u6307\u5b9a\u8a9e\u5f59\u3092\u542b\u307e\u306a\u3044\u751f\u6210\u6587\u304c\u3042\u308a\u307e\u3059: rave about \uff5e',
            result={'missing_targets':['rave about \uff5e']},path=self.db_path)
        status,content_type,body=self.get('/api/jobs?id='+job_id)
        job=json.loads(body)
        self.assertEqual((status,content_type),(200,'application/json'))
        self.assertEqual(job['error'],'\u6307\u5b9a\u8a9e\u5f59\u3092\u542b\u307e\u306a\u3044\u751f\u6210\u6587\u304c\u3042\u308a\u307e\u3059: rave about \uff5e')
        self.assertEqual(job['result']['missing_targets'],['rave about \uff5e'])
        self.assertEqual((job['completed_items'],job['total_items']),(1,2))

    def test_dataset_sentence_generation_tracks_job_cost_and_reusable_conditions(self):
        import time
        from unittest.mock import patch
        from urllib.request import Request
        body=json.dumps({'category':'WorkAndCareer','direction':'en_to_ja','count':1,'include_unstudied':True,'mastery_status':'unlearned','difficulty':'','theme':'work','length':'medium','generation_mode':'article'}).encode()
        req=Request(self.base+'/api/study-set/plan',data=body,headers={'Content-Type':'application/json'},method='POST')
        with urlopen(req) as response: plan=json.loads(response.read())
        self.assertEqual(plan['selected_count'],1)
        self.assertEqual(json.loads(self.get('/api/study-set/last')[2])['conditions']['length'],'medium')
        self.assertEqual(json.loads(self.get('/api/study-set/last')[2])['conditions']['mastery_status'],'unlearned')
        self.assertEqual(json.loads(self.get('/api/study-set/last')[2])['conditions']['generation_mode'],'article')
        request_body=json.dumps({'vocab_ids':['fixture-vocab'],'difficulty':'B1','theme':'work','length':'medium','generation_mode':'article'}).encode()
        req=Request(self.base+'/api/study-set/generate',data=request_body,headers={'Content-Type':'application/json'},method='POST')
        def provider(endpoint,payload):
            self.assertEqual(payload['text']['format']['name'],'practice_article')
            return {'model':'fixture-model','output_text':json.dumps({'paragraphs':['The team took part in the trial.']}),'usage':{'input_tokens':20,'output_tokens':12}}
        worker=self.http.process_study_set_job
        with patch.object(self.http,'API_KEY','fixture-key'), patch.object(self.http,'process_study_set_job',side_effect=lambda job_id,key:worker(job_id,key,provider=provider)):
            with urlopen(req) as response: started=json.loads(response.read())
            self.assertEqual(started.get('job_id') is not None,True)
            deadline=time.time()+3
            while time.time()<deadline:
                job=database.get_api_job(started['job_id'],path=self.db_path)
                if job['status']!='running':break
                time.sleep(.01)
        self.assertEqual(job['status'],'completed')
        self.assertEqual(job['payload']['generation_mode'],'article')
        self.assertEqual(job['result']['generation_mode'],'article')
        self.assertEqual(job['result']['text'],'The team took part in the trial.')
        with database.connect(self.db_path) as conn:
            job=conn.execute("SELECT status,completed_items,result_json FROM api_jobs WHERE job_type='study_set_generation'").fetchone()
            self.assertEqual((job['status'],job['completed_items']),('completed',1))
            self.assertIn('request_count',job['result_json'])
            usage=conn.execute("SELECT model,input_tokens,output_tokens FROM api_usage WHERE operation='study_set_generation'").fetchone()
            self.assertEqual(tuple(usage),('fixture-model',20,12))

    def test_manual_overlap_text_and_transcript_are_saved_in_db_with_audio_only_file(self):
        from unittest.mock import patch
        from urllib.request import Request
        body=json.dumps({'text':'Take part in a trial.','voice':'marin','style':'natural'}).encode()
        legacy_json_before=set(self.http.SAVE_DIR.glob('*.json'))
        req=Request(self.base+'/generate',data=body,headers={'Content-Type':'application/json'},method='POST')
        fake_audio=b'\0\0'*24000
        with patch.object(self.http,'API_KEY','fixture-key'), \
             patch.object(self.http,'generate_study_material',return_value=([{'english':'Take part in a trial.','japanese':'試験に参加する','vocabulary':[]}],{'input_tokens':5,'output_tokens':3})), \
             patch.object(self.http,'realtime_speech',return_value=(fake_audio,'Take part in a trial.',{'input_tokens':5,'output_tokens':10})), \
             patch.object(self.http,'transcribe_audio_chunks',return_value=[{'word':'Take','start':0,'end':.2}]), \
             patch.object(self.http,'wav_to_mp3',return_value=b'fixture mp3'):
            with urlopen(req) as response: result=next(event['result'] for event in generation_stream(response) if event['type']=='complete')
        self.assertTrue(result['material_id'])
        self.assertTrue((self.http.SAVE_DIR / result['audio_file']).is_file())
        self.assertFalse(result.get('subtitle_file'))
        material=database.get_material(result['material_id'],path=self.db_path)
        content=database.material_content(material)
        self.assertEqual(material['text_content'],'Take part in a trial.')
        self.assertEqual(content['blocks'][0]['english'],'Take part in a trial.')
        self.assertEqual(set(self.http.SAVE_DIR.glob('*.json')),legacy_json_before)

    def test_overlap_endpoint_keeps_article_when_translation_notes_need_cleanup(self):
        from unittest.mock import patch
        from urllib.request import Request
        from english_overlap import app
        request_body=json.dumps({'text':'A comprehensive guide helps.','voice':'marin','style':'natural'}).encode()
        req=Request(self.base+'/generate',data=request_body,headers={'Content-Type':'application/json'},method='POST')
        generated={'items':[{'japanese':'案内 مرحباです。','vocabulary':[{'word':'guide','meaning':'案内 رائع'}]}]}
        response=json.dumps({'output_text':json.dumps(generated,ensure_ascii=False),'usage':{'input_tokens':4,'output_tokens':3}},ensure_ascii=False).encode('utf-8')
        fake_audio=b'\0\0'*24000
        with patch.object(self.http,'API_KEY','fixture-key'), \
             patch.object(app,'call_api',return_value=response), \
             patch.object(self.http,'realtime_speech',return_value=(fake_audio,'A comprehensive guide helps.',{'input_tokens':2,'output_tokens':3})), \
             patch.object(self.http,'transcribe_audio_chunks',return_value=[{'word':'guide','start':0.2,'end':0.5}]), \
             patch.object(self.http,'wav_to_mp3',return_value=b'fixture mp3'):
            with urlopen(req) as result_response: result=next(event['result'] for event in generation_stream(result_response) if event['type']=='complete')
        self.assertEqual(result['blocks'][0]['english'],'A comprehensive guide helps.')
        self.assertEqual(result['blocks'][0]['japanese'],'案内です。')
        self.assertEqual(result['blocks'][0]['vocabulary'],[{'word':'guide','meaning':'案内'}])
        material=database.get_material(result['material_id'],path=self.db_path)
        content=database.material_content(material)
        self.assertEqual(content['blocks'][0]['japanese'],'案内です。')
        with database.connect(self.db_path) as conn:
            row=conn.execute('SELECT text_content,audio_path,json_path FROM materials WHERE material_id=?',(result['material_id'],)).fetchone()
            self.assertEqual((row['text_content'],row['audio_path'],row['json_path']),('A comprehensive guide helps.',result['audio_file'],None))

    def test_material_summary_and_edits_use_database_only(self):
        from unittest.mock import patch
        from english_overlap import summaries
        material_id=self.saved_file_material_id()
        original_json=(self.http.SAVE_DIR/'english_overlap_fixture.json').read_bytes()
        with connect(self.db_path) as conn:
            conn.execute('UPDATE materials SET title=?,text_content=?,metadata_json=? WHERE material_id=?',
                         ('A news article','Japan parliament approved a new tax proposal.',json.dumps({'theme':'news'}),material_id))
            conn.execute('UPDATE materials SET content_json=? WHERE material_id=?',
                         (json.dumps({'spoken_text':'Japan parliament approved a new tax proposal.','blocks':[{'english':'Japan parliament approved a new tax proposal.'}],
                                      'words':[{'word':'Japan','start':0,'end':.2}],'audio_seconds':1.0,'audio_file':'english_overlap_fixture.mp3'}),material_id))
        captured={}
        response={'title':'Japan tax proposal','summary':'A summary of the parliamentary tax proposal.'}
        def fixture_request(endpoint,payload,api_key=None):
            captured.update({'endpoint':endpoint,'payload':payload,'api_key':api_key})
            return {'model':'fixture-model','output_text':json.dumps(response),'usage':{'input_tokens':25,'output_tokens':22}}
        with patch.object(self.http,'API_KEY','fixture-key'),patch.object(summaries,'request_json',side_effect=fixture_request):
            status,_,result=self.post_json('/api/materials/summarize',{'material_id':material_id})
        self.assertEqual(status,200)
        self.assertEqual(json.loads(captured['payload']['input']),{'text':'Japan parliament approved a new tax proposal.'})
        material=database.get_material(material_id,path=self.db_path)
        content=database.material_content(material)
        self.assertEqual((material['title'],material['text_content']),('Japan tax proposal','Japan parliament approved a new tax proposal.'))
        self.assertEqual((content['summary'],content['summary_model'],content['summary_prompt_version']),
                         (response['summary'],'fixture-model',summaries.SUMMARY_PROMPT_VERSION))
        self.assertEqual(json.loads(material['metadata_json'])['theme'],'news')
        self.assertEqual((result['title'],result['summary']),(response['title'],response['summary']))
        self.assertEqual((self.http.SAVE_DIR/'english_overlap_fixture.json').read_bytes(),original_json)
        edit_status,_,_=self.post_json('/api/materials/update',{'material_id':material_id,'title':'Edited news','text_content':'Edited news body.'})
        self.assertEqual(edit_status,200)
        edited=database.get_material(material_id,path=self.db_path)
        edited_content=database.material_content(edited)
        self.assertEqual((edited['title'],edited['text_content'],edited['audio_path']),('Edited news','Edited news body.',None))
        self.assertEqual((edited_content['blocks'],edited_content['words'],edited_content['transcript']),([],[],[]))
        self.assertNotIn('summary_model',edited_content)
        self.assertTrue((self.http.SAVE_DIR/'english_overlap_fixture.mp3').exists())
        self.assertEqual((self.http.SAVE_DIR/'english_overlap_fixture.json').read_bytes(),original_json)

    def test_material_summary_failures_leave_database_unchanged_and_database_only_is_eligible(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
        from english_overlap.openai_api import OpenAIError
        material_id=self.saved_file_material_id()
        before=database.get_material(material_id,path=self.db_path)
        with patch.object(self.http,'API_KEY',''),self.assertRaises(HTTPError) as missing:
            self.post_json('/api/materials/summarize',{'material_id':material_id})
        self.assertEqual(missing.exception.code,400)
        with patch.object(self.http,'API_KEY','fixture-key'),patch.object(self.http,'generate_material_summary',side_effect=OpenAIError('fixture failure')):
            with self.assertRaises(HTTPError) as failed:self.post_json('/api/materials/summarize',{'material_id':material_id})
        self.assertEqual(failed.exception.code,502)
        after=database.get_material(material_id,path=self.db_path)
        self.assertEqual((after['title'],after['text_content'],after['content_json']),(before['title'],before['text_content'],before['content_json']))
        database_only=database.create_material(title='Database only',text_content='Stored only in the database.',path=self.db_path)
        with patch.object(self.http,'API_KEY','fixture-key'),patch.object(self.http,'generate_material_summary',return_value={
            'title':'Database only title','summary':'Database only summary','model':'fixture-model','usage':{},'prompt_version':'fixture-v2'}):
            status,_,result=self.post_json('/api/materials/summarize',{'material_id':database_only})
        self.assertEqual(status,200)
        self.assertEqual(result['summary'],'Database only summary')
        self.assertEqual(database.material_content(database.get_material(database_only,path=self.db_path))['summary'],'Database only summary')

    def test_malformed_summary_response_records_usage_without_changing_existing_content(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
        from english_overlap.summaries import SummaryGenerationError
        material_id=self.saved_file_material_id()
        before=database.get_material(material_id,path=self.db_path)
        error=SummaryGenerationError('Malformed fixture',model='fixture-model',usage={'input_tokens':7,'output_tokens':2})
        with patch.object(self.http,'API_KEY','fixture-key'),patch.object(self.http,'generate_material_summary',side_effect=error):
            with self.assertRaises(HTTPError) as malformed:self.post_json('/api/materials/summarize',{'material_id':material_id})
        self.assertEqual(malformed.exception.code,502)
        self.assertEqual(database.get_material(material_id,path=self.db_path)['content_json'],before['content_json'])
        with connect(self.db_path) as conn:
            usage=conn.execute("SELECT model,input_tokens,output_tokens FROM api_usage WHERE operation='material_summary_generation'").fetchone()
            self.assertEqual(tuple(usage),('fixture-model',7,2))


if __name__ == '__main__':
    unittest.main()
