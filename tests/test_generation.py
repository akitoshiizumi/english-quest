import json
import unittest

from english_overlap.generation import generate_vocabulary_sentences


class GenerationTests(unittest.TestCase):
    def test_uses_fixed_provider_and_tracks_inflected_target_offsets(self):
        def fake_provider(endpoint,payload):
            self.assertEqual(endpoint,'responses')
            return {'model':'fixture-model','usage':{'input_tokens':5,'output_tokens':8},'output_text':json.dumps({'sentences':['The team took part in a short trial.']})}
        result=generate_vocabulary_sentences([{'vocab_id':'v1','sense_id':1,'english':'take part','meaning':'参加する'}],provider=fake_provider)
        self.assertEqual(result['used_vocab_ids'],['v1'])
        self.assertEqual(result['usages'][0]['usage_text'],'took part')
        self.assertEqual(result['model'],'fixture-model')

    def test_missing_target_fails_before_material_is_saved(self):
        with self.assertRaisesRegex(ValueError,'comprehensive'):
            generate_vocabulary_sentences([{'vocab_id':'v2','english':'comprehensive','meaning':'包括的'}],
                provider=lambda *args:{'output_text':json.dumps({'sentences':['This is a simple guide.']})})

    def test_missing_targets_get_one_completion_pass_and_usage_is_aggregated(self):
        calls=[]
        def provider(endpoint,payload):
            calls.append(payload)
            sentence='The team took part in the review.' if len(calls)==1 else 'A comprehensive plan worked.'
            return {'model':'fixture-model','output_text':json.dumps({'sentences':[sentence]}),'usage':{'input_tokens':10,'output_tokens':4}}
        items=[{'vocab_id':'v1','sense_id':1,'english':'take part','meaning':'参加する'}, {'vocab_id':'v2','sense_id':2,'english':'comprehensive','meaning':'包括的'}]
        result=generate_vocabulary_sentences(items,provider=provider,length='medium')
        self.assertEqual(result['used_vocab_ids'],['v1','v2'])
        self.assertEqual(result['usage'],{'input_tokens':20,'output_tokens':8})
        self.assertEqual(result['request_count'],2)
        self.assertEqual(result['length'],'medium')
        self.assertIn('comprehensive',calls[1]['input'])

    def test_trailing_placeholder_is_explained_and_phrase_stem_is_covered(self):
        calls=[]
        def provider(endpoint,payload):
            calls.append(payload)
            return {'model':'fixture-model','output_text':json.dumps({'sentences':['They rave about the new cafe.']})}
        target={'vocab_id':'rave','sense_id':7,'english':'rave about \u301c','meaning':'fixture'}
        result=generate_vocabulary_sentences([target],provider=provider)
        self.assertEqual(result['used_vocab_ids'],['rave'])
        self.assertEqual(result['usages'][0]['usage_text'],'rave about')
        self.assertEqual(json.loads(calls[0]['input'])['targets'][0]['match_phrase'],'rave about')
        self.assertIn('open slot',calls[0]['instructions'])

    def test_regex_metacharacters_are_literal_in_vocabulary_coverage(self):
        cases=[('C++ is useful.','C++'),('Use a+b in this expression.','a+b'),('A.B works.','A.B')]
        for sentence,target in cases:
            with self.subTest(target=target):
                result=generate_vocabulary_sentences([{'vocab_id':target,'english':target,'meaning':'fixture'}],
                    provider=lambda *args,sentence=sentence:{'output_text':json.dumps({'sentences':[sentence]})})
                self.assertEqual(result['used_vocab_ids'],[target])

    def test_large_selection_is_split_into_bounded_requests(self):
        calls=[]
        items=[{'vocab_id':f'v{i}','english':f'target{i}','meaning':'fixture'} for i in range(11)]
        def provider(endpoint,payload):
            calls.append(payload)
            targets=json.loads(payload['input'])['targets']
            sentences=[item['english']+' is useful.' for item in targets]
            return {'model':'fixture-model','output_text':json.dumps({'sentences':sentences}),'usage':{'input_tokens':len(targets),'output_tokens':len(targets)}}
        result=generate_vocabulary_sentences(items,provider=provider)
        self.assertEqual(len(calls),2)
        self.assertEqual([len(json.loads(call['input'])['targets']) for call in calls],[10,1])
        self.assertEqual(set(result['used_vocab_ids']),{f'v{i}' for i in range(11)})
        self.assertEqual(result['request_count'],2)

    def test_article_mode_uses_all_targets_in_one_cohesive_response(self):
        calls=[]
        items=[{'vocab_id':'v1','sense_id':1,'english':'take part','meaning':'fixture'},
               {'vocab_id':'v2','sense_id':2,'english':'comprehensive','meaning':'fixture'}]
        def provider(endpoint,payload):
            calls.append(payload)
            self.assertEqual(endpoint,'responses')
            self.assertEqual(payload['text']['format']['name'],'practice_article')
            return {'model':'fixture-model','usage':{'input_tokens':12,'output_tokens':16},
                    'output_text':json.dumps({'paragraphs':['The team took part in a comprehensive review.']})}
        result=generate_vocabulary_sentences(items,provider=provider,generation_mode='article')
        self.assertEqual(len(calls),1)
        self.assertEqual(result['generation_mode'],'article')
        self.assertEqual(result['groups'],[['The team took part in a comprehensive review.']])
        self.assertEqual(set(result['used_vocab_ids']),{'v1','v2'})
        self.assertEqual(result['request_count'],1)

    def test_article_mode_completes_missing_target_and_preserves_article(self):
        calls=[]
        items=[{'vocab_id':'v1','sense_id':1,'english':'take part','meaning':'fixture'},
               {'vocab_id':'v2','sense_id':2,'english':'comprehensive','meaning':'fixture'}]
        def provider(endpoint,payload):
            calls.append(payload)
            if len(calls)==1:
                paragraphs=['The team took part in a local review.']
            else:
                request=json.loads(payload['input'])
                self.assertIn('The team took part in a local review.',request['existing_article'])
                self.assertEqual([t['vocab_id'] for t in request['targets']],['v2'])
                paragraphs=['The comprehensive report helped everyone agree.']
            return {'model':'fixture-model','usage':{'input_tokens':3,'output_tokens':4},'output_text':json.dumps({'paragraphs':paragraphs})}
        result=generate_vocabulary_sentences(items,provider=provider,generation_mode='article')
        self.assertEqual(len(calls),2)
        self.assertEqual(result['generation_mode'],'article')
        self.assertEqual(result['groups'],[['The team took part in a local review.','The comprehensive report helped everyone agree.']])
        self.assertEqual(set(result['used_vocab_ids']),{'v1','v2'})
        self.assertEqual(result['usage'],{'input_tokens':6,'output_tokens':8})

    def test_unknown_generation_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unsupported generation mode'):
            generate_vocabulary_sentences([{'vocab_id':'v1','english':'target','meaning':'fixture'}],generation_mode='invalid',provider=lambda *args:None)


if __name__ == '__main__': unittest.main()
