import json, os, uuid, urllib.request, urllib.error, base64, io, wave, html, re, statistics, shutil, subprocess, unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from .storage import practice_data_dir

ROOT=Path(__file__).resolve().parent.parent
HOST='127.0.0.1'; PORT=8765
VOICES={'marin','cedar','coral','sage','shimmer','alloy','ash','ballad','echo','verse'}
MODEL=os.environ.get('OPENAI_REALTIME_MODEL', 'gpt-realtime-2.1-mini')
TEXT_MODEL=os.environ.get('OPENAI_TEXT_MODEL', 'gpt-6-luna')
EMBEDDING_MODEL=os.environ.get('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small')
TRANSCRIPTION_MODEL=os.environ.get('OPENAI_TRANSCRIPTION_MODEL', 'whisper-1')
SAVE_DIR=practice_data_dir()
MAX_TEXT_CHARS=20000
REALTIME_RATES={'input_audio':10.00,'input_text':0.60,'cached_input':0.30,'output_audio':20.00,'output_text':2.40}
WHISPER_PER_MINUTE=0.006
DEFAULT_SPEECH_STYLES={
    'natural':{'label':'自然','note':'自然な標準アメリカ英語','speed':1.0,'instructions':'Use natural contemporary American English with lifelike rhythm and linked speech. Keep reductions subtle and intelligible.'},
    'clear':{'label':'クリア','note':'明瞭で学習しやすいアメリカ英語','speed':0.88,'instructions':'Use clear contemporary American English at a measured pace with distinct consonants and clean word boundaries. Keep reductions light.'},
    'expressive':{'label':'感情豊か','note':'抑揚を大きくしたアメリカ英語','speed':1.0,'instructions':'Use expressive contemporary American English. Make the emotional contour clearly audible: vary pitch, stress important words, and use intentional rises and falls. Do not deliver this neutrally.'},
    'joy':{'label':'喜び','note':'明るく嬉しそうなアメリカ英語','speed':1.06,'instructions':'Use joyful contemporary American English. Sound genuinely happy, bright, smiling, and enthusiastic with buoyant pitch and upbeat emphasis.'},
    'sadness':{'label':'悲しみ','note':'静かで感傷的なアメリカ英語','speed':0.78,'instructions':'Use sad contemporary American English. Sound genuinely subdued and reflective with slower pacing, softer volume, falling pitch, and longer pauses. Avoid melodrama.'},
    'anger':{'label':'怒り','note':'強く断固としたアメリカ英語','speed':1.08,'instructions':'Use angry contemporary American English. Sound firm, tense, and controlled with sharp stress, decisive pacing, and stronger volume. Do not shout or add insults.'},
    'warm':{'label':'温かく親しみやすい','note':'フレンドリーなアメリカ英語','speed':0.94,'instructions':'Use warm, friendly contemporary American English with a smiling, encouraging, welcoming tone. Use gentle pitch movement and softened emphasis.'},
    'energetic':{'label':'明るく活発','note':'テンポのよいアメリカ英語','speed':1.12,'instructions':'Use lively, confident contemporary American English with upbeat energy, brisk momentum, bright pitch, and strong forward emphasis without shouting.'},
    'calm':{'label':'落ち着いて思慮深い','note':'ゆったりしたアメリカ英語','speed':0.82,'instructions':'Use calm, thoughtful contemporary American English with noticeably relaxed pacing, lower energy, gentle pauses, and restrained pitch movement.'},
    'storytelling':{'label':'物語を語るように','note':'表現力のあるアメリカ英語','speed':0.94,'instructions':'Use engaging contemporary American English with natural storytelling emphasis. Shape the sentence like a story with contrast, suspense, and varied pitch.'},
    'casual':{'label':'自然な日常会話','note':'くだけたアメリカ英語','speed':1.08,'instructions':'Use relaxed conversational contemporary American English with casual everyday phrasing, informal rhythm, light reductions, and a spontaneous feel.'},
    'reduced':{'label':'崩し','note':'自然な連結・弱形を使うアメリカ英語','speed':1.08,'instructions':'Use noticeably casual contemporary American connected speech with natural reductions, weak forms, linking, contractions, and occasional dropped sounds. Keep every word recoverable; do not mumble or invent words.'},
    'reduced_big':{'label':'崩し大','note':'強い連結・短縮の上級アメリカ英語','speed':1.2,'instructions':'Use strongly reduced, fast contemporary American connected speech. Apply frequent weak forms, linking, contractions, flapping, schwa reduction, and natural sound elisions. Make it clearly different from careful speech, but keep the exact words recoverable and never mumble or invent words.'},
    'reduced_extreme':{'label':'崩し特大','note':'非常に速く大きく崩した超上級アメリカ英語','speed':1.3,'instructions':'Use extremely reduced, highly casual contemporary American connected speech at a fast conversational pace. Apply very frequent weak forms, aggressive linking, contractions, flapping, schwa reduction, sound elisions, and compressed rhythm. Make it intentionally difficult and strongly different from clear speech, but preserve every original word in the audio; do not mumble, replace words, or invent words.'},
    'native_unfiltered':{
        'label':'ネイティブ会話・最難関',
        'note':'早口・強い音の連結・弱化・軽いもごもご発音',
        'instructions':(
            'Speak like a native American English speaker talking spontaneously to a lifelong friend who already knows the context. '
            'Use an extremely casual, fast conversational cadence with irregular rhythm and sudden bursts of speed. '
            'Use heavily reduced pronunciation and aggressive connected speech: run words together, weaken unstressed vowels and function words, '
            'swallow some unstressed syllables, and apply natural elision, assimilation, contractions, flapping, and occasional dropped consonants. '
            'Mumble slightly in brief stretches and sometimes trail off, but keep the original text recognizable. '
            'Do not articulate carefully like a narrator or teacher. Do not sound drunk, perform exaggerated slurring, or deliberately mispronounce every word. '
            'Keep every supplied word in the same order; change only its spoken realization, not the wording.'
        )
    }
}
STYLE_ORDER=['natural','clear','expressive','joy','sadness','anger','reduced','reduced_big','reduced_extreme','native_unfiltered']

