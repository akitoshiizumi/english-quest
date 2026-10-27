"""Versioned embedding cache and candidate similarity assessment."""

from __future__ import annotations

import hashlib
import json
import math
import os
import operator
from array import array
from functools import lru_cache
from pathlib import Path

from . import database
from .openai_api import request_json
from .vocabulary import normalize_headword

INPUT_VERSION='english-meaning-v1'


def make_embedding_text(english: str, meaning: str) -> str:
    return f"English: {english.strip()}\nJapanese meaning: {meaning.strip()}"


def embedding_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def fetch_embedding(text: str, *, api_key: str, model: str | None = None, provider=request_json) -> tuple[list[float], str, dict]:
    model=model or os.environ.get('OPENAI_EMBEDDING_MODEL','text-embedding-3-small')
    result=provider('embeddings',{'model':model,'input':text},api_key=api_key)
    return [float(x) for x in result['data'][0]['embedding']], result.get('model',model), result.get('usage',{})


def save_embedding(vocab_id: str, sense_id: int, text: str, vector: list[float], model: str,
                   *, path=None) -> None:
    import sqlite3
    from datetime import datetime, timezone
    with database.connect(path) as conn:
        conn.execute("""INSERT INTO embeddings(vocab_id,sense_id,model,dimensions,input_version,input_hash,vector_json,created_at_utc)
            VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(vocab_id,sense_id,model,input_version) DO UPDATE SET
            dimensions=excluded.dimensions,input_hash=excluded.input_hash,vector_json=excluded.vector_json,created_at_utc=excluded.created_at_utc""",
            (vocab_id,sense_id,model,len(vector),INPUT_VERSION,embedding_hash(text),json.dumps(vector,separators=(',',':')),datetime.now(timezone.utc).isoformat(timespec='seconds')))


def index_missing(*, api_key: str, limit: int = 100, path=None, provider=request_json) -> dict:
    limit=max(1,min(int(limit),100))
    with database.connect(path) as conn:
        rows=conn.execute("""SELECT v.vocab_id,s.sense_id,v.english,s.meaning FROM vocab v JOIN senses s ON s.vocab_id=v.vocab_id
            WHERE trim(s.meaning)<>'' AND NOT EXISTS(SELECT 1 FROM embeddings e WHERE e.vocab_id=v.vocab_id AND e.sense_id=s.sense_id AND e.model=? AND e.input_version=?)
            ORDER BY v.vocab_id,s.sense_index LIMIT ?""",(os.environ.get('OPENAI_EMBEDDING_MODEL','text-embedding-3-small'),INPUT_VERSION,limit)).fetchall()
    if not rows:return {'indexed':0,'remaining':0,'model':os.environ.get('OPENAI_EMBEDDING_MODEL','text-embedding-3-small')}
    model=os.environ.get('OPENAI_EMBEDDING_MODEL','text-embedding-3-small')
    texts=[make_embedding_text(row['english'],row['meaning']) for row in rows]
    result=provider('embeddings',{'model':model,'input':texts},api_key=api_key)
    for row,item,text in zip(rows,result['data'],texts):
        save_embedding(row['vocab_id'],row['sense_id'],text,item['embedding'],result.get('model',model),path=path)
    with database.connect(path) as conn:
        remaining=conn.execute("""SELECT count(*) FROM vocab v JOIN senses s ON s.vocab_id=v.vocab_id WHERE trim(s.meaning)<>'' AND NOT EXISTS(
            SELECT 1 FROM embeddings e WHERE e.vocab_id=v.vocab_id AND e.sense_id=s.sense_id AND e.model=? AND e.input_version=?)""",(model,INPUT_VERSION)).fetchone()[0]
    return {'indexed':len(rows),'remaining':remaining,'model':result.get('model',model),'usage':result.get('usage',{})}


def _sum_products(left, right) -> float:
    sumprod=getattr(math,'sumprod',None)
    return sumprod(left,right) if sumprod else sum(map(operator.mul,left,right))


