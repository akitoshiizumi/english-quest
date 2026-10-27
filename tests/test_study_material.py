import json
import unittest
from unittest.mock import patch

from english_overlap.app import generate_study_material


class StudyMaterialGenerationTests(unittest.TestCase):
    def test_retries_contaminated_notes_then_removes_only_foreign_text(self):
        responses = []
        payloads = []
        items = [
            {'japanese': 'チームはمرحبا会議に参加した。', 'vocabulary': [
                {'word': 'took part', 'meaning': '参加する رائع'}]},
            {'japanese': '包括的な手引きです。', 'vocabulary': [
                {'word': 'comprehensive', 'meaning': '包括的な'},
                {'word': 'guide', 'meaning': '手引き'}]},
        ]
        response = {'output_text': json.dumps({'items': items}, ensure_ascii=False),
                    'usage': {'input_tokens': 3, 'output_tokens': 4}}

        def fake_call(endpoint, body, content_type):
            self.assertEqual(endpoint, 'responses')
            self.assertEqual(content_type, 'application/json')
            payloads.append(json.loads(body))
            responses.append(response)
            return json.dumps(response, ensure_ascii=False).encode('utf-8')

        with patch('english_overlap.app.call_api', side_effect=fake_call):
            blocks, usage = generate_study_material('The team took part.\nA comprehensive guide helps.')

        self.assertEqual(len(payloads), 2)
        self.assertIn('Japanese only', payloads[0]['instructions'])
        self.assertIn('correction_needed', json.loads(payloads[1]['input']))
        self.assertIn('Rewrite those fields entirely in Japanese', payloads[1]['instructions'])
        self.assertEqual(blocks[0]['japanese'], 'チームは会議に参加した。')
        self.assertEqual(blocks[0]['vocabulary'], [{'word': 'took part', 'meaning': '参加する'}])
        self.assertEqual(blocks[1]['japanese'], '包括的な手引きです。')
        self.assertEqual(len(blocks[1]['vocabulary']), 2)
        self.assertEqual(usage, {'input_tokens': 6, 'output_tokens': 8})

    def test_all_foreign_translation_is_omitted_without_aborting_the_article(self):
        response = {'output_text': json.dumps({'items': [
            {'japanese': 'مرحبا this is English', 'vocabulary': [
                {'word': 'guide', 'meaning': 'helpful'}]}
        ]}, ensure_ascii=False)}
        with patch('english_overlap.app.call_api', return_value=json.dumps(response, ensure_ascii=False).encode('utf-8')):
            blocks, _ = generate_study_material('A guide is useful.')
        self.assertEqual(blocks[0]['english'], 'A guide is useful.')
        self.assertEqual(blocks[0]['japanese'], '（日本語訳を省略）')
        self.assertEqual(blocks[0]['vocabulary'], [])

    def test_valid_japanese_notes_return_without_retry(self):
        response = {'output_text': json.dumps({'items': [
            {'japanese': '包括的な案内です。', 'vocabulary': [
                {'word': 'guide', 'meaning': '案内'}]}
        ]}, ensure_ascii=False)}
        with patch('english_overlap.app.call_api', return_value=json.dumps(response, ensure_ascii=False).encode('utf-8')) as call:
            blocks, _ = generate_study_material('A guide is comprehensive.')
        self.assertEqual(call.call_count, 1)
        self.assertEqual(blocks[0]['vocabulary'][0]['word'], 'guide')

    def test_malformed_response_shape_still_fails_with_a_clear_message(self):
        response = {'output_text': json.dumps({'items': []})}
        with patch('english_overlap.app.call_api', return_value=json.dumps(response).encode('utf-8')):
            with self.assertRaisesRegex(RuntimeError, '学習メモの形式が不正'):
                generate_study_material('A guide is useful.')


if __name__ == '__main__':
    unittest.main()