def parse_practice_text(text):
    """Split English input into sentence blocks for translation generation."""
    from .sentences import split_english_sentences
    sentences=split_english_sentences(text.strip())
    if not sentences:
        sentences=[text.strip()]
    return [{'english':sentence,'japanese':'','vocabulary':[]} for sentence in sentences],text.strip()

def _is_japanese_letter(char):
    code=ord(char)
    return (0x3040<=code<=0x30ff or 0x3400<=code<=0x4dbf or 0x4e00<=code<=0x9fff
            or 0xf900<=code<=0xfaff or 0xff66<=code<=0xff9f)

def _has_foreign_letters(text):
    return any(unicodedata.category(char).startswith('L') and not _is_japanese_letter(char) for char in text)

def _strip_non_japanese_text(text):
    """Remove foreign-script letters while preserving Japanese, punctuation, and numbers."""
    cleaned=''.join(char for char in str(text) if _is_japanese_letter(char)
                    or unicodedata.category(char)[0] in ('P','N','Z'))
    cleaned=re.sub(r'\s+',' ',cleaned).strip()
    cleaned=re.sub(r'(?<=[\u3040-\u30ff\u3400-\u9fff])\s+(?=[\u3040-\u30ff\u3400-\u9fff])','',cleaned)
    cleaned=re.sub(r'\s+([、。，．！？：；）】』」])',r'\1',cleaned)
    cleaned=re.sub(r'([（【『「])\s+',r'\1',cleaned)
    return cleaned

