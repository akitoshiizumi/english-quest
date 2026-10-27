"""Small server-side OpenAI HTTP boundary with injectable transport for tests."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Callable


class OpenAIError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def request_json(endpoint: str, payload: dict, *, api_key: str | None = None,
                 transport: Callable | None = None) -> dict:
    key = (api_key if api_key is not None else os.environ.get('OPENAI_API_KEY', '')).strip()
    if not key:
        raise OpenAIError('サーバーにOpenAI APIキーが設定されていません。')
    if endpoint not in {'responses', 'embeddings'}:
        raise ValueError('Unsupported OpenAI endpoint')
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request('https://api.openai.com/v1/' + endpoint, data=body,
                                 headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'}, method='POST')
    send = transport or urllib.request.urlopen
    try:
        with send(req, timeout=90) as response:
            result = json.loads(response.read())
            if not isinstance(result, dict):
                raise OpenAIError('OpenAI returned an invalid response.')
            return result
    except urllib.error.HTTPError as error:
        # Never surface the request headers or key in API-facing errors.
        retryable = error.code in (408, 409, 429) or error.code >= 500
        raise OpenAIError(f'OpenAI request failed (HTTP {error.code}).', status=error.code, retryable=retryable) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise OpenAIError('OpenAIへの接続に失敗しました。ネットワークを確認して再試行してください。', retryable=True) from None


def response_text(result: dict) -> str:
    text = result.get('output_text')
    if isinstance(text, str) and text.strip():
        return text.strip()
    return ''.join(content.get('text', '') for item in result.get('output', [])
                   if item.get('type') == 'message' for content in item.get('content', [])
                   if content.get('type') == 'output_text').strip()
