import base64
import io
import json
import sys
import types
import unittest
import wave
from unittest.mock import patch

from english_overlap import app


class FakeRealtimeSocket:
    def __init__(self):
        self.sent = []
        self.events = iter([
            {'type': 'session.updated'},
            {'type': 'response.output_audio.delta', 'delta': base64.b64encode(b'\x00\x00').decode()},
            {'type': 'response.done', 'response': {'status': 'completed', 'usage': {'output_tokens': 1}}},
        ])

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def recv(self, timeout=None):
        return json.dumps(next(self.events))


class SpeechStyleTests(unittest.TestCase):
    def test_advanced_style_reaches_realtime_request_and_preserves_text(self):
        socket = FakeRealtimeSocket()
        websockets = types.ModuleType('websockets')
        sync = types.ModuleType('websockets.sync')
        client = types.ModuleType('websockets.sync.client')
        client.connect = lambda *_args, **_kwargs: socket
        progress=[]
        with patch.dict(sys.modules, {'websockets': websockets, 'websockets.sync': sync, 'websockets.sync.client': client}):
            audio, transcript, usage = app.realtime_speech('We were going to leave.', 'marin', 'native_unfiltered',on_progress=progress.append)
        session, response = socket.sent
        self.assertEqual(session['session']['audio']['output']['speed'], 1.0)
        self.assertEqual(session['session']['audio']['output']['format']['rate'], 24000)
        self.assertEqual(response['type'], 'response.create')
        instructions = response['response']['instructions']
        for phrase in ('heavily reduced pronunciation', 'connected speech', 'Mumble slightly', 'irregular rhythm', 'every supplied word'):
            self.assertIn(phrase, instructions)
        self.assertIn('We were going to leave.', response['response']['input'][0]['content'][0]['text'])
        self.assertTrue(audio.startswith(b'RIFF'))
        self.assertEqual(usage['output_tokens'], 1)
        self.assertEqual(progress[-1],1.0)
        self.assertEqual(progress,sorted(progress))

    def test_transcription_reports_completed_synthetic_chunks(self):
        source=io.BytesIO()
        with wave.open(source,'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(24000);audio.writeframes(b'\0\0'*24000)
        progress=[]
        with patch.object(app,'call_api',return_value=json.dumps({'words':[{'word':'fixture','start':0.1,'end':0.5}]}).encode()):
            words=app.transcribe_audio_chunks(source.getvalue(),on_progress=lambda current,total:progress.append((current,total)))
        self.assertEqual(words,[{'word':'fixture','start':0.1,'end':0.5}])
        self.assertEqual(progress,[(1,1)])

    def test_style_order_keeps_existing_profiles(self):
        self.assertEqual(app.STYLE_ORDER[-2:], ['reduced_extreme', 'native_unfiltered'])
        self.assertIn('natural', app.load_speech_styles())
        self.assertIn('native_unfiltered', app.load_speech_styles())


if __name__ == '__main__':
    unittest.main()
