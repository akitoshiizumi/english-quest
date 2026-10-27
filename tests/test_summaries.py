import json
import unittest

from english_overlap.openai_api import OpenAIError
from english_overlap.summaries import SUMMARY_PROMPT_VERSION, SummaryGenerationError, generate_material_summary


class MaterialSummaryTests(unittest.TestCase):
    def setUp(self):
        self.material = {'title': 'A useful guide', 'text_content': 'Employees can share ideas in a weekly meeting.'}

    def test_summary_uses_responses_structured_output_and_returns_provenance(self):
        captured = {}

        def provider(endpoint, payload):
            captured['endpoint'] = endpoint
            captured['payload'] = payload
            return {'model': 'fixture-model', 'output_text': json.dumps({'title': 'Weekly team meetings', 'summary': '週次会議で意見を共有する方法を説明します。'}),
                    'usage': {'input_tokens': 30, 'output_tokens': 12}}

        result = generate_material_summary(self.material, provider=provider)
        self.assertEqual(captured['endpoint'], 'responses')
        self.assertEqual(captured['payload']['text']['format']['type'], 'json_schema')
        self.assertEqual(json.loads(captured['payload']['input']), {
            'text': self.material['text_content']})
        self.assertEqual(result['title'], 'Weekly team meetings')
        self.assertEqual(result['summary'], '週次会議で意見を共有する方法を説明します。')
        self.assertEqual(result['model'], 'fixture-model')
        self.assertEqual(result['prompt_version'], SUMMARY_PROMPT_VERSION)
        self.assertEqual(result['usage']['input_tokens'], 30)

    def test_malformed_or_empty_output_fails_without_returning_a_summary(self):
        for response in ({'model': 'fixture-model', 'output_text': 'not json', 'usage': {'input_tokens': 2}},
                         {'model': 'fixture-model', 'output_text': '{"title":"Weekly meeting","summary":"  "}', 'usage': {}}):
            with self.subTest(response=response):
                with self.assertRaises(SummaryGenerationError):
                    generate_material_summary(self.material, provider=lambda *_: response)

    def test_provider_failure_is_reported(self):
        def provider(*_):
            raise OpenAIError('fixture API failure', status=503, retryable=True)

        with self.assertRaisesRegex(OpenAIError, 'fixture API failure'):
            generate_material_summary(self.material, provider=provider)


if __name__ == '__main__':
    unittest.main()
