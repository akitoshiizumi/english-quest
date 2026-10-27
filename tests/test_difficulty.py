import json
import tempfile
import unittest
from pathlib import Path

from english_overlap import database
from english_overlap.database import connect, migrate_database
from english_overlap.difficulty import MAX_OUTPUT_TOKENS, assess_sense, process_difficulty_job


class DifficultyJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'fixture.sqlite3'
        self.old_path = database.database_path
        database.database_path = lambda: self.path
        migrate_database(self.path)
        with connect(self.path) as conn:
            conn.execute("INSERT INTO vocab(vocab_id,english,japanese) VALUES ('auto','substantial','かなりの')")
            conn.execute("INSERT INTO senses(vocab_id,sense_index,meaning) VALUES ('auto',0,'かなりの')")
            conn.execute("INSERT INTO vocab(vocab_id,english,japanese) VALUES ('manual','routine','日課')")
            conn.execute("INSERT INTO senses(vocab_id,sense_index,meaning,difficulty_level,difficulty_manual) VALUES ('manual',0,'日課','B1',1)")

    def tearDown(self):
        database.database_path = self.old_path
        self.temp.cleanup()

    def test_assessment_uses_larger_output_limit_and_describes_incomplete_or_malformed_json(self):
        item=database.senses_for_difficulty(limit=1)[0]
        seen=[]
        def complete_provider(endpoint,payload,*,api_key):
            seen.append(payload['max_output_tokens'])
            return {'status':'completed','model':'fixture-model','output_text':json.dumps({'level':'B2','evidence':'fixture'})}
        assessment,_=assess_sense(item,api_key='fixture-key',provider=complete_provider)
        self.assertEqual(assessment['level'],'B2')
        self.assertEqual(seen,[MAX_OUTPUT_TOKENS])
        with self.assertRaisesRegex(ValueError,'incomplete \\(max_output_tokens\\)'):
            assess_sense(item,api_key='fixture-key',provider=lambda *args,**kwargs:{'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output_text':'{"level":"B2","evidence":"trunc'})
        with self.assertRaisesRegex(ValueError,'incomplete or invalid JSON'):
            assess_sense(item,api_key='fixture-key',provider=lambda *args,**kwargs:{'status':'completed','output_text':'{"level":"B2","evidence":"trunc'})
        with self.assertRaisesRegex(ValueError,'expected assessment fields'):
            assess_sense(item,api_key='fixture-key',provider=lambda *args,**kwargs:{'status':'completed','output_text':'{"level":"D1","evidence":"fixture"}'})

    def test_failed_truncated_sense_resumes_without_repeating_completed_assessments(self):
        with connect(self.path) as conn:
            conn.execute("INSERT INTO vocab(vocab_id,english,japanese) VALUES ('second-auto','steady','安定')")
            conn.execute("INSERT INTO senses(vocab_id,sense_index,meaning) VALUES ('second-auto',0,'安定')")
        items=database.senses_for_difficulty(limit=100)
        self.assertEqual(len(items),2)
        ids=[item['sense_id'] for item in items]
        job=database.create_api_job('automatic_difficulty_assessment',{'automatic':True,'sense_ids':ids},2,'fixture-model',path=self.path)
        database.update_api_job(job,status='running',path=self.path)
        calls=[]
        def truncated_on_second(endpoint,payload,*,api_key):
            calls.append(payload['input'])
            if len(calls)==1:
                return {'status':'completed','model':'fixture-model','output_text':json.dumps({'level':'B2','evidence':'completed fixture'}),'usage':{'input_tokens':10,'output_tokens':5}}
            return {'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'model':'fixture-model','output_text':'{"level":"B2","evidence":"trunc','usage':{'input_tokens':100,'output_tokens':160}}
        failed=process_difficulty_job(job,api_key='fixture-key',provider=truncated_on_second,path=self.path)
        self.assertEqual((failed['status'],failed['completed_items']),('failed',1))
        with connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM api_usage WHERE job_id=?',(job,)).fetchone()[0],2)
            failed_english=json.loads(calls[1])['english']
            failed_level=conn.execute('SELECT s.difficulty_level FROM senses s JOIN vocab v USING(vocab_id) WHERE v.english=?',(failed_english,)).fetchone()[0]
            self.assertIsNone(failed_level,'truncated JSON must not be saved as an assessment')
        database.update_api_job(job,status='running',path=self.path)
        resumed=process_difficulty_job(job,api_key='fixture-key',provider=lambda *args,**kwargs:{'status':'completed','model':'fixture-model','output_text':json.dumps({'level':'C1','evidence':'resumed fixture'}),'usage':{'input_tokens':8,'output_tokens':6}},path=self.path)
        self.assertEqual((resumed['status'],resumed['completed_items']),('completed',2))
        self.assertEqual(len(calls),2)
        with connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM api_usage WHERE job_id=?',(job,)).fetchone()[0],3)

    def test_job_assesses_missing_senses_preserves_manual_and_records_usage(self):
        items = database.senses_for_difficulty(limit=100)
        self.assertEqual(len(items), 1)
        job = database.create_api_job('difficulty_assessment', {'sense_ids': [items[0]['sense_id']]}, 1, 'fixture-model')
        database.update_api_job(job, status='running')

        def provider(endpoint, payload, *, api_key):
            self.assertEqual(endpoint, 'responses')
            self.assertEqual(api_key, 'fixture-key')
            return {'model': 'fixture-model', 'output_text': json.dumps({'level':'B2','evidence':'Fixture rationale'}), 'usage': {'input_tokens':10,'output_tokens':5}}

        result = process_difficulty_job(job, api_key='fixture-key', provider=provider)
        self.assertEqual((result['status'], result['completed_items']), ('completed', 1))
        with connect(self.path) as conn:
            levels = {row['english']: (row['difficulty_level'], row['difficulty_manual']) for row in conn.execute('SELECT v.english,s.difficulty_level,s.difficulty_manual FROM vocab v JOIN senses s USING(vocab_id)')}
            self.assertEqual(levels, {'substantial': ('B2', 0), 'routine': ('B1', 1)})
            usage = conn.execute('SELECT operation,model,input_tokens,output_tokens FROM api_usage').fetchone()
            self.assertEqual(tuple(usage), ('difficulty_assessment','fixture-model',10,5))

    def test_paused_job_returns_before_provider_call(self):
        item = database.senses_for_difficulty(limit=1)[0]
        job = database.create_api_job('difficulty_assessment', {'sense_ids':[item['sense_id']]}, 1, 'fixture-model')
        database.update_api_job(job,status='paused')
        result = process_difficulty_job(job,api_key='fixture-key',provider=lambda *args,**kwargs:self.fail('provider must not run while paused'))
        self.assertEqual(result['status'],'paused')

    def test_automatic_job_reserves_daily_budget_and_resumes_failure_checkpoint(self):
        item=database.senses_for_difficulty(limit=1)[0]
        database.set_setting('automatic_difficulty',{'enabled':True,'per_run_limit':1,'daily_budget_usd':0.05},path=self.path)
        job=database.create_api_job('automatic_difficulty_assessment',{'automatic':True,'sense_ids':[item['sense_id']]},1,'fixture-model',path=self.path)
        database.update_api_job(job,status='running',path=self.path)
        failed=process_difficulty_job(job,api_key='fixture-key',provider=lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError('fixture rate limit')),path=self.path)
        self.assertEqual(failed['status'],'failed')
        self.assertEqual(failed['completed_items'],0)
        database.update_api_job(job,status='running',path=self.path)
        def provider(endpoint,payload,*,api_key):
            self.assertEqual(payload['max_output_tokens'],MAX_OUTPUT_TOKENS)
            return {'model':'fixture-model','output_text':json.dumps({'level':'B2','evidence':'Fixture rationale'}),'usage':{'input_tokens':100,'output_tokens':40}}
        completed=process_difficulty_job(job,api_key='fixture-key',provider=provider,path=self.path)
        self.assertEqual((completed['status'],completed['completed_items']),('completed',1))
        with connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM api_usage').fetchone()[0],1)

    def test_automatic_job_pauses_before_provider_when_daily_budget_would_be_exceeded(self):
        item=database.senses_for_difficulty(limit=1)[0]
        database.set_setting('automatic_difficulty',{'enabled':True,'per_run_limit':1,'daily_budget_usd':0.000001},path=self.path)
        job=database.create_api_job('automatic_difficulty_assessment',{'automatic':True,'sense_ids':[item['sense_id']]},1,'fixture-model',path=self.path)
        database.update_api_job(job,status='running',path=self.path)
        result=process_difficulty_job(job,api_key='fixture-key',provider=lambda *args,**kwargs:self.fail('daily budget should stop before the API call'),path=self.path)
        self.assertEqual(result['status'],'paused')
        self.assertEqual(result['result']['pause_reason'],'daily_budget')


if __name__ == '__main__':
    unittest.main()
