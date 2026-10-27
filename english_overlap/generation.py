"""Dataset-grounded sentence and article generation with coverage checks."""

from __future__ import annotations

import json
import os

from .openai_api import request_json, response_text
from .vocabulary import find_usage, phrase_match_text


class VocabularyCoverageError(ValueError):
    def __init__(self, missing: list[str], usage: dict, model: str, request_count: int):
        super().__init__('\u6307\u5b9a\u8a9e\u5f59\u3092\u542b\u307e\u306a\u3044\u751f\u6210\u6587\u304c\u3042\u308a\u307e\u3059: ' + ', '.join(missing))
        self.missing=missing;self.usage=usage;self.model=model;self.request_count=request_count


def generate_vocabulary_sentences(vocabulary: list[dict], *, difficulty: str = '', theme: str = '',
                                  length: str = 'short', generation_mode: str = 'per_vocabulary',
                                  provider=None, api_key: str | None = None, on_progress=None) -> dict:
    if not vocabulary:
        raise ValueError('\u8b1b\u6750\u306b\u4f7f\u3046\u8a9e\u5f59\u3092\u9078\u629e\u3057\u3066\u304f\u3060\u3055\u3044')
    if generation_mode not in ('per_vocabulary','article'):
        raise ValueError('Unsupported generation mode')
    model=os.environ.get('OPENAI_TEXT_MODEL','gpt-6-luna')
    send=provider or (lambda endpoint,payload: request_json(endpoint,payload,api_key=api_key))
    all_sentences=[];groups=[];usages=[];used=set();total_usage={'input_tokens':0,'output_tokens':0};models=[];request_count=0

    def generate_chunk(targets, *, completion=False, previous_article=''):
        nonlocal request_count
        output_key='paragraphs' if generation_mode=='article' else 'sentences'
        schema={'type':'object','additionalProperties':False,'properties':{output_key:{'type':'array','items':{'type':'string'}}},'required':[output_key]}
        if generation_mode=='article':
            instructions='Write one cohesive, natural English practice article using every supplied target phrase. Make the ideas flow as one article rather than a list of example sentences. Return its paragraphs in order in the paragraphs array. '
            if completion: instructions+='Write only a short continuation paragraph that naturally adds the previously missing target phrases to the existing article. '
        else:
            instructions='Write exactly one natural, grammatical English sentence for each supplied vocabulary item, in the same order as the input. Keep each sentence focused on its assigned target; do not combine multiple targets into one sentence. '
        instructions+='For a target ending in a placeholder such as ?, ?, ~, ?, or ..., treat that marker as an open slot, omit the marker, and use the English phrase stem followed by a natural completion. For all other targets, include the target literally or as a common inflection. Do not translate target phrases into Japanese. Keep sentences appropriate for English learners. Return JSON only.'
        if completion and generation_mode=='per_vocabulary': instructions+=' Return exactly one sentence for each supplied missing target in the same order.'
        target_data=[{'vocab_id':item['vocab_id'],'english':item['english'],'match_phrase':phrase_match_text(item['english']),'meaning':item['meaning']} for item in targets]
        request_input={'targets':target_data,'difficulty':difficulty or 'unspecified','theme':theme,'length':length,'generation_mode':generation_mode}
        if previous_article:request_input['existing_article']=previous_article
        prompt={'model':model,'instructions':instructions,'input':json.dumps(request_input,ensure_ascii=False),
                'text':{'format':{'type':'json_schema','name':'practice_'+generation_mode,'strict':True,'schema':schema}}}
        response=send('responses',prompt);request_count+=1
        usage=response.get('usage') or {};total_usage['input_tokens']+=int(usage.get('input_tokens') or 0);total_usage['output_tokens']+=int(usage.get('output_tokens') or 0)
        models.append(response.get('model',model))
        return json.loads(response_text(response)).get(output_key,[])

    def register_usage(paragraphs, targets):
        for text in paragraphs:
            for item in targets:
                matches=find_usage(text,item['english'])
                if matches:
                    used.add(item['vocab_id'])
                    usages.extend({'vocab_id':item['vocab_id'],'sense_id':item.get('sense_id'),
                                   'usage_text':match['text'],'usage_start':match['start'],'usage_end':match['end']} for match in matches)

    if generation_mode=='article':
        paragraphs=generate_chunk(vocabulary)
        missing=[item for item in vocabulary if not any(find_usage(text,item['english']) for text in paragraphs)]
        if missing:
            paragraphs.extend(generate_chunk(missing,completion=True,previous_article='\\n\\n'.join(paragraphs)))
        register_usage(paragraphs,vocabulary)
        missing=[item for item in vocabulary if item['vocab_id'] not in used]
        if missing:raise VocabularyCoverageError([item['english'] for item in missing],total_usage,models[-1] if models else model,request_count)
        groups=[paragraphs];all_sentences.extend(paragraphs)
        if on_progress:on_progress({'groups':groups[:],'sentences':all_sentences[:],'usages':usages[:],'used_vocab_ids':sorted(used),'usage':dict(total_usage),'model':models[-1] if models else model,'request_count':request_count})
    else:
        chunk_size=10
        for start in range(0,len(vocabulary),chunk_size):
            chunk=vocabulary[start:start+chunk_size]
            generated=generate_chunk(chunk)
            assigned={item['vocab_id']:generated[index] for index,item in enumerate(chunk[:len(generated)])}
            missing=[item for item in chunk if item['vocab_id'] not in assigned or not find_usage(assigned[item['vocab_id']],item['english'])]
            if missing:
                completion=generate_chunk(missing,completion=True)
                assigned.update({item['vocab_id']:completion[index] for index,item in enumerate(missing[:len(completion)])})
            final=[assigned[item['vocab_id']] for item in chunk if item['vocab_id'] in assigned]
            register_usage(final,chunk)
            missing=[item for item in chunk if item['vocab_id'] not in assigned or not find_usage(assigned[item['vocab_id']],item['english'])]
            if missing:raise VocabularyCoverageError([item['english'] for item in missing],total_usage,models[-1] if models else model,request_count)
            groups.append(final);all_sentences.extend(final)
            if on_progress:on_progress({'groups':groups[:],'sentences':all_sentences[:],'usages':usages[:],'used_vocab_ids':sorted(used),'usage':dict(total_usage),'model':models[-1] if models else model,'request_count':request_count})
    return {'sentences':all_sentences,'usages':usages,'used_vocab_ids':sorted(used),
            'unused_vocab_ids':[item['vocab_id'] for item in vocabulary if item['vocab_id'] not in used],
            'groups':groups,'model':models[-1] if models else model,'usage':total_usage,'request_count':request_count,'length':length,'generation_mode':generation_mode}
