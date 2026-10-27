(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.EnglishOverlapDistribution=api;
})(typeof globalThis==='object'?globalThis:this,function(){
  const metrics={
    accuracy:{label:'自己評価正解率',kind:'accuracy'},
    attempts:{label:'登場回数',kind:'count',value:item=>item.attempts},
    known:{label:'正解数',kind:'count',value:item=>item.known},
    again:{label:'再学習数',kind:'count',value:item=>item.again}
  };
  const createAccuracyBins=()=>Array.from({length:10},(_,index)=>({label:index===9?'90–100%':`${index*10}–${index*10+9}%`,count:0}));
  const countLabels=['0','1','2','3','4','5','6–10','11–20','21+'];
  function countBinIndex(value){const count=Math.max(0,Math.floor(Number(value)||0));if(count<=5)return count;if(count<=10)return 6;if(count<=20)return 7;return 8;}
  function buildVocabularyDistribution(rows,metricKey){
    const metric=metrics[metricKey]||metrics.accuracy;const items=Array.isArray(rows)?rows.filter(item=>item&&typeof item==='object'):[];
    if(metric.kind==='accuracy'){
      let studied=0,excludedUnstudied=0;
      for(const item of items){const attempts=Number(item.attempts)||0;const rate=Number(item.known_rate);if(attempts<=0||!Number.isFinite(rate)){excludedUnstudied++;continue;}studied++;}
      const bins=createAccuracyBins();
      for(const item of items){const attempts=Number(item.attempts)||0;const rate=Number(item.known_rate);if(attempts>0&&Number.isFinite(rate)){const index=Math.max(0,Math.min(9,Math.floor(Math.max(0,Math.min(1,rate))*10)));bins[index].count++;}}
      return {metric:metricKey,label:metric.label,bins,total:studied,excludedUnstudied};
    }
    const bins=countLabels.map(label=>({label,count:0}));
    for(const item of items)bins[countBinIndex(metric.value(item))].count++;
    return {metric:metricKey,label:metric.label,bins,total:items.length,excludedUnstudied:0};
  }
  return {buildVocabularyDistribution};
});
