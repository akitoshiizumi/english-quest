(function(){
  'use strict';
  const player=document.getElementById('player');
  if(!player)return;
  let sessionId=null,materialId=null,lastTime=null,activeSeconds=0;
  function currentMaterial(){return document.body.dataset.materialId||document.getElementById('savedList')?.value||'legacy-overlap';}
  async function ensureSession(){
    const nextMaterial=currentMaterial();
    if(sessionId&&nextMaterial===materialId)return;
    sessionId=null;materialId=nextMaterial;
    const response=await fetch('/api/overlap/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({material_id:materialId})});
    if(!response.ok)throw new Error('Could not start overlap session');
    sessionId=(await response.json()).session_id;
  }
  async function flush(){
    if(!sessionId||activeSeconds<0.2)return;
    const duration=activeSeconds;activeSeconds=0;
    const body=JSON.stringify({session_id:sessionId,material_id:materialId,duration_seconds:duration,idempotency_key:crypto.randomUUID()});
    try{const response=await fetch('/api/overlap/activity',{method:'POST',headers:{'Content-Type':'application/json'},body,keepalive:true});if(response.ok)window.dispatchEvent(new CustomEvent('english-overlap-activity-saved'));}catch(_){}
  }
  player.addEventListener('play',()=>{lastTime=player.currentTime;ensureSession().catch(()=>{});});
  player.addEventListener('timeupdate',()=>{
    const current=player.currentTime;
    if(lastTime!==null){const delta=current-lastTime;if(delta>0&&delta<=1.5)activeSeconds+=delta/Math.max(.2,player.playbackRate);}
    lastTime=current;
    if(activeSeconds>=10)flush();
  });
  player.addEventListener('seeking',()=>{lastTime=null;});
  player.addEventListener('seeked',()=>{lastTime=player.currentTime;});
  player.addEventListener('waiting',()=>{lastTime=null;});
  player.addEventListener('playing',()=>{lastTime=player.currentTime;});
  player.addEventListener('pause',()=>{lastTime=null;flush();});
  player.addEventListener('ended',()=>{lastTime=null;flush();});
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')flush();});
  window.addEventListener('pagehide',()=>{
    if(!sessionId||activeSeconds<.2)return;
    const data=new Blob([JSON.stringify({session_id:sessionId,material_id:materialId,duration_seconds:activeSeconds,idempotency_key:crypto.randomUUID()})],{type:'application/json'});
    navigator.sendBeacon('/api/overlap/activity',data);activeSeconds=0;
  });
})();
