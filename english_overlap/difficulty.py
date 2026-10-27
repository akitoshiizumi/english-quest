"""Background CEFR assessment jobs with resumable progress."""

from __future__ import annotations

import json
import os

from . import database
from .openai_api import request_json, response_text

MAX_OUTPUT_TOKENS = 512


class DifficultyResponseError(ValueError):
    def __init__(self,message: str,response: dict):
        super().__init__(message)
        self.response=response


def _record_usage(job_id: str,response: dict,*,path=None,allow_missing: bool=False) -> str:
    model=response.get('model',os.environ.get('OPENAI_TEXT_MODEL','gpt-6-luna'))
    usage=response.get('usage')
    if usage is None and allow_missing:
        return model
    usage=usage or {}
    input_tokens=int(usage.get('input_tokens') or 0)
    output_tokens=int(usage.get('output_tokens') or 0)
    estimated=(input_tokens*float(os.environ.get('OPENAI_TEXT_INPUT_USD_PER_MILLION','0.10'))+
               output_tokens*float(os.environ.get('OPENAI_TEXT_OUTPUT_USD_PER_MILLION','0.50')))/1_000_000
    database.add_api_usage(operation='difficulty_assessment',model=model,input_tokens=input_tokens,
                           output_tokens=output_tokens,estimated_usd=estimated,job_id=job_id,path=path)
    return model


def assess_sense(item: dict, *, api_key: str, provider=request_json) -> tuple[dict,dict]:
    model=os.environ.get('OPENAI_TEXT_MODEL','gpt-6-luna')
    schema={'type':'object','additionalProperties':False,'properties':{'level':{'type':'string','enum':['A1','A2','B1','B2','C1','C2']},'evidence':{'type':'string'}},'required':['level','evidence']}
    instructions='Estimate the CEFR level of this English headword only in the supplied Japanese sense and part of speech. Give a concise Japanese reason grounded in frequency, abstraction, and usage. Output JSON only.'
    input_text=json.dumps({'english':str(item['english'])[:160],'meaning':str(item['meaning'])[:240]},ensure_ascii=False)
    payload={'model':model,'instructions':instructions,'input':input_text,'max_output_tokens':MAX_OUTPUT_TOKENS,'text':{'format':{'type':'json_schema','name':'cefr_assessment','strict':True,'schema':schema}}}
    result=provider('responses',payload,api_key=api_key)
    if result.get('status') == 'incomplete':
        reason=(result.get('incomplete_details') or {}).get('reason') or 'unknown reason'
        raise DifficultyResponseError(f'CEFR response was incomplete ({reason}); retry the assessment.',result)
    try:
        assessment=json.loads(response_text(result))
    except (TypeError, json.JSONDecodeError):
        raise DifficultyResponseError('CEFR response contained incomplete or invalid JSON; retry the assessment.',result) from None
    if (not isinstance(assessment,dict) or assessment.get('level') not in {'A1','A2','B1','B2','C1','C2'}
            or not isinstance(assessment.get('evidence'),str)):
        raise DifficultyResponseError('CEFR response did not match the expected assessment fields; retry the assessment.',result)
    return assessment,result


def process_difficulty_job(job_id: str, *, api_key: str, provider=request_json, path=None) -> dict:
    job=database.get_api_job(job_id,path=path)
    if not job or job['job_type'] not in ('difficulty_assessment','automatic_difficulty_assessment'):raise LookupError('Difficulty job not found')
    automatic=job['job_type']=='automatic_difficulty_assessment'
    result=job['result'];assessed=set(result.get('assessed_sense_ids',[]))
    senses=database.senses_for_difficulty(job['payload'].get('sense_ids'),limit=100,path=path)
    for item in senses:
        if item['sense_id'] in assessed or item['difficulty_manual']:
            assessed.add(item['sense_id']);continue
        current=database.get_api_job(job_id,path=path)
        if current['status']=='paused':return current
        if automatic:
            settings=database.get_setting('automatic_difficulty',{'enabled':True,'per_run_limit':10,'daily_budget_usd':0.05},path=path)
            if not settings.get('enabled',True):
                database.update_api_job(job_id,status='paused',error='automatic_paused',result={**result,'assessed_sense_ids':sorted(assessed),'pause_reason':'disabled'},path=path)
                return database.get_api_job(job_id,path=path)
            spent=database.api_usage_spent_today('difficulty_assessment',path=path)
            sample_text=json.dumps({'english':str(item['english'])[:160],'meaning':str(item['meaning'])[:240]},ensure_ascii=False)
            input_chars=len(sample_text)+180
            input_rate=float(os.environ.get('OPENAI_TEXT_INPUT_USD_PER_MILLION','0.10'))
            output_rate=float(os.environ.get('OPENAI_TEXT_OUTPUT_USD_PER_MILLION','0.50'))
            reserve=(input_chars*3*input_rate+MAX_OUTPUT_TOKENS*output_rate)/1_000_000
            budget=float(settings.get('daily_budget_usd',0.05))
            if spent+reserve>budget:
                database.update_api_job(job_id,status='paused',error='daily_budget_limit',result={**result,'assessed_sense_ids':sorted(assessed),'pause_reason':'daily_budget','spent_today_usd':spent,'daily_budget_usd':budget},path=path)
                return database.get_api_job(job_id,path=path)
        try:
            assessment,response=assess_sense(item,api_key=api_key,provider=provider)
        except DifficultyResponseError as ex:
            _record_usage(job_id,ex.response,path=path,allow_missing=True)
            database.update_api_job(job_id,status='failed',error=str(ex),result={**result,'assessed_sense_ids':sorted(assessed)},path=path)
            return database.get_api_job(job_id,path=path)
        except Exception as ex:
            database.update_api_job(job_id,status='failed',error=str(ex),result={**result,'assessed_sense_ids':sorted(assessed)},path=path)
            return database.get_api_job(job_id,path=path)
        model=_record_usage(job_id,response,path=path)
        database.update_difficulty(item['sense_id'],assessment['level'],assessment['evidence'],model=model,path=path)
        assessed.add(item['sense_id'])
        progress={'assessed_sense_ids':sorted(assessed)}
        database.update_api_job(job_id,status='running',completed_items=len(assessed),result=progress,path=path)
    database.update_api_job(job_id,status='completed',completed_items=len(senses),result={'assessed_sense_ids':sorted(assessed)},path=path)
    return database.get_api_job(job_id,path=path)
