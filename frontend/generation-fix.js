/* Generation response/error normalization.
   Keep the main UI renderer untouched; this file fixes structured FastAPI
   error details so JavaScript never coerces an object into "[object Object]". */
(function(){
  const originalFetch=window.fetch.bind(window);
  const stringifyDetail=value=>{
    if(value==null)return 'Generation failed.';
    if(typeof value==='string'){
      try{
        const parsed=JSON.parse(value);
        return stringifyDetail(parsed);
      }catch{return value;}
    }
    if(typeof value==='object'){
      if(typeof value.message==='string'&&value.message.trim()){
        const extras=[];
        if(value.deep_analysis?.blockers?.length)extras.push(`Blockers: ${value.deep_analysis.blockers.join('; ')}`);
        if(value.validation?.status&&value.validation.status!=='passed')extras.push(`Verification: ${value.validation.status}`);
        if(value.static_validation?.errors?.length)extras.push(`Validation errors: ${value.static_validation.errors.join('; ')}`);
        return [value.message,...extras].join(' ');
      }
      try{return JSON.stringify(value,null,2);}catch{return String(value);}
    }
    return String(value);
  };

  const originalRunGenerate=window.runGenerate;
  window.runGenerate=async function(kind){
    if(!state.url.trim())return state.error='Enter a GitHub repository URL.',render();
    state.loading=true;state.error='';state.events=[];state.result=null;state.generatedMode=kind;state.dockerPorts={host:null,internal:null};state.tab='artifacts';render();
    const endpoint=kind==='dockerfile'?'/generate/dockerfile':'/generate/docker-compose';
    try{
      const response=await originalFetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repo_url:state.url.trim()})});
      const text=await response.text();
      let payload;
      try{payload=text?JSON.parse(text):{};}catch{throw new Error(text||`Generation failed (${response.status}).`);}
      if(!response.ok){
        const detail=payload?.detail??payload?.message??payload;
        throw new Error(stringifyDetail(detail));
      }
      const base={
        summary:payload.summary,
        languages:payload.stacks?.languages||[],
        frameworks:payload.stacks?.frameworks||[],
        evidence:[],dependency_graph:{},migrations:{},security:{},generated_files:{},
        deployment_ir:payload.deployment_ir,
        static_validation:payload.static_validation,
        deep_analysis:payload.deep_analysis,
        verification:payload.verification,
        deployment_gate:payload.deployment_gate
      };
      if(kind==='dockerfile'){
        if(typeof payload.dockerfile!=='string')throw new Error('Backend returned an invalid Dockerfile payload; expected text.');
        base.generated_files.Dockerfile=payload.dockerfile;
        const detected=detectedPorts(base);state.dockerPorts={host:detected.host,internal:detected.internal};
      }else{
        if(typeof payload.compose!=='string')throw new Error('Backend returned an invalid compose payload; expected text.');
        base.generated_files['compose.yaml']=payload.compose;
      }
      state.result=base;
      state.events=[{
        phase:'generation',
        message:kind==='dockerfile'?'Repository analyzed, stack detected and Dockerfile generated and runtime-verified.':'Repository analyzed and compose configuration generated successfully.',
        status:'done',
        data:{analysis_id:payload.analysis_id,deep_analysis:payload.deep_analysis,verification:payload.verification}
      }];
    }catch(e){state.error=stringifyDetail(e?.message||e||'Generation failed');}
    finally{state.loading=false;render();}
  };
})();
