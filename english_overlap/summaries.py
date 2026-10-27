"""AI summaries for saved learning materials."""

from __future__ import annotations

import json
import os

from .openai_api import OpenAIError, request_json, response_text


SUMMARY_PROMPT_VERSION = 'material-summary-v2-json-source-title'


class SummaryGenerationError(OpenAIError):
    def __init__(self, message: str, *, model: str, usage: dict):
        super().__init__(message)
        self.model = model
        self.usage = usage


def generate_material_summary(material: dict, *, api_key: str | None = None, provider=None) -> dict:
    model = os.environ.get('OPENAI_TEXT_MODEL', 'gpt-6-luna')
    send = provider or (lambda endpoint, payload: request_json(endpoint, payload, api_key=api_key))
    schema = {
        'type': 'object', 'additionalProperties': False,
        'properties': {'title': {'type': 'string'}, 'summary': {'type': 'string'}},
        'required': ['title', 'summary'],
    }
    prompt = {
        'model': model,
        'instructions': (
            'Read only the supplied material text. Return a concise title in the same language as the material '
            'and a concise Japanese summary in 1–3 sentences. Make the title specific to the text, describe its '
            'actual topic in the summary, and do not use or infer a topic from any outside title or prior metadata. '
            'Do not add unsupported facts. Return both fields in the required JSON schema.'
        ),
        'input': json.dumps({'text': material['text_content']}, ensure_ascii=False),
        'text': {'format': {'type': 'json_schema', 'name': 'material_summary', 'strict': True, 'schema': schema}},
        'max_output_tokens': 300,
    }
    result = send('responses', prompt)
    usage = result.get('usage') or {}
    if not isinstance(usage, dict):
        usage = {}
    model = result.get('model') or model
    try:
        parsed = json.loads(response_text(result))
        if not isinstance(parsed, dict):
            raise TypeError('summary response must be a JSON object')
        title = str(parsed.get('title') or '').strip()
        summary = str(parsed.get('summary') or '').strip()
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        raise SummaryGenerationError('AI要約の応答を読み取れませんでした。再試行してください。', model=model, usage=usage) from None
    if not title or not summary:
        raise SummaryGenerationError('AIが教材名または要約を返しませんでした。再試行してください。', model=model, usage=usage)
    return {'title': title[:160], 'summary': summary, 'model': model, 'usage': usage,
            'prompt_version': SUMMARY_PROMPT_VERSION}
