// Actual queue/desk renders: a settled failure must never advertise loading.
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
process.env.NODE_ENV = 'production' // SSR render-only fixture; avoids development-only layout-effect warnings.
const require=createRequire(import.meta.url), ts=require('typescript')
for(const ext of ['.ts','.tsx']) require.extensions[ext]=(module,file)=>module._compile(ts.transpileModule(readFileSync(file,'utf8'),{
  fileName:file, compilerOptions:{jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,esModuleInterop:true},
}).outputText,file)
require.extensions['.css']=()=>{}
const React=require('react'), {renderToStaticMarkup}=require('react-dom/server'), {MemoryRouter}=require('react-router-dom')
let fixture={data:null,error:'',refresh(){}}
require('./operatorApprovals.ts').useGovernance=()=>fixture
let apiFixture={data:null,error:null,loading:false,refetch(){}}
require('../hooks/useApi.ts').useApi=()=>apiFixture
const {default:Approvals}=require('../pages/ApprovalsHub.tsx')
const {default:DeskBoard}=require('../components/DeskBoard.tsx')
const render=component=>renderToStaticMarkup(React.createElement(MemoryRouter,null,component))
const queue={items:[],pending_count:0,known_pending_count:0,complete:true,gaps:[],as_of:'2026-11-04T15:00:00Z',recent:[],filtered_count:0,offset:0}
let passed=0,failed=0
const cases=[
 ['queue loading',{data:null,error:'',loading:true},html=>{assert.match(html,/Loading.*approval/i);assert.doesNotMatch(html,/approval queue is unavailable/i)}],
 ['queue failed',{data:null,error:'Synthetic source unavailable'},html=>{assert.match(html,/approval queue is unavailable/i);assert.match(html,/Try again/);assert.doesNotMatch(html,/Loading the latest queue|Loading approvals/)}],
 ['queue ready',{data:queue,error:''},html=>{assert.match(html,/0 waiting for review/);assert.doesNotMatch(html,/Queue unavailable|Loading approvals/)}],
 ['queue partial',{data:{...queue,pending_count:null,complete:false,gaps:[{source:'synthetic',reason:'not loaded'}]},error:''},html=>assert.match(html,/total is not yet known/i)],
]
for(const[name,state,check]of cases){try{fixture={...state,refresh(){}};check(render(React.createElement(Approvals)));passed++}catch(e){failed++;console.error(`FAIL ${name}: ${e.message.split('\n')[0]}`)}}
for(const state of [{data:null,error:null,loading:true},{data:null,error:'synthetic refusal',loading:false},{data:null,error:null,loading:false}]){
 try{apiFixture={...state,refetch(){}};const html=render(React.createElement(DeskBoard,{desk:'synthetic',title:'Synthetic',purpose:'fixture',tabs:[{id:'one',label:'One'}],classicHref:'/synthetic',testId:'synthetic'}));
  if(state.loading){assert.match(html,/Loading.*Synthetic/i);assert.doesNotMatch(html,/Synthetic.*unavailable/i)}
  else{assert.match(html,state.error?/Synthetic.*unavailable/i:/Synthetic.*could not be read/i);assert.match(html,/Try again/);assert.doesNotMatch(html,/Loading the desk projection/)}passed++
 }catch(e){failed++;console.error(`FAIL desk loading=${state.loading} error=${state.error}: ${e.message.split('\n')[0]}`)}
}
console.log(`approvalQueueState actual renders: ${passed} passed, ${failed} failed`)
process.exitCode=failed?1:0