def generate_study_material(text):
    """Generate Japanese translations and vocabulary notes for each sentence."""
    blocks,_=parse_practice_text(text)
    schema={
        'type':'object','additionalProperties':False,
        'properties':{'items':{'type':'array','items':{
            'type':'object','additionalProperties':False,
            'properties':{
                'japanese':{'type':'string'},
                'vocabulary':{'type':'array','items':{
                    'type':'object','additionalProperties':False,
                    'properties':{'word':{'type':'string'},'meaning':{'type':'string'}},
                    'required':['word','meaning']
                }}
            },
            'required':['japanese','vocabulary']
        }}},'required':['items']
    }
    total_usage={'input_tokens':0,'output_tokens':0}
    candidate_items=None
    correction_needed=[]
    for attempt in range(2):
        request={
            'model':TEXT_MODEL,
            'instructions':'You create study notes for American English learners. For every source sentence, write one complete, natural translation in Japanese. The japanese field and every vocabulary meaning field must contain Japanese only: use Japanese kanji, hiragana, and katakana; do not copy English from the source, transliterate foreign text, or include Arabic, Latin, Cyrillic, Greek, or other foreign-language words. Keep English only in vocabulary word fields, copied exactly from the corresponding source sentence. Meanings should be concise Japanese equivalents, not explanations. Example for "a comprehensive guide": {"word":"comprehensive","meaning":"包括的な"}, {"word":"guide","meaning":"手引き"}. Do not add fields or commentary. Return JSON only.' + (' The previous response contained non-Japanese text in the listed fields. Rewrite those fields entirely in Japanese; do not preserve or quote the foreign text.' if attempt else ''),
            'input':json.dumps({'sentences':[block['english'] for block in blocks],
                                **({'correction_needed':correction_needed} if correction_needed else {})},ensure_ascii=False),
            'text':{'format':{'type':'json_schema','name':'english_study_material','strict':True,'schema':schema}}
        }
        response=json.loads(call_api('responses',json.dumps(request,ensure_ascii=False).encode('utf-8'),'application/json'))
        usage=response.get('usage') or {}
        total_usage['input_tokens']+=int(usage.get('input_tokens') or 0)
        total_usage['output_tokens']+=int(usage.get('output_tokens') or 0)
        output=response.get('output_text','')
        if not output:
            output=''.join(content.get('text','') for item in response.get('output',[]) if item.get('type')=='message' for content in item.get('content',[]) if content.get('type')=='output_text')
        result=json.loads(output)
        items=result.get('items',[])
        if len(items)!=len(blocks):
            continue
        candidate_items=items
        correction_needed=[]
        for block,item in zip(blocks,items):
            if not isinstance(item,dict):
                correction_needed.append({'sentence':block['english'],'fields':['item']})
                continue
            japanese=str(item.get('japanese','')).strip()
            vocabulary=item.get('vocabulary',[])
            issues=[]
            if not japanese or not re.search(r'[\u3040-\u30ff\u3400-\u9fff]',japanese) or _has_foreign_letters(japanese):
                issues.append('japanese')
            if not isinstance(vocabulary,list):
                issues.append('vocabulary')
                vocabulary=[]
            for entry in vocabulary:
                if not isinstance(entry,dict):
                    issues.append('vocabulary')
                    continue
                word=str(entry.get('word','')).strip()
                meaning=str(entry.get('meaning','')).strip()
                if (not word or re.search(r'[\u3040-\u30ff\u3400-\u9fff\u0600-\u06ff\u0400-\u04ff\u0370-\u03ff]',word)
                    or not re.search(r'[A-Za-z]',word)
                    or not re.search(r'[\u3040-\u30ff\u3400-\u9fff]',meaning)
                    or _has_foreign_letters(meaning)
                    or not re.search(r'(?<![A-Za-z0-9])'+re.escape(word)+r'(?![A-Za-z0-9])',block['english'],re.IGNORECASE)):
                    issues.append('vocabulary.meaning')
            if issues:
                correction_needed.append({'sentence':block['english'],'fields':sorted(set(issues))})
        if not correction_needed:
            for block,item in zip(blocks,items):
                block['japanese']=str(item['japanese']).strip()
                block['vocabulary']=item.get('vocabulary',[])
            return blocks,total_usage
    if candidate_items is None:
        raise RuntimeError('学習メモの形式が不正なため生成できませんでした。')
    # A bad note should not discard the complete article after the corrective retry.
    for block,item in zip(blocks,candidate_items):
        if not isinstance(item,dict):
            block['japanese']='（日本語訳を省略）'
            block['vocabulary']=[]
            continue
        japanese=_strip_non_japanese_text(item.get('japanese',''))
        block['japanese']=japanese if re.search(r'[\u3040-\u30ff\u3400-\u9fff]',japanese) else '（日本語訳を省略）'
        vocabulary=[]
        source_entries=item.get('vocabulary',[])
        for entry in source_entries if isinstance(source_entries,list) else []:
            if not isinstance(entry,dict):
                continue
            word=str(entry.get('word','')).strip()
            meaning=_strip_non_japanese_text(entry.get('meaning',''))
            if (word and not re.search(r'[\u3040-\u30ff\u3400-\u9fff\u0600-\u06ff\u0400-\u04ff\u0370-\u03ff]',word)
                    and re.search(r'[A-Za-z]',word)
                    and re.search(r'(?<![A-Za-z0-9])'+re.escape(word)+r'(?![A-Za-z0-9])',block['english'],re.IGNORECASE)
                    and re.search(r'[\u3040-\u30ff\u3400-\u9fff]',meaning)):
                vocabulary.append({**entry,'word':word,'meaning':meaning})
        block['vocabulary']=vocabulary
    return blocks,total_usage
