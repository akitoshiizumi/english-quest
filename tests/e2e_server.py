"""Isolated server used by Playwright; never reads user database or practice_data."""
import os
import tempfile
import io
import json
import wave
import math
import struct
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEMP = tempfile.TemporaryDirectory(prefix='overlap-e2e-')
os.environ['ENGLISH_OVERLAP_DB'] = str(Path(TEMP.name) / 'fixture.sqlite3')
os.environ['ENGLISH_OVERLAP_DATA_ROLE'] = 'test'
os.environ['ENGLISH_OVERLAP_TEST_DATA_DIR'] = str(Path(TEMP.name) / 'materials')

from english_overlap.database import connect, migrate_database
from english_overlap import http
from english_overlap.http import Handler

migrate_database()
with connect() as conn:
    rows = [
        ('e2e-1','take part','参加する','verb','WorkAndCareer'),
        ('e2e-2','comprehensive','包括的','adjective','WorkAndCareer'),
        ('e2e-3','guide','手引き','noun','DailyLife'),
    ]
    rows.extend((f'e2e-page-{index:03d}',f'Pageword {index:03d}',f'ページ語{index:03d}','noun','Pagination') for index in range(125))
    for vocab_id, english, meaning, pos, category in rows:
        conn.execute('INSERT INTO vocab(vocab_id,english,japanese,pos,genre_tags) VALUES (?,?,?,?,?)', (vocab_id,english,meaning,pos,category))
        difficulty='A1' if category=='Pagination' else None
        conn.execute('INSERT INTO senses(vocab_id,sense_index,meaning,part_of_speech,difficulty_level) VALUES (?,0,?,?,?)', (vocab_id,meaning,pos,difficulty))
        conn.execute('INSERT OR IGNORE INTO categories(category_id,name) VALUES (?,?)', (category,category))
        conn.execute('INSERT INTO vocabulary_categories(vocab_id,category_id) VALUES (?,?)', (vocab_id,category))

Handler.ROOT = ROOT
http.API_KEY = ''  # E2E never inherits a developer API key or calls paid endpoints.
http.SAVE_DIR = Path(os.environ['ENGLISH_OVERLAP_TEST_DATA_DIR'])
http.SAVE_DIR.mkdir(parents=True, exist_ok=True)
audio_buffer = io.BytesIO()
with wave.open(audio_buffer, 'wb') as audio:
    audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000); audio.writeframes(b'\0\0' * 48000)
(http.SAVE_DIR / 'english_overlap_fixture.wav').write_bytes(audio_buffer.getvalue())
(http.SAVE_DIR / 'english_overlap_fixture.json').write_text(json.dumps({
    'text':'A fixture sentence.', 'spoken_text':'A fixture sentence.', 'blocks':[{'english':'A fixture sentence.','japanese':'\u5408\u6210\u6587\u3067\u3059\u3002','vocabulary':[{'word':'fixture','meaning':'\u5408\u6210\u7528'}]}],
    'words':[{'word':'A','start':0.0,'end':0.1},{'word':'fixture','start':0.1,'end':0.5},{'word':'sentence','start':0.5,'end':0.9}],
    'created_at':'2026-10-24T00:00:00+00:00','audio_seconds':1.0,'audio_file':'english_overlap_fixture.wav','voice':'marin','style':'natural','summary':'Fixture'
},ensure_ascii=False),encoding='utf-8')
(http.SAVE_DIR / 'english_overlap_no_summary_fixture.json').write_text(json.dumps({
    'text':'A synthetic sentence without a generated summary.', 'created_at':'2026-10-24T01:00:00+00:00',
    'audio_file':'missing_fixture_audio.mp3'
},ensure_ascii=False),encoding='utf-8')
(http.SAVE_DIR / 'english_overlap_no_summary_second_fixture.json').write_text(json.dumps({
    'text':'Another synthetic sentence without a summary.', 'created_at':'2026-10-24T02:00:00+00:00'
},ensure_ascii=False),encoding='utf-8')
(http.SAVE_DIR / 'english_overlap_edit_fixture.json').write_text(json.dumps({
    'text':'Editable audio fixture.', 'spoken_text':'Editable audio fixture.',
    'created_at':'2026-10-24T03:00:00+00:00', 'audio_file':'english_overlap_fixture.wav',
    'blocks':[{'english':'Editable audio fixture.','japanese':'???????????','vocabulary':[]}],
    'words':[{'word':'Editable','start':0.0,'end':0.2}], 'audio_seconds':1.0
},ensure_ascii=False),encoding='utf-8')
two_sentence_audio = io.BytesIO()
with wave.open(two_sentence_audio, 'wb') as audio:
    audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
    samples = (int(12000 * math.sin(2 * math.pi * (440 if t < 1.1 else 880) * t))
               if t < 1.1 or 1.5 <= t < 2.8 or 3.0 <= t < 3.8 else 0 for t in (i / 24000 for i in range(96000)))
    audio.writeframes(b''.join(struct.pack('<h', value) for value in samples))
