const {createRequire}=require('node:module');
const fs=require('node:fs');const assert=require('node:assert/strict');const path=require('node:path');
const root=process.env.COMMS_REVIEW_ROOT;
if(!root || !path.isAbsolute(root))throw new Error('absolute scratch/source review root required');
const app=path.join(root,'apps/command-center-v3');
const deps=process.env.COMMS_REVIEW_DEPS || app;
const req=createRequire(path.join(deps,'package.json'));
(async()=>{
 const {outputFiles}=await req('esbuild').build({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import {MemoryRouter} from 'react-router-dom';import View from './src/pages/CommunicationsHub';createRoot(document.getElementById('root')).render(<MemoryRouter><View/></MemoryRouter>);`,resolveDir:app,loader:'tsx'},nodePaths:[path.join(deps,'node_modules')],bundle:true,write:false,jsx:'automatic',platform:'browser',define:{'process.env.NODE_ENV':'"test"'}});
 const browser=await req('@playwright/test').chromium.launch({headless:true});const results=[];
 try {for(const scenario of ['aggregate','unavailable','retained','recovery','no-external-effects']){
  const page=await browser.newPage();let external=0;await page.route('**/*',r=>{external++;return r.abort()});await page.setContent('<div id="root"></div>');
  await page.evaluate(initial=>{window.summaryCalls=[];window.deliveryCalls=[];window.allCalls=[];window.nextStatus=initial;window.fetch=async(input,opts)=>{
    const url=String(input).split('?')[0];window.allCalls.push({url,method:opts?.method||'GET'});const summary=url.endsWith('/deliveries/summary');const delivery=url.endsWith('/deliveries');
    if(summary)window.summaryCalls.push(window.nextStatus);if(delivery)window.deliveryCalls.push(window.nextStatus);
    const status=(summary||delivery)?window.nextStatus:200;
    const observedAt=new Date().toISOString();
    const data=summary?{schema:'CommunicationsDeliverySummary@v1',ok:true,status:'OK',source:'db',basis:'server_side_aggregate',total:1234,unsettled:17,failed:9,oldest_unsettled_age_s:600,as_of:observedAt,coverage:{scope:'all_retained_rows',complete:true,window_start:'2026-01-01T00:00:00Z',window_end:observedAt}}:{events:[],deliveries:delivery?Array.from({length:500},(_,i)=>({delivery_id:String(i),status:'DELIVERED'})):[],subjects:[],subscriptions:[],receipts:[],delivery_owned:true};
    return new Response(JSON.stringify(status===200?data:{retry_after_sec:60}),{status,headers:{'Content-Type':'application/json'}});
  }},scenario==='unavailable'?503:200);
  await page.addScriptTag({content:outputFiles[0].text});await page.waitForFunction(()=>window.deliveryCalls.length>=1);await page.waitForTimeout(150);
  if(scenario==='retained'||scenario==='recovery'){
   await page.evaluate(()=>{window.nextStatus=503;window.dispatchEvent(new Event('cc-v3-api-recover'))});await page.waitForFunction(()=>window.deliveryCalls.length>=2);await page.waitForTimeout(150);
   if(scenario==='recovery'){await page.evaluate(()=>{window.nextStatus=200;window.dispatchEvent(new Event('cc-v3-api-recover'))});await page.waitForFunction(()=>window.deliveryCalls.length>=3);await page.waitForTimeout(150);}
  }
  const text=await page.locator('body').innerText();const calls=await page.evaluate(()=>({summary:window.summaryCalls,delivery:window.deliveryCalls,all:window.allCalls}));
  try{
   if(scenario==='aggregate'||scenario==='recovery'){assert.match(text,/deliveries 1234/);assert.match(text,/all retained rows/i);assert.doesNotMatch(text,/delivery health (UNAVAILABLE|STALE)/);}
   if(scenario==='unavailable'){assert.match(text,/delivery health UNAVAILABLE/);assert.doesNotMatch(text,/un-settled 0/);}
   if(scenario==='retained'){assert.match(text,/delivery health STALE/);assert.match(text,/last good/i);}
   assert.equal(external,0);assert(calls.all.every(c=>c.method==='GET'));results.push({scenario,passed:true,calls});
  }catch(e){if(e.name!=='AssertionError')throw e;results.push({scenario,passed:false,assertion:e.message,calls,text});}
  await page.close();
 }}finally{await browser.close()}
 const result={root,actual_component:true,actual_hook:true,live_requests:false,results};if(process.env.COMMS_REVIEW_RESULT)fs.writeFileSync(process.env.COMMS_REVIEW_RESULT,JSON.stringify(result,null,2),{flag:'wx'});console.log(JSON.stringify(results.map(({text,...r})=>r)));process.exitCode=results.some(r=>!r.passed)?1:0;
})().catch(e=>{console.error(e);process.exitCode=2});