def load_speech_styles():
    styles={key:value.copy() for key,value in DEFAULT_SPEECH_STYLES.items()}
    config_path=ROOT/'config.json'
    if config_path.exists():
        try:
            config_data=json.loads(config_path.read_text(encoding='utf-8-sig'))
            configured=config_data.get('SPEECH_STYLES',{})
            if isinstance(configured,dict):
                for key,value in configured.items():
                    if isinstance(value,dict) and value.get('instructions'):
                        styles[key]={**styles.get(key,{}),**value}
        except (OSError,ValueError):
            pass
    return styles

SPEECH_STYLES=load_speech_styles()

def load_api_key():
    """Read the local .env first, optionally falling back to process env."""
    env_file=ROOT/'.env'
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding='utf-8-sig').splitlines():
                line=line.strip()
                if line.startswith('OPENAI_API_KEY='):
                    key=line.split('=',1)[1].strip().strip('"').strip("'")
                    if key:
                        return key
        except OSError:
            pass
    config_path=ROOT/'config.json'
    if config_path.exists():
        try:
            config=json.loads(config_path.read_text(encoding='utf-8-sig'))
            key=config.get('OPENAI_API_KEY','')
            if not isinstance(key,str):
                raise ValueError('OPENAI_API_KEY は文字列で指定してください。')
            key=key.strip()
            if key and key!='sk-ここにAPIキーを入力':
                return key
        except (ValueError, OSError) as ex:
            raise RuntimeError(f'config.json を読み取れません: {ex}') from ex
    return os.environ.get('OPENAI_API_KEY','').strip()

API_KEY=load_api_key()

def api_error(ex):
    raw=str(ex)
    if 'invalid_api_key' in raw or 'Incorrect API key' in raw or ('api key' in raw.lower() and 'invalid' in raw.lower()):
        return 'OpenAI APIキーが無効です。.env の OPENAI_API_KEY を有効なキーに更新し、サーバーを再起動してください。キーが漏えいした場合は新しいキーへローテーションしてください。'
    if isinstance(ex,urllib.error.HTTPError):
        try:
            msg=json.loads(ex.read().decode('utf-8'))['error']['message']
        except Exception:
            msg=f'API HTTP {ex.code}'
        return msg
    return str(ex)