(http.SAVE_DIR / 'english_overlap_zz_two_sentence_fixture.wav').write_bytes(two_sentence_audio.getvalue())
(http.SAVE_DIR / 'english_overlap_zz_two_sentence_fixture.json').write_text(json.dumps({
    'text':'We start here. Then we continue.',
    'blocks':[{'english':'We start here.','japanese':'ここから始めます。','vocabulary':[]},
              {'english':'Then we continue.','japanese':'それから続けます。','vocabulary':[]}],
    'words':[{'word':'We','start':0.0,'end':0.2},{'word':'start','start':0.2,'end':0.7},{'word':'here','start':0.7,'end':1.1},
             {'word':'Then','start':1.5,'end':1.8},{'word':'we','start':1.8,'end':2.1},{'word':'continue','start':2.1,'end':2.8}],
    'audio_seconds':4.0,'audio_file':'english_overlap_zz_two_sentence_fixture.wav','voice':'marin','style':'natural','summary':'Two sentence fixture'
},ensure_ascii=False),encoding='utf-8')
(http.SAVE_DIR / 'english_overlap_zz_three_sentence_fixture.json').write_text(json.dumps({
    'text':'We start here. Then we continue. Finally, we finish.',
    'blocks':[{'english':'We start here.','japanese':'ここから始めます。','vocabulary':[]},
              {'english':'Then we continue.','japanese':'それから続けます。','vocabulary':[]},
              {'english':'Finally, we finish.','japanese':'最後に終わります。','vocabulary':[]}],
    'words':[{'word':'We','start':0.0,'end':0.2},{'word':'start','start':0.2,'end':0.7},{'word':'here','start':0.7,'end':1.1},
             {'word':'Then','start':1.5,'end':1.8},{'word':'we','start':1.8,'end':2.1},{'word':'continue','start':2.1,'end':2.8},
             {'word':'Finally','start':3.0,'end':3.25},{'word':'we','start':3.25,'end':3.45},{'word':'finish','start':3.45,'end':3.8}],
    'audio_seconds':4.0,'audio_file':'english_overlap_zz_two_sentence_fixture.wav','voice':'marin','style':'natural','summary':'Three sentence fixture'
},ensure_ascii=False),encoding='utf-8')
(http.SAVE_DIR / 'english_overlap_zz_close_fixture.json').write_text(json.dumps({
    'text':'Go. Now.',
    'blocks':[{'english':'Go.','japanese':'行こう。','vocabulary':[]},
              {'english':'Now.','japanese':'今。','vocabulary':[]}],
    'words':[{'word':'Go','start':0.0,'end':0.12},{'word':'Now','start':0.06,'end':0.4}],
    'audio_seconds':4.0,'audio_file':'english_overlap_zz_two_sentence_fixture.wav','summary':'Close sentence fixture'
},ensure_ascii=False),encoding='utf-8')
(http.SAVE_DIR / 'english_overlap_zz_untimed_fixture.json').write_text(json.dumps({
    'text':'An untimed sentence. Another untimed sentence.',
    'blocks':[{'english':'An untimed sentence.','japanese':'時刻なし。','vocabulary':[]},
              {'english':'Another untimed sentence.','japanese':'もう一文。','vocabulary':[]}],
    'words':[], 'audio_seconds':4.0,'audio_file':'english_overlap_zz_two_sentence_fixture.wav','summary':'Untimed fixture'
},ensure_ascii=False),encoding='utf-8')
http.schedule_automatic_difficulty()  # Startup queues a bounded job; the empty key keeps it waiting.
server = ThreadingHTTPServer(('127.0.0.1', int(os.environ.get('ENGLISH_OVERLAP_E2E_PORT', '18765'))), Handler)
try:
    server.serve_forever()
finally:
    server.server_close()
    TEMP.cleanup()
