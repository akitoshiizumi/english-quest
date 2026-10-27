import json
import math
import random
import tempfile
import unittest
from pathlib import Path

from english_overlap import database
from english_overlap.embeddings import INPUT_VERSION, compare_candidate, compare_candidates, embedding_hash, index_missing, make_embedding_text, save_embedding


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'db.sqlite3'
        database.migrate_database(self.path)
        with database.connect(self.path) as conn:
            conn.execute("INSERT INTO vocab(vocab_id,english,japanese) VALUES ('v1','comprehensive','包括的')")
            conn.execute("INSERT INTO senses(vocab_id,sense_index,meaning) VALUES ('v1',0,'包括的')")
    def tearDown(self):self.temp.cleanup()

    def test_index_uses_cache_metadata_and_cosine_threshold(self):
        def fake_provider(endpoint,payload,api_key):
            self.assertEqual(endpoint,'embeddings');self.assertEqual(api_key,'fixture-key')
            return {'model':'text-embedding-3-small','data':[{'embedding':[1.0,0.0]}],'usage':{'total_tokens':12}}
        result=index_missing(api_key='fixture-key',limit=100,path=self.path,provider=fake_provider)
        self.assertEqual((result['indexed'],result['remaining']),(1,0))
        candidate={'candidate_id':'c1','english':'all-inclusive','meaning':'包括的'}
        assessment=compare_candidate(candidate,api_key='fixture-key',threshold=.8,path=self.path,
            provider=lambda *args,**kwargs:{'model':'text-embedding-3-small','data':[{'embedding':[.8,.6]}]})
        self.assertTrue(assessment['excluded'])
        self.assertEqual(assessment['reason'],'cosine_similarity')
        self.assertEqual(assessment['matched_vocab_id'],'v1')
        self.assertAlmostEqual(assessment['similarity'],.8)

    def test_repeated_batches_index_all_missing_senses(self):
        with database.connect(self.path) as conn:
            conn.execute("UPDATE senses SET meaning='' WHERE vocab_id='v1'")
            conn.executemany("INSERT INTO vocab(vocab_id,english,japanese) VALUES (?,?,'meaning')",
                [(f'batch-{index:03}',f'word-{index:03}') for index in range(205)])
            conn.executemany("INSERT INTO senses(vocab_id,sense_index,meaning) VALUES (?,0,'meaning')",
                [(f'batch-{index:03}',) for index in range(205)])
        batch_sizes=[]
        def fake_provider(endpoint,payload,api_key):
            batch_sizes.append(len(payload['input']))
            return {'model':'text-embedding-3-small','data':[{'embedding':[1.0,0.0]} for _ in payload['input']]}
        totals=[]
        while True:
            result=index_missing(api_key='fixture-key',limit=100,path=self.path,provider=fake_provider)
            totals.append(result['indexed'])
            if result['remaining']==0:break
            self.assertGreater(result['indexed'],0)
        self.assertEqual(batch_sizes,[100,100,5])
        self.assertEqual(totals,[100,100,5])
        with database.connect(self.path) as conn:
            count=conn.execute("SELECT count(*) FROM embeddings WHERE vocab_id LIKE 'batch-%'").fetchone()[0]
        self.assertEqual(count,205)

    def test_batch_comparison_embeds_nonexact_candidates_once_and_keeps_threshold_semantics(self):
        with database.connect(self.path) as conn:
            sense_id=conn.execute("SELECT sense_id FROM senses WHERE vocab_id='v1'").fetchone()[0]
        save_embedding('v1',sense_id,make_embedding_text('comprehensive','meaning'),[1.0,0.0],'fixture-model',path=self.path)
        calls=[]
        def fake_provider(endpoint,payload,api_key):
            calls.append(payload)
            return {'model':'fixture-model','data':[{'index':0,'embedding':[.8,.6]},{'index':1,'embedding':[0.,1.]}],'usage':{'total_tokens':9}}
        result=compare_candidates([
            {'candidate_id':'exact','english':' COMPREHENSIVE ','meaning':'meaning'},
            {'candidate_id':'boundary','english':'all-inclusive','meaning':'meaning'},
            {'candidate_id':'other','english':'guide','meaning':'meaning'}],
            api_key='fixture-key',threshold=.8,path=self.path,provider=fake_provider)
        self.assertEqual(len(calls),1)
        self.assertEqual(len(calls[0]['input']),2)
        self.assertEqual(result['usage']['total_tokens'],9)
        self.assertEqual([item['reason'] for item in result['items']],['exact_match','cosine_similarity',None])
        self.assertAlmostEqual(result['items'][1]['similarity'],.8)
        self.assertFalse(result['items'][2]['excluded'])

    def test_batch_comparison_returns_exact_nearest_three_distinct_words_below_threshold(self):
        words=[('near-a','first meaning',[.9,math.sqrt(1-.9**2),0.,0.]),
               ('near-b','second meaning',[.8,0.,.6,0.]),
               ('near-c','third meaning',[.8,0.,0.,.6]),
               ('near-d','fourth meaning',[.7,math.sqrt(1-.7**2),0.,0.])]
        with database.connect(self.path) as conn:
            for english,meaning,_ in words:
                conn.execute("INSERT INTO vocab(vocab_id,english,japanese) VALUES (?,?,?)",(english,english,meaning))
                conn.execute("INSERT INTO senses(vocab_id,sense_index,meaning) VALUES (?,0,?)",(english,meaning))
            conn.execute("INSERT INTO senses(vocab_id,sense_index,meaning) VALUES ('near-a',1,'alternate meaning')")
            senses=conn.execute("SELECT vocab_id,sense_id,meaning FROM senses WHERE vocab_id LIKE 'near-%' ORDER BY vocab_id,sense_index").fetchall()
        vectors={english:[vector for word,_,vector in words if word==english] for english,_,_ in words}
        for sense in senses:
            vector=vectors[sense['vocab_id']][0]
            if sense['meaning']=='alternate meaning':vector=[.85,0.,math.sqrt(1-.85**2),0.]
            save_embedding(sense['vocab_id'],sense['sense_id'],make_embedding_text(sense['vocab_id'],sense['meaning']),
                           vector,'fixture-model',path=self.path)
        result=compare_candidates([{'candidate_id':'query','english':'nearby-query','meaning':'query meaning'}],
            api_key='fixture-key',threshold=.95,path=self.path,
            provider=lambda *args,**kwargs:{'model':'fixture-model','data':[{'embedding':[1.,0.,0.,0.]}]})
        item=result['items'][0]
        self.assertFalse(item['excluded'],'all nearest words are below the exclusion threshold')
        self.assertEqual([match['english'] for match in item['similar_matches']],['near-a','near-b','near-c'])
        self.assertAlmostEqual(item['similar_matches'][0]['similarity'],.9)
        self.assertAlmostEqual(item['similar_matches'][1]['similarity'],.8)
        self.assertAlmostEqual(item['similar_matches'][2]['similarity'],.8)

    def test_safe_prefix_bound_skips_full_cosine_for_unrelated_vectors(self):
        rng=random.Random(78);vectors=[]
        with database.connect(self.path) as conn:
            conn.execute("UPDATE senses SET meaning='' WHERE vocab_id='v1'")
            conn.executemany("INSERT INTO vocab(vocab_id,english,japanese) VALUES (?,?,'meaning')",
                [(f'vec-{index:03}',f'vector-{index:03}') for index in range(128)])
            conn.executemany("INSERT INTO senses(vocab_id,sense_index,meaning) VALUES (?,0,'meaning')",
                [(f'vec-{index:03}',) for index in range(128)])
            senses=conn.execute("SELECT vocab_id,sense_id FROM senses WHERE vocab_id LIKE 'vec-%' ORDER BY vocab_id").fetchall()
            for _ in senses:
                vector=[rng.gauss(0,1) for _ in range(32)];norm=math.sqrt(sum(value*value for value in vector));vectors.append([value/norm for value in vector]+[0.0]*32)
            vectors[0]=[1.0]+[0.0]*63
            conn.executemany("""INSERT INTO embeddings(vocab_id,sense_id,model,dimensions,input_version,input_hash,vector_json,created_at_utc)
                VALUES (?,?,'fixture-model',64,?,?,?,'2026-10-25T00:00:00+00:00')""",
                [(row['vocab_id'],row['sense_id'],INPUT_VERSION,embedding_hash(json.dumps(vector)),json.dumps(vector)) for row,vector in zip(senses,vectors)])
        result=compare_candidates([{'candidate_id':'nearest','english':'nearby phrase','meaning':'meaning'}],api_key='fixture-key',threshold=.8,path=self.path,
            provider=lambda *args,**kwargs:{'model':'fixture-model','data':[{'embedding':[1.0]+[0.0]*63}]})
        self.assertTrue(result['items'][0]['excluded'])
        self.assertEqual(result['items'][0]['matched_vocab_id'],'vec-000')
        self.assertEqual(len(result['items'][0]['similar_matches']),3)
        self.assertEqual(result['items'][0]['similar_matches'][0]['vocab_id'],'vec-000')
        self.assertLess(result['exact_comparisons'],result['dataset_size'])
        self.assertEqual(result['dataset_size'],128)

    def test_exact_match_and_missing_index_are_explained(self):
        exact=compare_candidate({'english':' COMPREHENSIVE ','meaning':'包括的'},api_key='fixture',path=self.path,
            provider=lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError('exact match should short-circuit')))
        self.assertEqual(exact['reason'],'exact_match')
        unknown=compare_candidate({'english':'guide','meaning':'手引き'},api_key='fixture',path=self.path,
            provider=lambda *args,**kwargs:{'model':'another-model','data':[{'embedding':[1,0]}]})
        self.assertEqual(unknown['reason'],'dataset_embeddings_not_indexed')


if __name__=='__main__':unittest.main()