def call_api(endpoint, body, content_type):
    request=urllib.request.Request('https://api.openai.com/v1/'+endpoint, data=body, headers={'Authorization':'Bearer '+API_KEY,'Content-Type':content_type},method='POST')
    with urllib.request.urlopen(request,timeout=120) as response:
        return response.read()

def multipart_form(fields, file_bytes, filename='speech.mp3'):
    boundary='----overlap-'+uuid.uuid4().hex
    chunks=[]
    for key,value in fields.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    chunks.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: audio/wav\r\n\r\n'.encode(),file_bytes,b'\r\n',f'--{boundary}--\r\n'.encode()])
    return b''.join(chunks),'multipart/form-data; boundary='+boundary

def wav_to_mp3(audio):
    """Convert internal PCM WAV audio to an MP3 for storage and browser playback."""
    ffmpeg=shutil.which('ffmpeg') or r'C:\bin\ffmpeg-6.1.1-full_build\bin\ffmpeg.exe'
    if not Path(ffmpeg).is_file() and not shutil.which('ffmpeg'):
        raise RuntimeError('MP3変換に必要なffmpegが見つかりません。')
    result=subprocess.run([
        ffmpeg,'-hide_banner','-loglevel','error','-f','wav','-i','pipe:0',
        '-codec:a','libmp3lame','-b:a','192k','-f','mp3','pipe:1'
    ],input=audio,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    if result.returncode!=0 or not result.stdout:
        raise RuntimeError('WAVからMP3への変換に失敗しました。')
    return result.stdout

def transcribe_audio_chunks(audio, chunk_seconds=30, on_progress=None):
    """Transcribe short WAV chunks so long recordings retain local timing."""
    with wave.open(io.BytesIO(audio),'rb') as source:
        params=source.getparams()
        frames=source.readframes(source.getnframes())
    if params.sampwidth != 2 or params.nchannels != 1:
        raise RuntimeError('Unexpected generated WAV format')
    frame_bytes=params.sampwidth*params.nchannels
    total_frames=len(frames)//frame_bytes
    chunk_frames=params.framerate*chunk_seconds
    all_words=[]
    chunk_starts=list(range(0,total_frames,chunk_frames))
    for chunk_index,start_frame in enumerate(chunk_starts,1):
        end_frame=min(total_frames,start_frame+chunk_frames)
        chunk=io.BytesIO()
        with wave.open(chunk,'wb') as output:
            output.setparams(params)
            output.writeframes(frames[start_frame*frame_bytes:end_frame*frame_bytes])
        fields={
            'model':TRANSCRIPTION_MODEL,'response_format':'verbose_json',
            'timestamp_granularities[]':'word','language':'en','temperature':'0'
        }
        payload,ct=multipart_form(fields,chunk.getvalue(),filename='speech_chunk.wav')
        transcription=json.loads(call_api('audio/transcriptions',payload,ct))
        offset=start_frame/params.framerate
        for word in transcription.get('words',[]):
            start=offset+float(word.get('start') or 0)
            end=offset+float(word.get('end') or start)
            all_words.append({'word':word.get('word',''),'start':start,'end':end})
        if on_progress:on_progress(chunk_index,len(chunk_starts))
    return all_words

def realtime_speech(text,voice,style,on_progress=None):
    from websockets.sync.client import connect
    # Reload on every generation so config.json changes take effect without
    # requiring the user to restart the server.
    profile=load_speech_styles().get(style,load_speech_styles()['natural'])
    guidance=profile['instructions']
    # Keep the generated playback speed identical across styles so that
    # differences come from pronunciation, reductions, rhythm, and emotion.
    output_speed=1.0
    blocks=[]; transcript=''; done=False; usage={}
    expected_audio_bytes=max(48000,int(len(text.split())*0.42*48000))
    received_audio_bytes=0
    url=f'wss://api.openai.com/v1/realtime?model={MODEL}'
    with connect(url,additional_headers={'Authorization':'Bearer '+API_KEY},open_timeout=25,close_timeout=8,max_size=15_000_000) as ws:
        # `turn_detection` belongs to `session.audio.input` in the current
        # Realtime API schema.  It is disabled because this endpoint sends a
        # complete text prompt and explicitly triggers one response.
        ws.send(json.dumps({'type':'session.update','session':{
            'type':'realtime',
            'audio':{
                'input':{'turn_detection':None},
                'output':{'format':{'type':'audio/pcm','rate':24000},'voice':voice,'speed':output_speed}
            },
            'output_modalities':['audio']
        }}))
        # Do not send response.create until the session configuration has
        # been accepted.  This also surfaces configuration errors cleanly.
        while True:
            event=json.loads(ws.recv(timeout=60))
            kind=event.get('type','')
            if kind=='error':
                raise RuntimeError(event.get('error',{}).get('message','Realtime API error'))
            if kind=='session.updated':
                break
        # Use an isolated response so generation never uses prior conversation history.
        ws.send(json.dumps({'type':'response.create','response':{
          'conversation':'none','output_modalities':['audio'],
          'instructions':guidance+' Speak only the exact supplied English text; do not add prefaces, explanations, or extra sentences.',
          'input':[{'type':'message','role':'user','content':[{'type':'input_text','text':'Read the following text exactly, with no additions:\n'+text}]}]
        }}))
        for _ in range(10000):
            event=json.loads(ws.recv(timeout=180))
            kind=event.get('type','')
            if kind=='error':raise RuntimeError(event.get('error',{}).get('message','Realtime API error'))
            if kind=='response.output_audio.delta':
                block=base64.b64decode(event['delta']);blocks.append(block);received_audio_bytes+=len(block)
                if on_progress:on_progress(min(0.98,received_audio_bytes/expected_audio_bytes))
            if kind=='response.output_audio_transcript.done':transcript=event.get('transcript','')
            if kind=='response.done':
                response=event.get('response',{})
                if response.get('status')!='completed':
                    raise RuntimeError(str(response.get('status_details') or response.get('status')))
                usage=response.get('usage') or {}
                done=True;break
    if on_progress:on_progress(1.0)
    if not done or not blocks:raise RuntimeError('音声が返されませんでした。')
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000)
        wav.writeframes(b''.join(blocks))
    return buffer.getvalue(),transcript,usage

