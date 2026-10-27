(function(){
  'use strict';
  const player=document.getElementById('player');
  if(!player)return;
  let context=null,sending=false;
  const pending=[];
  function currentMaterial(){return document.body.dataset.materialId||document.getElementById('savedList')?.value||'legacy-overlap';}
  function currentContext(){
    const materialId=currentMaterial();
    if(!context||context.materialId!==materialId){
      if(context)flush(context);
      context={materialId,sessionId:null,sessionPromise:null,lastTime:null,seconds:0,sentences:0};
    }
    return context;
  }
  function ensureSession(state){
    if(!state.sessionPromise)state.sessionPromise=(async()=>{
      const response=await fetch('/api/overlap/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({material_id:state.materialId}),keepalive:true});
      if(!response.ok)throw new Error('Could not start overlap session');
      state.sessionId=(await response.json()).session_id;return state.sessionId;
    })().catch(error=>{state.sessionPromise=null;throw error;});
    return state.sessionPromise;
  }
  function payload(job){return {session_id:job.state.sessionId,material_id:job.state.materialId,duration_seconds:job.seconds,completed_sentences:job.sentences,idempotency_key:job.key};}
  async function sendPending(){
    if(sending)return;sending=true;
    try{
      while(pending.length){
        const job=pending[0];await ensureSession(job.state);
        const response=await fetch('/api/overlap/activity',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload(job)),keepalive:true});
        if(!response.ok)throw new Error('Could not save overlap activity');
        pending.shift();window.dispatchEvent(new CustomEvent('english-overlap-activity-saved'));
      }
    }catch(_){/* Keep the same idempotency key and retry on the next flush. */}
    finally{sending=false;}
  }
  function flush(state=context){
    if(state&&(state.seconds>=.2||state.sentences>0)){
      pending.push({state,seconds:state.seconds,sentences:state.sentences,key:crypto.randomUUID()});
      state.seconds=0;state.sentences=0;
    }
    void sendPending();
  }
  player.addEventListener('play',()=>{const state=currentContext();state.lastTime=player.currentTime;ensureSession(state).catch(()=>{});void sendPending();});
  player.addEventListener('timeupdate',()=>{
    const state=currentContext();
    const current=player.currentTime;
    if(player.seeking||(player.paused&&!player.ended)){state.lastTime=null;return;}
    if(state.lastTime!==null){const delta=current-state.lastTime;if(delta>0&&delta<=1.5)state.seconds+=delta/Math.max(.2,player.playbackRate);}
    state.lastTime=current;
    if(state.seconds>=10)flush(state);
  });
  window.addEventListener('english-overlap-sentence-completed',event=>{
    const state=currentContext();
    if(event.detail?.materialId!==state.materialId)return;
    state.sentences++;flush(state);
  });
  player.addEventListener('seeking',()=>{if(context)context.lastTime=null;});
  player.addEventListener('seeked',()=>{if(context)context.lastTime=player.currentTime;});
  player.addEventListener('waiting',()=>{if(context)context.lastTime=null;});
  player.addEventListener('playing',()=>{currentContext().lastTime=player.currentTime;});
  player.addEventListener('pause',()=>{if(context)context.lastTime=null;flush();});
  player.addEventListener('ended',()=>{if(context)context.lastTime=null;flush();});
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')flush();});
  window.addEventListener('pagehide',()=>{
    flush();
    for(const job of pending){
      if(!job.state.sessionId)continue;
      navigator.sendBeacon('/api/overlap/activity',new Blob([JSON.stringify(payload(job))],{type:'application/json'}));
    }
  });
})();
