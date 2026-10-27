import json
import tempfile
import unittest
from pathlib import Path

from english_overlap import database
from english_overlap.database import connect, migrate_database
from english_overlap.http import process_study_set_job


class StudySetBackgroundJobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'fixture.sqlite3'
        self.old_path=database.database_path
        database.database_path=lambda:self.path
        migrate_database(self.path)
        with connect(self.path) as conn:
            for index in range(11):
                vocab_id=f'fixture-{index}'
                conn.execute('INSERT INTO vocab(vocab_id,english,japanese) VALUES (?,?,?)',(vocab_id,f'target{index}','fixture'))
                conn.execute('INSERT INTO senses(vocab_id,sense_index,meaning) VALUES (?,0,?)',(vocab_id,'fixture'))

    def tearDown(self):
        database.database_path=self.old_path
        self.temp.cleanup()

    @staticmethod
    def provider(endpoint,payload):
        targets=json.loads(payload['input'])['targets']
        return {'model':'fixture-model','output_text':json.dumps({'sentences':[item['english']+' matters.' for item in targets]}),'usage':{'input_tokens':len(targets)*2,'output_tokens':len(targets)}}

    def test_placeholder_coverage_failure_keeps_target_separate_from_error(self):
        with connect(self.path) as conn:
            conn.execute('INSERT INTO vocab(vocab_id,english,japanese) VALUES (?,?,?)',('rave','rave about \uff5e','to praise'))
            conn.execute('INSERT INTO senses(vocab_id,sense_index,meaning) VALUES (?,?,?)',('rave',0,'to praise'))
        job=database.create_api_job('study_set_generation',{'vocab_ids':['rave']},1,path=self.path)
        database.update_api_job(job,status='running',path=self.path)
        failed=process_study_set_job(job,'fixture-key',provider=lambda *args:{'output_text':json.dumps({'sentences':['They praise the cafe.']})})
        self.assertEqual(failed['status'],'failed')
        self.assertIn('rave about',failed['error'])
        self.assertEqual(failed['result']['missing_targets'],['rave about \uff5e'])
        self.assertNotEqual(failed['result']['missing_targets'],failed['error'])

    def test_retry_resumes_after_completed_passages_without_regenerating_or_rebilling_them(self):
        ids=[f'fixture-{index}' for index in range(11)]
        job=database.create_api_job('study_set_generation',{'vocab_ids':ids,'difficulty':'B1','theme':'fixture','length':'medium'},11,'fixture-model',path=self.path)
        database.update_api_job(job,status='running',path=self.path)
        calls=0
        def fail_after_one_passage(endpoint,payload):
            nonlocal calls
            calls+=1
            if calls==2:raise RuntimeError('fixture transient failure')
            return self.provider(endpoint,payload)
        failed=process_study_set_job(job,'fixture-key',provider=fail_after_one_passage)
        self.assertEqual((failed['status'],failed['completed_items']),('failed',10))
        self.assertEqual(len(failed['result']['groups']),1)
        with connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM api_usage WHERE job_id=?',(job,)).fetchone()[0],1)
            first_total=conn.execute('SELECT sum(input_tokens) FROM api_usage WHERE job_id=?',(job,)).fetchone()[0]
        resumed=process_study_set_job(job,'fixture-key',provider=self.provider)
        self.assertEqual((resumed['status'],resumed['completed_items']),('completed',11))
        self.assertEqual(len(resumed['result']['groups']),2)
        self.assertEqual(set(resumed['result']['used_vocab_ids']),set(ids))
        self.assertEqual(resumed['result']['request_count'],2)
        with connect(self.path) as conn:
            rows=conn.execute('SELECT input_tokens FROM api_usage WHERE job_id=? ORDER BY created_at_utc',(job,)).fetchall()
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]['input_tokens'],first_total)
            self.assertEqual(conn.execute('SELECT sum(input_tokens) FROM api_usage WHERE job_id=?',(job,)).fetchone()[0],22)


if __name__=='__main__':unittest.main()