def token_count(details, key):
    return int((details or {}).get(key) or 0)

def calculate_cost(usage, audio_seconds):
    """Estimate this request from the usage returned by response.done."""
    input_details=usage.get('input_token_details') or {}
    output_details=usage.get('output_token_details') or {}
    input_audio=token_count(input_details,'audio_tokens')
    input_text=token_count(input_details,'text_tokens')
    cached=token_count(input_details,'cached_tokens')
    output_audio=token_count(output_details,'audio_tokens')
    output_text=token_count(output_details,'text_tokens')
    # Keep the estimate honest if an older server omits token details.
    if not any((input_audio,input_text,cached,output_audio,output_text)):
        input_text=int(usage.get('input_tokens') or 0)
        output_audio=int(usage.get('output_tokens') or 0)
    realtime=(input_audio*REALTIME_RATES['input_audio']+
              input_text*REALTIME_RATES['input_text']+
              cached*REALTIME_RATES['cached_input']+
              output_audio*REALTIME_RATES['output_audio']+
              output_text*REALTIME_RATES['output_text'])/1_000_000
    transcription=(audio_seconds/60)*WHISPER_PER_MINUTE
    return {
        'realtime_usd':round(realtime,8),
        'transcription_usd':round(transcription,8),
        'total_usd':round(realtime+transcription,8),
        'currency':'USD',
        'rates_per_1m_tokens':REALTIME_RATES,
        'transcription_model':TRANSCRIPTION_MODEL,
        'transcription_rate_usd_per_minute':WHISPER_PER_MINUTE,
        'usage':usage,
    }