def _prefix_dimensions(dimensions: int, threshold: float) -> int:
    # Comparing a prefix plus the Cauchy-Schwarz tail bound safely prunes
    # vectors that cannot reach the threshold without changing cosine results.
    fraction=min(1.0,max(0.5,1.0-threshold+0.15))
    return min(dimensions,max(1,math.ceil(dimensions*fraction)))


@lru_cache(maxsize=2)
def _load_similarity_index(db_path: str, model: str, dimensions: int, prefix_dimensions: int,
                          row_count: int, latest_created: str, vector_chars: int):
    del row_count, latest_created, vector_chars  # Cache-key revisions for embedding-only DB changes.
    rows=[]
    with database.connect(db_path) as conn:
        cursor=conn.execute("""SELECT e.vocab_id,e.sense_id,v.english,e.vector_json
            FROM embeddings e JOIN vocab v ON v.vocab_id=e.vocab_id
            WHERE e.model=? AND e.dimensions=? AND e.input_version=?
            ORDER BY e.vocab_id,e.sense_id""",(model,dimensions,INPUT_VERSION))
        for row in cursor:
            vector=json.loads(row['vector_json'])
            if len(vector)!=dimensions:continue
            prefix=array('f',vector[:prefix_dimensions])
            quantization_error=math.sqrt(_sum_products((float(value)-packed for value,packed in zip(vector[:prefix_dimensions],prefix)),
                                                        (float(value)-packed for value,packed in zip(vector[:prefix_dimensions],prefix))))
            tail_norm=math.sqrt(_sum_products(vector[prefix_dimensions:],vector[prefix_dimensions:]))
            norm=math.sqrt(_sum_products(vector,vector))
            rows.append((row['vocab_id'],row['sense_id'],row['english'],prefix,norm,tail_norm,quantization_error))
    return tuple(rows)


def _similarity_index(*, path, model: str, dimensions: int, prefix_dimensions: int):
    db_path=str(Path(path or database.database_path()).resolve())
    with database.connect(db_path) as conn:
        marker=conn.execute("""SELECT count(*),coalesce(max(created_at_utc),''),coalesce(sum(length(vector_json)),0)
            FROM embeddings WHERE model=? AND dimensions=? AND input_version=?""",
            (model,dimensions,INPUT_VERSION)).fetchone()
    return _load_similarity_index(db_path,model,dimensions,prefix_dimensions,int(marker[0]),str(marker[1]),int(marker[2]))


