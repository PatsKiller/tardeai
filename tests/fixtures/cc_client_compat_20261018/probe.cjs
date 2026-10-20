// Real reader/components; network hooks and unrelated UI primitives are faked.
const fs = require('node:fs')
const path = require('node:path')
const zlib = require('node:zlib')
const root = process.env.CC_READER_ROOT
const area = __dirname
const app = path.join(root, 'apps/command-center-v3')
const esbuild = require(require.resolve('esbuild', {paths:[app]}))
const fixtures = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(area,'observations.json.gz'))))
const plugins = [{name:'fake-effects-only',setup(build){
  build.onResolve({filter:/^(react|react-dom\/server|react\/jsx-runtime)$/},a=>({path:require.resolve(a.path,{paths:[app]})}))
  build.onResolve({filter:/hooks\/useApi$/},()=>({path:'api',namespace:'fake'}))
  build.onResolve({filter:/components\/primitives$/},()=>({path:'primitives',namespace:'fake'}))
  build.onResolve({filter:/^react-router-dom$/},()=>({path:'router',namespace:'fake'}))
  build.onResolve({filter:/SchedulerOperations$/},()=>({path:'other',namespace:'fake'}))
  build.onLoad({filter:/.*/,namespace:'fake'},a=>({loader:'js',resolveDir:area,contents:{
    api:`export const useApi=p=>globalThis.__hook(p);`,
    primitives:`import {createElement as h} from 'react';export const Chip=({children,tone,...p})=>h('span',{'data-tone':tone,title:p.title},children);export const ChipRow=({children})=>h('div',null,children);export const SortHeader=({children})=>h('th',null,children);export const useSort=(rows,sort)=>({rows,sort,toggle:()=>{}});`,
    router:`export const useSearchParams=()=>[new URLSearchParams('tab=events'),()=>{}];`,
    other:`export default function Other(){return null}`,
  }[a.path]}))
}}]
const entry=`
import {createElement as h} from 'react';import {renderToStaticMarkup as render} from 'react-dom/server';
import Today from '${app}/src/pages/N8nToday.tsx';import Page from '${app}/src/pages/CoordinationPage.tsx';
import {projectCoordination} from '${app}/src/lib/coordinationEvents.ts';import {projectOutbox} from '${app}/src/lib/outboxProjection.ts';
import OldToday from './old/src/pages/N8nToday.tsx';import OldPage from './old/src/pages/CoordinationPage.tsx';
import {projectCoordination as oldCoord} from './old/src/lib/coordinationEvents.ts';import {projectOutbox as oldOutbox} from './old/src/lib/outboxProjection.ts';
export {projectCoordination,projectOutbox,oldCoord,oldOutbox};export const today=()=>render(h(Today));export const page=()=>render(h(Page));export const oldToday=()=>render(h(OldToday));export const oldPage=()=>render(h(OldPage));
`
async function main(){
 const out=await esbuild.build({stdin:{contents:entry,sourcefile:'probe.tsx',loader:'tsx',resolveDir:area},write:false,bundle:true,format:'cjs',platform:'node',jsx:'automatic',plugins,define:{__CC_BUNDLE_SOURCE_SHA__:JSON.stringify('7af14c7782cf7ab0cba261cc25e6789fe810b092'),__ANALYST_UI_VERSION__:JSON.stringify('fixture+loaded'),__BUILD_DATE__:JSON.stringify('2026-10-18')}})
 const Module=require('node:module');const m=new Module(path.join(area,'probe-built.cjs'));m.filename=path.join(area,'probe-built.cjs');m.paths=module.paths;m._compile(out.outputFiles[0].text,m.filename);const r=m.exports
 Date.now=()=>fixtures.nowMs
 const hook=(data,opts={})=>({data,loading:false,error:null,transport:'OK',stale:false,...opts});let requests=[]
 const setToday=(data,opts={})=>{globalThis.__hook=p=>{requests.push(p);return hook(data,opts)}}
 const setPage=(data,opts={})=>{globalThis.__hook=p=>{requests.push(p);return p.includes('/outbox?')?hook(data,opts):p.includes('/events?')?hook(p.includes('source=runs')?fixtures.runsFull:fixtures.eventsFull):hook(null)}}
 const oldOnly=fn=>{const before=requests;requests=[];const value=fn();requests=before;return value}
 setToday(fixtures.todayMissing);const unavailable=r.today();const oldUnavailable=oldOnly(r.oldToday)
 setToday(null,{error:'HTTP 426',transport:'ERROR'});const rejected=r.today();const oldRejected=oldOnly(r.oldToday)
 setToday(fixtures.legacyToday);const legacyToday=r.today()
 setPage(fixtures.outboxFull,{error:'HTTP500',stale:true,transport:'RETAINED'});const retainedPage=r.page();const oldRetainedPage=oldOnly(r.oldPage)
 const opts={nowMs:fixtures.nowMs};const result={unavailable,rejected,legacyToday,retainedPage,requests,
  coordination:r.projectCoordination(fixtures.eventsFull,opts),outbox:r.projectOutbox(fixtures.outboxFull,{...opts,error:true,stale:true}),
  legacyCoordination:r.projectCoordination(fixtures.legacyEvents,opts),legacyOutbox:r.projectOutbox(fixtures.legacyOutbox,opts),
  old:{unavailable:oldUnavailable,rejected:oldRejected,retainedPage:oldRetainedPage,coordination:r.oldCoord(fixtures.eventsFull,opts),outbox:r.oldOutbox(fixtures.outboxFull)},
 }
 process.stdout.write(JSON.stringify(result))
}
main().catch(e=>{console.error(e);process.exitCode=1})