def calculate_text_cost(usage):
    input_tokens=int((usage or {}).get('input_tokens') or 0)
    output_tokens=int((usage or {}).get('output_tokens') or 0)
    input_rate=float(os.environ.get('OPENAI_TEXT_INPUT_USD_PER_MILLION', '0.10'))
    output_rate=float(os.environ.get('OPENAI_TEXT_OUTPUT_USD_PER_MILLION', '0.50'))
    return {
        'model':TEXT_MODEL,
        'input_tokens':input_tokens,
        'output_tokens':output_tokens,
        'usd':round((input_tokens*input_rate+output_tokens*output_rate)/1_000_000,8),
        'rate_version':os.environ.get('OPENAI_PRICE_RATE_VERSION', '2026-10-24-v1'),
        'rates_per_1m_tokens':{'input':input_rate,'output':output_rate},
        'usage':usage or {}
    }

def complete_word_timings(text, timed_words, audio_seconds):
    """Fill gaps in Whisper word timestamps using the original source words."""
    source_words=re.findall(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*", text)
    if not source_words or not timed_words:
        return timed_words
    def norm(value):
        return re.sub(r'[^a-z0-9]', '', str(value or '').lower().replace('’',"'"))
    source_norm=[norm(word) for word in source_words]
    timed_norm=[norm(item.get('word')) for item in timed_words]
    raw_starts=[float(item.get('start') or 0) for item in timed_words]
    if len(raw_starts)>=100:
        reference=statistics.median(raw_starts[:max(20,int(len(raw_starts)*.8))])
        tail_gaps=[raw_starts[i]-raw_starts[i-1] for i in range(max(1,int(len(raw_starts)*.9)),len(raw_starts))]
        reference_gaps=[raw_starts[i]-raw_starts[i-1] for i in range(1,max(2,int(len(raw_starts)*.8)))]
        if tail_gaps and reference_gaps and statistics.median(tail_gaps)<statistics.median(reference_gaps)*.05:
            step=audio_seconds/max(1,len(source_words))
            return [{'word':word,'start':round(i*step,3),'end':round(min(audio_seconds,(i+1)*step),3)} for i,word in enumerate(source_words)]
    anchors={}
    matcher=SequenceMatcher(None,source_norm,timed_norm,autojunk=False)
    for source_start,timed_start,size in matcher.get_matching_blocks():
        for offset in range(size):
            anchors[source_start+offset]=timed_words[timed_start+offset]
    if not anchors:
        step=audio_seconds/max(1,len(source_words))
        return [{'word':word,'start':round(i*step,3),'end':round((i+1)*step,3)} for i,word in enumerate(source_words)]
    starts=[None]*len(source_words); ends=[None]*len(source_words)
    for index,item in anchors.items():
        starts[index]=float(item.get('start') or 0); ends[index]=float(item.get('end') or starts[index])
    anchor_indices=sorted(anchors)
    first=anchor_indices[0]
    lead_step=(starts[first]/(first+1)) if first else audio_seconds/max(1,len(source_words))
    for i in range(first-1,-1,-1): starts[i]=max(0,starts[i+1]-lead_step)
    for left,right in zip(anchor_indices,anchor_indices[1:]):
        gap=right-left
        step=(starts[right]-starts[left])/gap if gap else 0
        for i in range(left+1,right): starts[i]=starts[left]+step*(i-left)
    last=anchor_indices[-1]
    tail_step=(audio_seconds-starts[last])/max(1,len(source_words)-last)
    for i in range(last+1,len(source_words)): starts[i]=starts[i-1]+tail_step
    for i,start in enumerate(starts):
        if ends[i] is None: ends[i]=starts[i+1] if i+1<len(starts) and starts[i+1] is not None else min(audio_seconds,start+0.25)
    return [{'word':word,'start':round(max(0,starts[i]),3),'end':round(min(audio_seconds,ends[i]),3)} for i,word in enumerate(source_words)]



