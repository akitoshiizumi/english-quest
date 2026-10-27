import json
import tempfile
import unittest
from pathlib import Path

from english_overlap import database
from english_overlap.app import parse_practice_text


class SentenceTests(unittest.TestCase):
    def test_abbreviation_boundaries_match_the_frontend_fixtures(self):
        fixtures=json.loads((Path(__file__).parent/'fixtures'/'sentences.json').read_text(encoding='utf-8'))
        for fixture in fixtures:
            with self.subTest(text=fixture['text']):
                blocks,_=parse_practice_text(fixture['text'])
                self.assertEqual([block['english'] for block in blocks],fixture['sentences'])


class PracticeOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'practice.sqlite3';database.migrate_database(self.path)
        self.session=database.create_study_session(path=self.path)
        with database.connect(self.path) as conn:
            for name in ['weak','medium','strong','unseen']:
                conn.execute('INSERT INTO vocab(vocab_id,english,japanese) VALUES (?,?,?)',(name,name,'意味'))
                conn.execute('INSERT INTO senses(vocab_id,sense_index,meaning) VALUES (?,0,?)',(name,'意味'))
        for name,ratings in [('weak',['again']*4),('medium',['known','again','again','again']),('strong',['known']*4)]:
            for index,rating in enumerate(ratings):
                database.record_vocabulary_answer(session_id=self.session,vocab_id=name,sense_id=None,direction='en_to_ja',rating=rating,duration_seconds=1,idempotency_key=f'{name}-{index}',path=self.path)

    def test_accuracy_score_and_counts_are_directional_and_zero_range_is_stable(self):
        items=database.list_practice_questions('en_to_ja',random_range=0,path=self.path)
        self.assertEqual([item['score'] for item in items],[0,0,25,100])
        medium=next(item for item in items if item['vocab_id']=='medium')
        self.assertEqual((medium['correct_count'],medium['answer_count'],medium['random_adjustment']),(1,4,0))
        opposite=database.list_practice_questions('ja_to_en',random_range=0,path=self.path)
        self.assertTrue(all(item['answer_count']==0 and item['score']==0 for item in opposite))

    def test_seed_is_repeatable_and_scores_all_eligible_words_before_limit(self):
        options=dict(random_range=80,random_seed='quest-123',path=self.path)
        all_items=database.list_practice_questions('en_to_ja',**options)
        self.assertEqual(all_items,database.list_practice_questions('en_to_ja',**options))
        self.assertEqual(all_items[:1],database.list_practice_questions('en_to_ja',limit=1,**options))
        self.assertEqual([item['score'] for item in all_items],sorted(item['score'] for item in all_items))
        for item in all_items:
            self.assertLessEqual(abs(item['random_adjustment']),80)
            self.assertAlmostEqual(item['score'],item['base_score']+item['random_adjustment'],places=3)
        other=database.list_practice_questions('en_to_ja',random_range=80,random_seed='different',path=self.path)
        self.assertNotEqual({item['vocab_id']:item['score'] for item in all_items},{item['vocab_id']:item['score'] for item in other})
        for invalid in [-1,101,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):database.list_practice_questions('en_to_ja',random_range=invalid,path=self.path)