def compare_candidates(candidates: list[dict], *, api_key: str, threshold: float = 0.8,
                       path=None, provider=request_json) -> dict:
    """Compare a bounded set with one embedding request and one dataset scan."""
    if not 0 <= float(threshold) <= 1:raise ValueError('threshold must be between 0 and 1')
    candidates=list(candidates)
    if not candidates:return {'items':[],'model':os.environ.get('OPENAI_EMBEDDING_MODEL','text-embedding-3-small'),'usage':{},'exact_comparisons':0,'dataset_size':0}
    model=os.environ.get('OPENAI_EMBEDDING_MODEL','text-embedding-3-small')
    with database.connect(path) as conn:
        existing={normalize_headword(row['english']):row['vocab_id'] for row in conn.execute('SELECT vocab_id,english FROM vocab')}
    assessments=[None]*len(candidates)
    pending=[]
    texts=[]
    for index,candidate in enumerate(candidates):
        vocab_id=existing.get(normalize_headword(candidate.get('english','')))
        if vocab_id:
            assessments[index]={'candidate_id':candidate.get('candidate_id'),'excluded':True,'reason':'exact_match',
                'matched_vocab_id':vocab_id,'matched_english':None,'similarity':1.0,'threshold':threshold,'model':None,
                'candidate_embedding':None,'input_hash':None,'similar_matches':[]}
        else:
            pending.append(index)
            texts.append(make_embedding_text(candidate.get('english',''),candidate.get('meaning','')))
    usage={}
    if pending:
        result=provider('embeddings',{'model':model,'input':texts},api_key=api_key)
        model=result.get('model',model);usage=result.get('usage',{})
        data=result.get('data') or []
        if len(data)!=len(pending):raise ValueError('Embedding response count does not match candidate count')
        indexed={int(item.get('index',position)):item for position,item in enumerate(data)}
        vectors=[]
        for position in range(len(pending)):
            item=indexed.get(position)
            if item is None:raise ValueError('Embedding response is missing a candidate vector')
            vector=[float(value) for value in item['embedding']]
            if not vector or not all(math.isfinite(value) for value in vector):raise ValueError('Embedding response contains an invalid vector')
            vectors.append(vector)
        dimensions=len(vectors[0])
        if any(len(vector)!=dimensions for vector in vectors):raise ValueError('Embedding vectors have inconsistent dimensions')
        prefix_dimensions=_prefix_dimensions(dimensions,threshold)
        dataset=_similarity_index(path=path,model=model,dimensions=dimensions,prefix_dimensions=prefix_dimensions)
        for pending_position,(candidate_index,vector) in enumerate(zip(pending,vectors)):
            text=texts[pending_position]
            assessments[candidate_index]={'candidate_id':candidates[candidate_index].get('candidate_id'),'excluded':False,
                'reason':None,'matched_vocab_id':None,'matched_english':None,'similarity':None,'threshold':threshold,
                'model':model,'candidate_embedding':vector,'input_hash':embedding_hash(text),'similar_matches':[]}
        if not dataset:
            exact_comparisons=0
            for candidate_index in pending:
                assessments[candidate_index]['reason']='dataset_embeddings_not_indexed'
        else:
            ranked_by_candidate={candidate_index:[] for candidate_index in pending}
            for candidate_index,vector in zip(pending,vectors):
                candidate_norm=math.sqrt(_sum_products(vector,vector))
                if not candidate_norm:continue
                candidate_prefix=vector[:prefix_dimensions]
                candidate_tail_norm=math.sqrt(_sum_products(vector[prefix_dimensions:],vector[prefix_dimensions:]))
                candidate_prefix_norm=math.sqrt(_sum_products(candidate_prefix,candidate_prefix))
                for row_index,row in enumerate(dataset):
                    row_norm=row[4]
                    if not row_norm:continue
                    prefix_dot=_sum_products(candidate_prefix,row[3])
                    upper=(prefix_dot+candidate_prefix_norm*row[6]+candidate_tail_norm*row[5])/(candidate_norm*row_norm)
                    ranked_by_candidate[candidate_index].append((upper,row_index))
                ranked_by_candidate[candidate_index].sort(key=lambda item:(-item[0],dataset[item[1]][0],dataset[item[1]][1]))
            selected_by_candidate={}
            for candidate_index,ranked in ranked_by_candidate.items():
                selected={row_index for upper,row_index in ranked if upper+1e-12>=threshold}
                selected.update(row_index for _,row_index in ranked[:3])
                selected_by_candidate[candidate_index]=selected
            exact_vectors={}

            def load_exact_vectors(row_indices):
                keys={(dataset[row_index][0],dataset[row_index][1]) for row_index in row_indices}
                missing=keys-exact_vectors.keys()
                if not missing:return
                vocab_ids=sorted({vocab_id for vocab_id,_ in missing})
                with database.connect(path) as conn:
                    for offset in range(0,len(vocab_ids),800):
                        chunk=vocab_ids[offset:offset+800]
                        placeholders=','.join('?' for _ in chunk)
                        rows=conn.execute(f"""SELECT e.vocab_id,e.sense_id,e.vector_json FROM embeddings e
                            WHERE e.model=? AND e.dimensions=? AND e.input_version=? AND e.vocab_id IN ({placeholders})""",
                            [model,dimensions,INPUT_VERSION,*chunk]).fetchall()
                        for row in rows:
                            key=(row['vocab_id'],row['sense_id'])
                            if key in missing:exact_vectors[key]=json.loads(row['vector_json'])

            load_exact_vectors({row_index for rows in selected_by_candidate.values() for row_index in rows})
            exact_comparisons=0
            vectors_by_candidate=dict(zip(pending,vectors))
            scored_by_candidate={candidate_index:[] for candidate_index in pending}
            scored_rows_by_candidate={candidate_index:set() for candidate_index in pending}
            while True:
                expand_by_candidate={}
                for candidate_index in pending:
                    vector=vectors_by_candidate[candidate_index]
                    candidate_norm=math.sqrt(_sum_products(vector,vector))
                    for row_index in selected_by_candidate[candidate_index]-scored_rows_by_candidate[candidate_index]:
                        scored_rows_by_candidate[candidate_index].add(row_index)
                        row=dataset[row_index];dataset_vector=exact_vectors.get((row[0],row[1]))
                        if not dataset_vector or not candidate_norm:continue
                        score=_sum_products(vector,dataset_vector)/(candidate_norm*row[4]);exact_comparisons+=1
                        scored_by_candidate[candidate_index].append((score,row[0],row[1],row[2]))
                    ranked_scores=sorted(scored_by_candidate[candidate_index],key=lambda item:(-item[0],item[1],item[2]))
                    nearest=[];seen_words=set()
                    for score,vocab_id,sense_id,english in ranked_scores:
                        word_key=normalize_headword(english)
                        if word_key in seen_words:continue
                        seen_words.add(word_key);nearest.append((score,vocab_id,sense_id,english))
                        if len(nearest)==3:break
                    ranked=ranked_by_candidate[candidate_index]
                    remaining=next(((upper,row_index) for upper,row_index in ranked
                                    if row_index not in scored_rows_by_candidate[candidate_index]),None)
                    if remaining is None:continue
                    if len(nearest)>=3 and remaining[0]+1e-12<min(threshold,nearest[2][0]):continue
                    next_rows=[]
                    for _,row_index in ranked:
                        if row_index not in scored_rows_by_candidate[candidate_index]:
                            next_rows.append(row_index)
                            if len(next_rows)>=64:break
                    if next_rows:expand_by_candidate[candidate_index]=next_rows
                if not expand_by_candidate:break
                for candidate_index,row_indices in expand_by_candidate.items():
                    selected_by_candidate[candidate_index].update(row_indices)
                load_exact_vectors({row_index for rows in expand_by_candidate.values() for row_index in rows})
            for candidate_index in pending:
                ranked_scores=sorted(scored_by_candidate[candidate_index],key=lambda item:(-item[0],item[1],item[2]))
                nearest=[];seen_words=set()
                for score,vocab_id,sense_id,english in ranked_scores:
                    word_key=normalize_headword(english)
                    if word_key in seen_words:continue
                    seen_words.add(word_key);nearest.append((score,vocab_id,sense_id,english))
                    if len(nearest)==3:break
                assessments[candidate_index]['similar_matches']=[
                    {'vocab_id':vocab_id,'english':english,'similarity':score}
                    for score,vocab_id,_,english in nearest]
                best=next((entry for entry in ranked_scores if entry[0]>=threshold),None)
                if best:
                    score,vocab_id,_,english=best
                    assessments[candidate_index].update({'excluded':True,'reason':'cosine_similarity',
                        'matched_vocab_id':vocab_id,'matched_english':english,'similarity':score})
    else:
        exact_comparisons=0;dataset_size=0
    dataset_size=len(dataset) if pending else 0
    return {'items':assessments,'model':model,'usage':usage,'exact_comparisons':exact_comparisons,'dataset_size':dataset_size}


def compare_candidate(candidate: dict, *, api_key: str, threshold: float = 0.8, path=None, provider=request_json) -> dict:
    result=compare_candidates([candidate],api_key=api_key,threshold=threshold,path=path,provider=provider)
    assessment={**result['items'][0],'usage':result['usage']}
    return assessment
