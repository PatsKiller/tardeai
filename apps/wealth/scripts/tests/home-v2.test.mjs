import test from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import Module from 'node:module'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
const app=fileURLToPath(new URL('../../',import.meta.url))
const compiled=await build({stdin:{contents:`import React from 'react';import{renderToStaticMarkup}from'react-dom/server';import{MemoryRouter}from'react-router-dom';import{DrawerProvider}from'./src/components/Drawer';import{HomeTodayPage}from'./src/pages/home/HomeTodayPage';import{HomeOutlookPage}from'./src/pages/home/HomeOutlookPage';import{HomeNeedsPage}from'./src/pages/home/HomeNeedsPage';import{HomePanel,HomeGauge,HomeFact,homeLink}from'./src/pages/home/HomeV2Parts';import{homeV2Model}from'./src/pages/home/homeV2Adapter';export{homeLink,homeV2Model};export function render(kind,props){const C={today:HomeTodayPage,outlook:HomeOutlookPage,needs:HomeNeedsPage,panel:HomePanel,gauge:HomeGauge,fact:HomeFact}[kind];return renderToStaticMarkup(<MemoryRouter><DrawerProvider><C {...props}/></DrawerProvider></MemoryRouter>)}`,resolveDir:app,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',target:'node22',loader:{'.css':'empty'},logLevel:'silent',define:{'process.env.NODE_ENV':'"production"'}})
const m=new Module(path.join(app,'scripts/tests/home-v2-virtual.cjs'));m.filename=path.join(app,'scripts/tests/home-v2-virtual.cjs');m.paths=Module._nodeModulePaths(app);m._compile(compiled.outputFiles[0].text,m.filename)
const{render,homeLink,homeV2Model}=m.exports
const section=extra=>({available:true,source:'Synthetic stored contract',clock:'2040-01-02T03:04:05Z',...extra})
const rows=Array.from({length:12},(_,i)=>({id:`s${i}`,label:`Synthetic issuer ${i}`,symbol:`TEST${i}`,href:`/wealth/portfolio/holdings?hv_query=TEST${i}&hv_account=synthetic`,facts:[{label:'Value',value:'$12.34',state:'grey'}]}))
test('all eleven Today groups render in approved order even when every source is absent',()=>{
 const html=render('today',{}),actual=[...html.matchAll(/data-home-panel="([^"]+)"/g)].map(x=>x[1])
 assert.deepEqual(actual,['stance','tiles','movers','stops','week','news','accounts','setups','watch','brief','pulse'])
 assert.match(html,/not served/);assert.doesNotMatch(html,/\$0|41\.8|1,255,586/)
})
test('Outlook promotes independent engine differences and keeps registry inventory explicitly available on demand',()=>{
 const html=render('outlook',{}),actual=[...html.matchAll(/data-home-panel="([^"]+)"/g)].map(x=>x[1])
 assert.deepEqual(actual,['temperature','regime','engineDifferences','sectors','hedge','week','futures','headlines','marketMovers'])
 assert.match(html,/Regime · separate engine/);assert.match(html,/Open registered findings/);assert.match(html,/aria-expanded="false"/)
 const model=homeV2Model({data:{outlook:{disagreements:section({rows:[{id:'registry:kept',label:'Retained registry conflict'}]}),engineDifferences:section({rows:[{label:'Independent engine risk comparison',facts:[{label:'Engine A',value:'Dated side A'},{label:'Engine B',value:'Dated side B'}]}]})}}})
 const populated=render('outlook',{sections:model.outlook})
 assert.match(populated,/Independent engine risk comparison/);assert.doesNotMatch(populated,/Retained registry conflict/);assert.equal(model.outlook.disagreements.rows[0].id,'registry:kept')
})
test('Needs history is collapsed by default and distinct from current protection and queue groups',()=>{
 const html=render('needs',{sections:{incidents:section({rows:[{label:'Synthetic historic incident'}],totalLabel:'one recorded item'})}})
 assert.match(html,/aria-expanded="false"/);assert.match(html,/history, not current gaps/)
 assert.doesNotMatch(html,/Synthetic historic incident/)
 for(const id of['summary','protect','decide','reentry','fix'])assert.match(html,new RegExp(`data-home-panel="${id}"`))
})
test('failure is isolated: failed stops remain grey while independently served book movers remain visible',()=>{
 const html=render('today',{sections:{stops:{available:false,reason:'Synthetic stops source timed out'},movers:section({rows:[rows[0]]})}})
 assert.match(html,/Synthetic stops source timed out/);assert.match(html,/Synthetic issuer 0/)
 assert.match(html,/Source observation|Source not served|source time not served/)
})
test('zero is preserved and missing is not turned into a value or a directional gain',()=>{
 const zero=render('fact',{fact:{label:'Synthetic zero',value:'0',state:'grey',signed:true}})
 assert.match(zero,/>0<\/span>/);assert.doesNotMatch(zero,/▲|▼|not served/)
 const missing=render('fact',{fact:{label:'Synthetic missing',value:null,state:'green',signed:true}})
 assert.match(missing,/not served/);assert.match(missing,/data-tone="grey"/);assert.doesNotMatch(missing,/▲|▼/)
})
test('signed gains and losses have arrows as well as direction; neutral readings keep neutral state',()=>{
 assert.match(render('fact',{fact:{label:'Move',value:'+$12.34',state:'green',signed:true}}),/▲ \+\$12\.34/)
 assert.match(render('fact',{fact:{label:'Move',value:'−$12.34',state:'red',signed:true}}),/▼ −\$12\.34/)
 assert.match(render('fact',{fact:{label:'VIX',value:'12.34',state:'grey'}}),/data-tone="grey"/)
})
test('compact rows preserve contextual held link and defer remaining rows behind accurately named browsing',()=>{
 const html=render('panel',{id:'movers',title:'Movers',icon:'pulse',section:section({rows}),limit:5})
 assert.equal((html.match(/class="home-v2-row"/g)||[]).length,5)
 assert.match(html,/Browse 10 per page/);assert.doesNotMatch(html,/Show all/);assert.doesNotMatch(html,/Synthetic issuer 5/)
 assert.match(html,/hv_query=TEST0&amp;hv_account=synthetic/)
})
test('unverified news never exposes confident financial explanation; issuer evidence unlocks stored detail',()=>{
 const candidate={label:'Synthetic candidate headline',detail:'Unsupported personal financial conclusion',issuerVerified:false,links:[{label:'Publisher source',href:'https://example.com/story'}],facts:[{label:'Published',value:'2040-01-02T03:04:05Z'}]}
 const html=render('panel',{id:'news',title:'Read first',icon:'news',section:section({rows:[candidate]}),news:true})
 assert.match(html,/Issuer match unverified/);assert.doesNotMatch(html,/Unsupported personal financial conclusion/)
 assert.match(html,/https:\/\/example.com\/story/);assert.match(html,/Published/)
 const verified=render('panel',{id:'news',title:'Read first',icon:'news',section:section({rows:[{...candidate,issuerVerified:true}]}),news:true})
 assert.match(verified,/Unsupported personal financial conclusion/)
})
test('safe links preserve actual symbol/account context and reject APIs, credentials, unsafe and protocol-relative destinations',()=>{
 assert.deepEqual(homeLink('/wealth/portfolio/holdings?hv_query=TEST&hv_account=synthetic'),{href:'/portfolio/holdings?hv_query=TEST&hv_account=synthetic',external:false})
 assert.deepEqual(homeLink('/watch/focus?symbol=TEST'),{href:'/watch/focus?symbol=TEST',external:false})
 assert.deepEqual(homeLink('/v3/watch/intelligence/TEST'),{href:'/v3/watch/intelligence/TEST',external:false,classic:true})
 for(const h of['javascript:alert(1)','//example.com','/api/v2/order','https://user:password@example.com','http://example.com'])assert.equal(homeLink(h),null)
})
test('gauge cannot adopt the mockup assumed policy; only served engine bands render',()=>{
 const absent=render('gauge',{})
 assert.match(absent,/Engine-owned gauge cut-offs/);assert.doesNotMatch(absent,/home-v2-gauge-marker/)
 const actual=render('gauge',{section:section({gauge:{policyVersion:'synthetic-scale@v1',source:'Synthetic engine scale',scoreLabel:'Synthetic engine score',bands:[{width:'35%',state:'green'},{width:'65%',state:'red'}],marker:'27%',ticks:[{position:'35%',label:'Engine boundary'}]}})})
 assert.match(actual,/width:35%/);assert.match(actual,/left:27%/);assert.match(actual,/Engine boundary/)
 const invalid=render('gauge',{section:section({gauge:{policyVersion:'synthetic-scale@v1',source:'Synthetic engine scale',scoreLabel:'bad',bands:[{width:'999%',state:'red'}],marker:'101%',ticks:[]}})})
 assert.match(invalid,/Gauge unavailable/)
})
test('an unzoned source clock stays unknown and cannot become a trustworthy observation',()=>{
 const html=render('panel',{id:'test',title:'Test',icon:'clock',section:section({clock:'2040-01-02T03:04:05',rows:[{label:'Synthetic record'}]})})
 assert.match(html,/source time not served/);assert.doesNotMatch(html,/<time/)
})

const envelope=(data,extra={})=>({ok:true,status:200,data,error:null,lastGood:null,lastGoodAt:null,lastGoodAgeSeconds:null,fetchedAt:'2040-01-02T04:00:00Z',timedOut:false,spec:{path:'/api/v2/wealth/home-v2'},...extra})
test('adapter refuses malformed payloads and preserves transport and nested product failures',()=>{
 for(const value of[null,[],42,'malformed']){const m=homeV2Model(envelope(value));assert.deepEqual(m.today,{});assert.deepEqual(m.outlook,{});assert.deepEqual(m.needs,{})}
 const bad=homeV2Model(envelope({ok:true,data:{ok:false,error:'Synthetic nested source failure',data:{today:{movers:section({rows})}}}}))
 assert.equal(bad.error,'Synthetic nested source failure');assert.deepEqual(bad.today,{})
 const transport=homeV2Model(envelope(null,{ok:false,error:'Synthetic timeout',timedOut:true}));assert.equal(transport.error,'Synthetic timeout')
})
test('adapter accepts server display zero, leaves numeric/null unsupported, and never computes financial totals',()=>{
 const m=homeV2Model(envelope({today:{tiles:section({metrics:[{label:'Portfolio',value:'SERVER TOTAL SENTINEL',state:'grey'},{label:'Zero',value:'0',state:'grey'},{label:'Missing',value:null,state:'green'},{label:'Numeric wire violates display contract',value:0,state:'green'}]}),accounts:section({rows:[{label:'Synthetic A',value:111},{label:'Synthetic B',value:222}]})}}))
 assert.equal(m.today.tiles.metrics[0].value,'SERVER TOTAL SENTINEL');assert.equal(m.today.tiles.metrics[1].value,'0');assert.equal(m.today.tiles.metrics[2].value,null);assert.equal(m.today.tiles.metrics[3].value,null)
 const html=render('today',{sections:m.today});assert.match(html,/SERVER TOTAL SENTINEL/);assert.doesNotMatch(html,/333|111|222/)
})
test('adapter retains source clocks separately from fetched/build clocks and rejects unzoned clocks',()=>{
 const m=homeV2Model(envelope({built_at:'2040-01-02T03:59:59Z',today:{movers:section({clock:'2040-01-01T01:00:00Z',rows:[{label:'Synthetic old observation',clock:'2040-01-01T00:00:00Z',facts:[{label:'Point reading',value:'0',clock:'2040-01-01T00:01:00Z'}]}]}),stops:section({clock:'2040-01-02T03:04:05'})}}))
 assert.equal(m.today.movers.clock,'2040-01-01T01:00:00Z');assert.equal(m.today.movers.rows[0].clock,'2040-01-01T00:00:00Z');assert.equal(m.today.movers.rows[0].facts[0].clock,'2040-01-01T00:01:00Z');assert.equal(m.today.stops.clock,null)
 const html=render('today',{sections:m.today});assert.doesNotMatch(html,/2040-01-02T04:00:00Z|2040-01-02T03:59:59Z/)
})
test('adapter retains last known evidence with an amber failure qualification and original observation clock',()=>{
 const good={today:{movers:section({rows:[{label:'Retained synthetic mover',state:'green',clock:'2040-01-01T01:00:00Z',facts:[{label:'Protection',value:'Active',state:'green',icon:'closed',clock:'2040-01-01T01:00:00Z'}]}]})}}
 const m=homeV2Model(envelope(null,{ok:false,error:'Synthetic current read failed',lastGood:good,lastGoodAt:'2040-01-02T03:50:00Z',lastGoodAgeSeconds:600}))
 assert.equal(m.today.movers.available,true);assert.equal(m.today.movers.state,'amber');assert.equal(m.today.movers.rows[0].state,'grey');assert.equal(m.today.movers.rows[0].facts[0].state,'grey');assert.match(m.today.movers.rows[0].facts[0].qualifier,/last known|current read failed/i);assert.equal(m.today.movers.rows[0].facts[0].clock,'2040-01-01T01:00:00Z');assert.match(m.today.movers.reason,/Synthetic current read failed/);assert.equal(m.today.movers.clock,'2040-01-02T03:04:05Z')
 const html=render('today',{sections:m.today});assert.match(html,/Retained synthetic mover/);assert.match(html,/last known · read failed/);assert.match(html,/Synthetic current read failed/)
})
test('adapter redacts known and opaque account identifiers from every displayed copy while retaining friendly account labels',()=>{
 const key='synthetic_broker_key',opaque='Z123456789',m=homeV2Model(envelope({account_labels:{[key]:'Synthetic family account'},today:{movers:section({reason:key+' '+opaque,source:key,title:key,notes:[key,opaque],metrics:[{label:key,value:opaque,qualifier:key}],rows:[{label:key,detail:opaque,symbol:key,source:key,facts:[{label:key,value:opaque}],links:[{label:key,href:'/wealth/portfolio/holdings?hv_query=TEST'}]}]})}}))
 const html=render('today',{sections:m.today});assert.match(html,/Synthetic family account/);assert.doesNotMatch(html,new RegExp(key+'|'+opaque));assert.match(html,/account withheld/)
})
test('semantic tiles cannot mislabel an unrelated count or a reordered server metric',()=>{
 const needs=render('needs',{sections:{summary:section({metrics:[{label:'Stored queue items',value:'UNRELATED COUNT'}]})}})
 assert.doesNotMatch(needs,/UNRELATED COUNT/);assert.match(needs,/Money decisions today/);assert.match(needs,/not served/)
 const html=render('today',{sections:{tiles:section({metrics:[{label:'Trading record',value:'TRADE RECORD'},{label:'Portfolio',value:'BOOK TOTAL'}]})}})
 assert.match(html,/Portfolio<[^]*?BOOK TOTAL/);assert.match(html,/Trading record<[^]*?TRADE RECORD/)
})

test('source display is Eastern labelled while canonical time stays explicit UTC',()=>{
 const html=render('panel',{id:'clock',title:'Synthetic clock',icon:'clock',section:section()})
 assert.match(html,/dateTime="2040-01-02T03:04:05Z"/);assert.match(html,/Jan 1, 2040, 10:04 PM ET/)
})

test('a metrics-only panel does not claim its absent row layout is missing evidence',()=>{
 const html=render('panel',{id:'temperature',title:'Synthetic engine',icon:'thermometer',section:section({metrics:[{label:'Score',value:'0'}]})})
 assert.match(html,/>0<\/span>/);assert.doesNotMatch(html,/No rows supplied/)
})
