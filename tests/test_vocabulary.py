import unittest

from english_overlap.vocabulary import cosine_disposition, cosine_similarity, find_usage, normalize_headword, select_weak_vocabulary


class VocabularyUtilitiesTests(unittest.TestCase):
    def test_normalization_and_cosine_boundaries(self):
        self.assertEqual(normalize_headword('  Take　PART  '), 'take part')
        self.assertAlmostEqual(cosine_similarity([1,0],[0.8,0.6]), 0.8)
        self.assertEqual(cosine_disposition(0.799,0.8), 'distinct')
        self.assertEqual(cosine_disposition(0.8,0.8), 'similar')
        self.assertEqual(cosine_similarity([0,0],[1,0]), 0)
        with self.assertRaises(ValueError): cosine_similarity([1],[1,2])

    def test_usage_accepts_simple_inflections_and_tracks_offsets(self):
        uses = find_usage('She took part in the program and later takes part again.', 'take part')
        self.assertEqual([item['text'] for item in uses], ['took part','takes part'])

    def test_directional_weakness_ranks_unstudied_then_lowest_known_rate_stably(self):
        items = [
            {'vocab_id':'b','events':[{'direction':'en_to_ja','rating':'known'}]},
            {'vocab_id':'a','events':[{'direction':'en_to_ja','rating':'again'}]},
            {'vocab_id':'c','events':[]},
        ]
        result=select_weak_vocabulary(items,'en_to_ja',3)
        self.assertEqual([item['vocab_id'] for item in result],['c','a','b'])
        self.assertEqual(result[0]['selection_reason'],'未学習・方向別履歴なし')
        self.assertEqual([item['vocab_id'] for item in select_weak_vocabulary(items,'ja_to_en',3,False)],[])

    def test_trailing_placeholder_markers_are_open_slots(self):
        for marker in ('\uff5e','\u301c','~','\u2026','...'):
            with self.subTest(marker=marker):
                matches=find_usage('They rave about the new cafe.', 'rave about '+marker)
                self.assertEqual([match['text'] for match in matches],['rave about'])


if __name__ == '__main__': unittest.main()
