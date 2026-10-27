import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from english_overlap import database
from english_overlap.database import connect


class DatabaseMigrationTests(unittest.TestCase):
    def scalar(self, path: Path, sql: str):
        with closing(sqlite3.connect(path)) as conn:
            return conn.execute(sql).fetchone()[0]

    def make_legacy_db(self, folder: Path) -> Path:
        path = folder / "fixture.sqlite3"
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript("""
                CREATE TABLE vocab (
                    vocab_id TEXT PRIMARY KEY, english TEXT NOT NULL, japanese TEXT NOT NULL,
                    pos TEXT, example_sentence TEXT, genre_tags TEXT, tags TEXT,
                    cefr_level TEXT, created_at TEXT, updated_at TEXT
                );
                CREATE TABLE history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vocab_id TEXT NOT NULL REFERENCES vocab(vocab_id) ON DELETE CASCADE,
                    score REAL, result TEXT, appeared_count INTEGER DEFAULT 0,
                    correct_count INTEGER DEFAULT 0, appeared_time TEXT, session_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE similar (
                    vocab_id TEXT NOT NULL, similar_vocab_id TEXT NOT NULL,
                    similarity REAL NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(vocab_id, similar_vocab_id)
                );
                INSERT INTO vocab(vocab_id,english,japanese,pos,example_sentence,genre_tags,tags)
                  VALUES ('fixture-1','take part in','参加する','phrase','I took part in a trial.','WorkAndCareer','course-a'),
                         ('fixture-2','take part','参加','verb','','WorkAndCareer','course-a');
                INSERT INTO history(vocab_id,score,result,appeared_count,correct_count,appeared_time,session_id)
                  VALUES ('fixture-1',80,'OK',1,1,'2026-01-01 09:00','old-session');
                INSERT INTO similar(vocab_id,similar_vocab_id,similarity)
                  VALUES ('fixture-1','fixture-2',0.8);
            """)
        return path

    def test_migration_preserves_legacy_rows_and_backfills_categories_and_senses(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = self.make_legacy_db(Path(temp))
            version, backup_path = database.migrate_database(db_path)
            self.assertEqual(version, 7)
            self.assertTrue(backup_path.is_file())
            with database.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM vocab").fetchone()[0], 2)
                self.assertEqual(conn.execute("SELECT count(*) FROM history").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT count(*) FROM similar").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT meaning FROM senses WHERE vocab_id='fixture-1'").fetchone()[0], '参加する')
                self.assertEqual(conn.execute("SELECT count(*) FROM vocabulary_categories").fetchone()[0], 2)
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0], 7)
            self.assertEqual(self.scalar(backup_path, "SELECT count(*) FROM vocab"), 2)

    def test_migration_is_idempotent_and_does_not_make_new_backup_without_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = self.make_legacy_db(Path(temp))
            database.migrate_database(db_path)
            version, backup_path = database.migrate_database(db_path)
            self.assertEqual(version, 7)
            self.assertIsNone(backup_path)
            with database.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM senses").fetchone()[0], 2)

    def test_failed_migration_rolls_back_schema_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = self.make_legacy_db(Path(temp))
            old_migrations = database.MIGRATIONS
            def failing_migration(conn):
                conn.execute("CREATE TABLE should_rollback (id INTEGER)")
                raise RuntimeError("synthetic failure")
            database.MIGRATIONS = ((1, failing_migration),)
            try:
                with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                    database.migrate_database(db_path)
            finally:
                database.MIGRATIONS = old_migrations
            with closing(sqlite3.connect(db_path)) as conn:
                self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name='should_rollback'").fetchone())
                self.assertEqual(conn.execute("SELECT coalesce(max(version), 0) FROM schema_migrations").fetchone()[0], 0)

    def test_restore_is_atomic_and_preserves_pre_restore_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            db_path = self.make_legacy_db(folder)
            backup_path = database.backup_database(db_path, folder / "known-good.sqlite3")
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("DELETE FROM vocab")
                conn.commit()
            database.restore_database(backup_path, db_path)
            with database.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM vocab").fetchone()[0], 2)
            copies = list(folder.glob("fixture.backup-*.sqlite3"))
            self.assertEqual(len(copies), 1)
            self.assertEqual(self.scalar(copies[0], "SELECT count(*) FROM vocab"), 0)

    def test_database_status_and_backup_listing_report_only_same_database_backups(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); db_path=self.make_legacy_db(folder); database.migrate_database(db_path)
            self.assertEqual(database.database_status(db_path)['integrity'],'ok')
            self.assertEqual(database.database_status(db_path)['schema_version'],7)
            backup=database.backup_database(db_path)
            self.assertIn(backup.name,[item['name'] for item in database.list_database_backups(db_path)])
            other=folder/'another.backup-example.sqlite3';other.touch()
            self.assertNotIn(other.name,[item['name'] for item in database.list_database_backups(db_path)])

    def test_vocabulary_events_are_directional_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = self.make_legacy_db(Path(temp))
            database.migrate_database(db_path)
            session_id = database.create_study_session(path=db_path)
            sense_id = self.scalar(db_path, "SELECT sense_id FROM senses WHERE vocab_id='fixture-1'")
            arguments = dict(session_id=session_id, vocab_id="fixture-1", sense_id=sense_id,
                             direction="en_to_ja", rating="again", duration_seconds=2.5,
                             idempotency_key="answer-once", path=db_path)
            self.assertTrue(database.record_vocabulary_answer(**arguments))
            self.assertFalse(database.record_vocabulary_answer(**arguments))
            with database.connect(db_path) as conn:
                row = conn.execute("SELECT direction,rating,duration_seconds FROM study_events").fetchone()
                self.assertEqual(tuple(row), ("en_to_ja", "again", 2.5))
                self.assertEqual(conn.execute("SELECT count(*) FROM study_events").fetchone()[0], 1)

    def test_candidate_selection_requires_meaning_and_deduplicates_normalized_headwords(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.make_legacy_db(Path(temp));database.migrate_database(path)
            batch=database.create_import_batch('vocabulary_list','take part / comprehensive / outline',path=path)
            ids=database.add_candidates(batch,[
                {'english':'TAKE   PART','meaning':'参加する','selected':True},
                {'english':'comprehensive','meaning':'包括的','selected':True},
                {'english':'COMPREHENSIVE','meaning':'包括的な','selected':True},
                {'english':'similar-word','meaning':'類似語','selected':True},
                {'english':'outline','meaning':'','selected':True}],path=path)
            similar=next(item for item in database.list_candidates(batch,path=path) if item['english']=='similar-word')
            database.update_candidate_assessment(similar['candidate_id'],{'reason':'cosine_similarity','matched_vocab_id':'fixture-1','similarity':0.9},path=path)
            created=database.select_candidates(batch,ids,path=path)
            self.assertEqual(len(created),1)
            self.assertEqual(database.select_candidates(batch,ids,path=path),[])
            candidates=database.list_candidates(batch,path=path)
            by_word={item['english']:item for item in candidates}
            self.assertEqual(by_word['TAKE   PART']['excluded_reason'],'exact_match')
            self.assertEqual(by_word['COMPREHENSIVE']['excluded_reason'],'duplicate_candidate')
            self.assertEqual(by_word['comprehensive']['created_vocab_id'],created[0])
            self.assertEqual(by_word['similar-word']['excluded_reason'],'cosine_similarity')
            self.assertEqual(by_word['outline']['excluded_reason'],'meaning_required')
            with database.connect(path) as conn:
                self.assertEqual(conn.execute("SELECT meaning FROM senses WHERE vocab_id=?",(created[0],)).fetchone()[0],'包括的')
                self.assertEqual(conn.execute("SELECT count(*) FROM vocab WHERE lower(english) LIKE 'comprehensive%' ").fetchone()[0],1)

    def test_manual_difficulty_is_not_overwritten_by_automatic_assessment(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.make_legacy_db(Path(temp));database.migrate_database(path)
            with database.connect(path) as conn: sense=conn.execute("SELECT sense_id FROM senses WHERE vocab_id='fixture-1'").fetchone()[0]
            database.update_difficulty(sense,'B2','manual correction',manual=True,path=path)
            database.update_difficulty(sense,'A2','automatic',model='gpt-6-luna',path=path)
            with database.connect(path) as conn:
                row=conn.execute("SELECT difficulty_level,difficulty_evidence,difficulty_manual FROM senses WHERE sense_id=?",(sense,)).fetchone()
                self.assertEqual(tuple(row),('B2','manual correction',1))

    def test_api_jobs_can_pause_resume_and_record_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.make_legacy_db(Path(temp));database.migrate_database(path)
            job=database.create_api_job('difficulty',{'sense_ids':[1,2]},2,'gpt-6-luna',path=path)
            database.update_api_job(job,status='running',completed_items=1,path=path)
            database.update_api_job(job,status='paused',completed_items=1,path=path)
            database.update_api_job(job,status='running',completed_items=2,result={'done':[1,2]},path=path)
            database.add_api_usage(operation='difficulty',model='gpt-6-luna',input_tokens=30,output_tokens=8,estimated_usd=.000007,job_id=job,path=path)
            with database.connect(path) as conn:
                state=conn.execute("SELECT status,completed_items,result_json FROM api_jobs WHERE job_id=?",(job,)).fetchone()
                self.assertEqual((state['status'],state['completed_items']),('running',2))
                self.assertIn('done',state['result_json'])
                self.assertEqual(conn.execute("SELECT count(*) FROM api_usage WHERE job_id=?",(job,)).fetchone()[0],1)

    def test_due_only_practice_uses_directional_latest_history_and_due_order(self):
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as temp:
            path=self.make_legacy_db(Path(temp));database.migrate_database(path)
            session=database.create_study_session(path=path)
            with database.connect(path) as conn:
                conn.execute("INSERT INTO categories(category_id,name) VALUES ('Other','Other')")
                conn.execute("DELETE FROM vocabulary_categories WHERE vocab_id='fixture-2'")
                conn.execute("INSERT INTO vocabulary_categories(vocab_id,category_id) VALUES ('fixture-2','Other')")
                conn.execute("UPDATE senses SET difficulty_level='B1' WHERE vocab_id='fixture-1'")
                conn.execute("UPDATE senses SET difficulty_level='A2' WHERE vocab_id='fixture-2'")
                conn.executemany("INSERT INTO study_events(event_id,session_id,event_type,vocab_id,direction,rating,duration_seconds,occurred_at_utc) VALUES (?,?,'vocabulary_answer',?,?,?,1,?)",[
                    ('old-due',session,'fixture-1','en_to_ja','again','2026-10-18T15:00:00+00:00'),
                    ('recent-due',session,'fixture-2','en_to_ja','known','2026-10-18T15:00:00+00:00'),
                    ('not-due',session,'fixture-1','ja_to_en','known','2026-10-20T15:00:00+00:00')])
            now=datetime(2026,10,22,0,0,tzinfo=timezone.utc)
            due=database.list_practice_questions('en_to_ja',due_only=True,as_of=now,path=path)
            self.assertEqual([row['vocab_id'] for row in due],['fixture-1','fixture-2'])
            self.assertEqual(database.list_practice_questions('ja_to_en',due_only=True,as_of=now,path=path),[])
            self.assertEqual([row['vocab_id'] for row in database.list_practice_questions('en_to_ja',category='WorkAndCareer',due_only=True,as_of=now,path=path)],['fixture-1'])
            self.assertEqual([row['vocab_id'] for row in database.list_practice_questions('en_to_ja',difficulty='B1',due_only=True,as_of=now,path=path)],['fixture-1'])
            self.assertEqual(database.list_practice_questions('en_to_ja',due_only=True,limit=1,as_of=now,path=path)[0]['vocab_id'],'fixture-1')
            self.assertEqual(len(database.list_practice_questions('en_to_ja',as_of=now,path=path)),2)
            with database.connect(path) as conn:
                conn.execute("INSERT INTO study_events(event_id,session_id,event_type,vocab_id,direction,rating,duration_seconds,occurred_at_utc) VALUES ('reschedule',?,'vocabulary_answer','fixture-1','en_to_ja','known',1,'2026-10-21T15:00:00+00:00')",(session,))
            due=database.list_practice_questions('en_to_ja',due_only=True,as_of=now,path=path)
            self.assertEqual([row['vocab_id'] for row in due],['fixture-2'])

    def test_tokyo_boundary_due_rules_and_overlap_activity_statistics(self):
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as temp:
            path=self.make_legacy_db(Path(temp));database.migrate_database(path)
            session=database.create_study_session(path=path)
            with database.connect(path) as conn:
                conn.execute("INSERT INTO study_events(event_id,session_id,event_type,vocab_id,direction,rating,duration_seconds,occurred_at_utc) VALUES ('due-again',?,'vocabulary_answer','fixture-1','en_to_ja','again',2,'2026-10-20T14:59:00+00:00')",(session,))
                conn.execute("INSERT INTO study_events(event_id,session_id,event_type,vocab_id,direction,rating,duration_seconds,occurred_at_utc) VALUES ('not-due-known',?,'vocabulary_answer','fixture-2','en_to_ja','known',3,'2026-10-20T14:59:00+00:00')",(session,))
            overlap_session=database.create_study_session('overlap',path=path)
            self.assertTrue(database.record_overlap_activity(session_id=overlap_session,material_id='fixture-material',duration_seconds=15,idempotency_key='play-segment',path=path))
            self.assertFalse(database.record_overlap_activity(session_id=overlap_session,material_id='fixture-material',duration_seconds=15,idempotency_key='play-segment',path=path))
            with database.connect(path) as conn:
                conn.execute("UPDATE study_events SET occurred_at_utc='2026-10-24T14:59:00+00:00' WHERE idempotency_key='play-segment'")
            stats=database.review_and_statistics(path=path,now=datetime(2026,10,21,14,59,tzinfo=timezone.utc))
            self.assertEqual(stats['today_tokyo'],'2026-10-21')
            self.assertEqual(stats['due_count'],1)
            self.assertEqual(stats['due_items'][0]['english'],'take part in')
            self.assertEqual(stats['due_items'][0]['due_date'],'2026-10-21')
            self.assertEqual(stats['active_seconds'],20)
            self.assertEqual(stats['vocabulary_active_seconds'],5)
            self.assertEqual(stats['overlap_active_seconds'],15)
            self.assertEqual(stats['database_stats']['vocabulary_count'],2)
            self.assertEqual(stats['database_stats']['active_vocabulary_count'],2)
            self.assertEqual(stats['database_stats']['attempt_count'],2)
            self.assertEqual(stats['database_stats']['known_count'],1)
            self.assertEqual(stats['database_stats']['again_count'],1)
            self.assertEqual(stats['database_stats']['accuracy'],0.5)
            per_word={item['vocab_id']:item for item in stats['vocabulary_performance']}
            self.assertEqual((per_word['fixture-1']['attempts'],per_word['fixture-1']['again'],per_word['fixture-1']['known_rate']),(1,1,0.0))
            self.assertEqual((per_word['fixture-2']['attempts'],per_word['fixture-2']['known'],per_word['fixture-2']['known_rate']),(1,1,1.0))
            self.assertEqual(stats['daily']['2026-10-20']['vocabulary_active_seconds'],5)
            self.assertEqual(stats['daily']['2026-10-24']['overlap_active_seconds'],15)
            short=database.review_and_statistics(path=path,now=datetime(2026,10,21,14,59,tzinfo=timezone.utc),days=2)
            self.assertEqual(short['vocabulary_active_seconds'],5)
            self.assertEqual(short['overlap_active_seconds'],0)
            self.assertEqual(list(short['daily']),['2026-10-20'])
            empty=database.review_and_statistics(path=path,now=datetime(2026,10,21,14,59,tzinfo=timezone.utc),days=1)
            self.assertEqual((empty['vocabulary_active_seconds'],empty['overlap_active_seconds'],empty['active_seconds'],empty['daily']),(0,0,0,{}))
            self.assertEqual(stats['legacy_history_count_excluded'],1)

    def test_cumulative_learning_goals_count_recorded_overlap_time_and_distinct_vocabularies(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.make_legacy_db(Path(temp));database.migrate_database(path)
            self.assertEqual(database.learning_goals_status(path=path),{'goals':{'overlap_hours':None,'vocabulary_count':None},'overlap_seconds':0.0,'learned_vocabulary_count':0})
            database.set_learning_goals(overlap_hours=2.5,vocabulary_count=20,path=path)
            vocabulary_session=database.create_study_session(path=path)
            database.record_vocabulary_answer(session_id=vocabulary_session,vocab_id='fixture-1',sense_id=None,direction='en_to_ja',rating='again',duration_seconds=2,idempotency_key='goal-answer-1',path=path)
            database.record_vocabulary_answer(session_id=vocabulary_session,vocab_id='fixture-1',sense_id=None,direction='en_to_ja',rating='known',duration_seconds=2,idempotency_key='goal-answer-2',path=path)
            database.record_vocabulary_answer(session_id=vocabulary_session,vocab_id='fixture-2',sense_id=None,direction='ja_to_en',rating='known',duration_seconds=2,idempotency_key='goal-answer-3',path=path)
            overlap_session=database.create_study_session('overlap',path=path)
            database.record_overlap_activity(session_id=overlap_session,material_id='fixture-material',duration_seconds=3600,idempotency_key='goal-overlap-1',path=path)
            database.record_overlap_activity(session_id=overlap_session,material_id='fixture-material',duration_seconds=1800,idempotency_key='goal-overlap-2',path=path)
            status=database.learning_goals_status(path=path)
            self.assertEqual(status['goals'],{'overlap_hours':2.5,'vocabulary_count':20})
            self.assertEqual(status['overlap_seconds'],5400)
            self.assertEqual(status['learned_vocabulary_count'],2)
            for overlap,vocabulary in [(0,20),(10001,20),(1.0,1.5)]:
                with self.assertRaises(ValueError):database.set_learning_goals(overlap_hours=overlap,vocabulary_count=vocabulary,path=path)
            self.assertEqual(database.learning_goals_status(path=path)['goals'],{'overlap_hours':2.5,'vocabulary_count':20})
            database.set_learning_goals(overlap_hours=None,vocabulary_count=None,path=path)
            self.assertEqual(database.learning_goals_status(path=path)['goals'],{'overlap_hours':None,'vocabulary_count':None})

    def test_legacy_material_import_preserves_existing_row_and_never_reimports_mutated_source(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path=Path(temp)/'fixture.sqlite3'
            database.migrate_database(db_path)
            with connect(db_path) as conn:conn.execute("INSERT INTO vocab(vocab_id,english,japanese) VALUES ('fixture-1','fixture','fixture')")
            material_id=database.create_material(title='Stale title',text_content='Stale body.',metadata={'theme':'news'},path=db_path)
            with connect(db_path) as conn:
                conn.execute("UPDATE materials SET json_path=?,status='archived' WHERE material_id=?",('english_overlap_news.json',material_id))
                conn.execute("INSERT INTO material_vocabulary(material_id,vocab_id) VALUES (?,?)",(material_id,'fixture-1'))
            source={'file':'english_overlap_news.json','sha256':'a'*64,'data':{
                'title':'News title','text':'A parliamentary news article.','created_at':'2026-10-25T00:00:00+00:00',
                'audio_file':'english_overlap_news.mp3','spoken_text':'A parliamentary news article.',
                'blocks':[{'english':'A parliamentary news article.'}],'words':[{'word':'parliamentary','start':0,'end':0.5}],
                'summary':'News summary','summary_model':'fixture-model','summary_prompt_version':'v2',
                'summary_generated_at_utc':'2026-10-25T00:00:00+00:00','voice':'marin','style':'natural',
                'cost':{'total_usd':0.01},'audio_seconds':2.2,'word_count':4,'character_count':31}}
            result=database.import_legacy_material(source,path=db_path)
            self.assertTrue(result['imported'])
            material=database.get_material(material_id,path=db_path)
            content=database.material_content(material)
            self.assertEqual((material['title'],material['text_content'],material['audio_path'],material['json_path'],material['status']),
                             ('News title','A parliamentary news article.','english_overlap_news.mp3',None,'archived'))
            self.assertEqual((content['summary'],content['summary_model'],content['blocks'],content['words'],content['voice']),
                             ('News summary','fixture-model',[{'english':'A parliamentary news article.'}],[{'word':'parliamentary','start':0,'end':0.5}],'marin'))
            self.assertEqual(json.loads(material['metadata_json']),{'theme':'news'})
            with connect(db_path) as conn:self.assertEqual(conn.execute('SELECT count(*) FROM material_vocabulary WHERE material_id=?',(material_id,)).fetchone()[0],1)
            mutated={**source,'sha256':'b'*64,'data':{**source['data'],'title':'Externally changed title'}}
            again=database.import_legacy_material(mutated,path=db_path)
            self.assertTrue(again['already_imported'])
            self.assertEqual(database.get_material(material_id,path=db_path)['title'],'News title')
            self.assertEqual(database.imported_material_source_names(path=db_path),{'english_overlap_news.json'})

    def test_orphan_legacy_material_import_is_idempotent_and_invalid_content_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path=Path(temp)/'fixture.sqlite3';database.migrate_database(db_path)
            item={'file':'english_overlap_orphan.json','sha256':'c'*64,'data':{'text':'An orphan material.'}}
            result=database.import_legacy_material(item,path=db_path)
            self.assertTrue(result['imported'])
            material=database.get_material(result['material_id'],path=db_path)
            self.assertEqual((material['material_type'],material['text_content'],material['audio_path']),('overlap','An orphan material.',None))
            self.assertFalse(database.import_legacy_material(item,path=db_path)['imported'])
            with self.assertRaisesRegex(ValueError,'no article text'):
                database.import_legacy_material({'file':'english_overlap_invalid.json','sha256':'d'*64,'data':{'text':'  '}},path=db_path)

if __name__ == "__main__":
    unittest.main()
