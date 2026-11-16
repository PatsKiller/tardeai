import test from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import Module from 'node:module'
import {fileURLToPath} from 'node:url'
import path from 'node:path'
const app=fileURLToPath(new URL('../',import.meta.url))
const output=await build({stdin:{contents:`import React from 'react';import{renderToStaticMarkup}from'react-dom/server';import{MemoryRouter}from'react-router-dom';import{DrawerProvider}from'./src/components/Drawer';import{HomePanel,HomeRowEvidence,HomeStoredNarrative,selectHomeRows,homeLink}from'./src/pages/home/HomeV2Parts';import{HomeNeedsPage}from'./src/pages/home/HomeNeedsPage';import{HomeOutlookPage}from'./src/pages/home/HomeOutlookPage';import{homeV2Model}from'./src/pages/home/homeV2Adapter';export{selectHomeRows,homeLink,homeV2Model};export function render(kind,props){const C={panel:HomePanel,evidence:HomeRowEvidence,narrative:HomeStoredNarrative,needs:HomeNeedsPage,outlook:HomeOutlookPage}[kind];return renderToStaticMarkup(<MemoryRouter><DrawerProvider><C {...props}/></DrawerProvider></MemoryRouter>)}`,resolveDir:app,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',target:'node22',loader:{'.css':'empty'},logLevel:'silent',define:{'process.env.NODE_ENV':'"production"'}})
const module=new Module(path.join(app,'tests/home-corrective-virtual.cjs'));module.filename=path.join(app,'tests/home-corrective-virtual.cjs');module.paths=Module._nodeModulePaths(app);module._compile(output.outputFiles[0].text,module.filename)
const{render,selectHomeRows,homeV2Model,homeLink}=module.exports
const at='2040-01-02T03:04:05Z',built='2040-01-02T03:10:00Z'
const section=extra=>({available:true,state:'amber',source:'Synthetic contract',clock:at,...extra})
const payload=extra=>({schema:'WealthHome@v2',...extra})
const adapt=(data,extra={})=>homeV2Model({data:{ok:true,data},...extra})
const findings=Array.from({length:200},(_,i)=>({id:'finding:'+i,version:'3',label:'Specific finding '+i,summary:'Source condition '+i,detail:'Registered clearance '+i,category:i===0?'CONFLICT':i<28?'GATE':'DATA_ERROR',source:i%2?'Synthetic engine A':'Synthetic engine B',state:'amber',facts:[{label:'Engine claim',value:'claim '+i}],owner:'Synthetic review owner'}))
test('200 retained findings render a small real DOM and expose scoped accessible browsing',()=>{
 const html=render('panel',{id:'dataQuality',title:'Data quality',icon:'gear',section:section({rows:findings,unit:'registered findings',totalCount:200,coverage:'200 retained; source cap200, completeness unproven'})})
 assert.equal((html.match(/data-home-record="true"/g)||[]).length,6)
 assert.doesNotMatch(html,/Specific finding 199/)
 assert.match(html,/Find Data quality/);assert.match(html,/Data quality category/);assert.match(html,/Data quality source/);assert.match(html,/Next Data quality page/)
 assert.match(html,/1–6 of 200 served registered findings/);assert.match(html,/source cap200/)
})
test('all 200 records remain reachable with at most ten DOM rows per browse page',()=>{
 const visited=[]
 for(let page=0;page<20;page++){const selected=selectHomeRows(findings,{page,pageSize:10});assert.equal(selected.visible.length,10);visited.push(...selected.visible.map(r=>r.id))}
 assert.equal(new Set(visited).size,200);assert.deepEqual(visited,findings.map(r=>r.id))
 assert.equal(selectHomeRows(findings,{pageSize:200}).visible.length,10)
 assert.equal(selectHomeRows(findings,{page:999,pageSize:10}).page,19)
})
test('category populations remain 27 gates/172 data errors/one conflict; UI does not deduplicate same-category identities',()=>{
 assert.equal(selectHomeRows(findings,{category:'GATE'}).total,27)
 assert.equal(selectHomeRows(findings,{category:'DATA_ERROR'}).total,172)
 assert.equal(selectHomeRows(findings,{category:'CONFLICT'}).total,1)
 const distinct=[...findings,{...findings[1],id:'finding:distinct',version:'4'}]
 assert.equal(selectHomeRows(distinct,{category:'GATE'}).total,28)
})
test('identity, detail, owner and facts are searchable across every retained page with independent source/category filters',()=>{
 assert.equal(selectHomeRows(findings,{query:'claim 199'}).visible[0].id,'finding:199')
 assert.equal(selectHomeRows(findings,{query:'finding:199',category:'DATA_ERROR',source:'Synthetic engine A'}).total,1)
 assert.equal(selectHomeRows(findings,{query:'finding:199',category:'GATE'}).total,0)
 assert.equal(selectHomeRows(findings,{query:'Specific finding 199',source:'Synthetic engine B'}).total,0)
 assert.equal(selectHomeRows(findings,{query:'review owner'}).total,200)
 assert.equal(selectHomeRows(findings,{}).total,200)
})
test('cards use explicit summary facts and lazy drawers retain full reasons, metadata, all facts and distinct clocks',()=>{
 const row={...findings[199],clock:at,buildClock:built,reason:'Specific contract boundary',facts:[{label:'Public summary',value:'Summary'},{label:'Detailed missing source',value:null,qualifier:'Expected exact field unavailable'},{label:'Other engine',value:'Retained claim',clock:at}],summaryFacts:[{label:'Public summary',value:'Summary'}]}
 const card=render('panel',{id:'findings',title:'Findings',icon:'warning',section:section({rows:[row]})})
 assert.match(card,/Public summary/);assert.doesNotMatch(card,/Detailed missing source|Expected exact field unavailable|Other engine/)
 const detail=render('evidence',{row,section:section({coverage:'Partial retained population'})})
 for(const s of['finding:199','Version','Specific contract boundary','Detailed missing source','Expected exact field unavailable','Other engine','Partial retained population',at,built])assert.ok(detail.includes(s),s)
})
test('canonical task lists and position inventory stay separate with explicit units; no frontend queue recount',()=>{
 const tasks=Array.from({length:9},(_,i)=>({id:'task:'+i,label:'Review task '+i,href:'/v3/approvals/review-'+i,category:'protect'}))
 const positions=Array.from({length:25},(_,i)=>({id:'position:'+i,label:'Position observation '+i}))
 const model=adapt(payload({needs:{summary:section({metrics:[{label:'Protect money',value:'9'},{label:'Decide',value:'1'},{label:'Fix system',value:'0'},{label:'Queue freshness',value:null}]}),protect:section({rows:tasks,unit:'task groups',populationLabel:'Stored task groups',totalCount:9}),protectionInventory:section({rows:positions,unit:'account positions',populationLabel:'Position inventory, not tasks',totalCount:25})}}))
 assert.equal(model.needs.protect.rows.length,9);assert.equal(model.needs.protectionInventory.rows.length,25)
 const html=render('needs',{sections:model.needs})
 assert.match(html,/1–6 of 9 served task groups/);assert.match(html,/1–6 of 25 served account positions/)
 assert.match(html,/Re-entry watch/);assert.doesNotMatch(html,/Since you were stopped out/)
 assert.equal(model.needs.summary.metrics.find(f=>f.label==='Protect money').value,'9')
 assert.equal(model.needs.summary.metrics.find(f=>f.label==='Fix system').value,'0')
 assert.equal(model.needs.summary.metrics.find(f=>f.label==='Queue freshness').value,null)
})
test('separated conflicts render distinct truthful sections with engine details instead of a 200-card disagreement group',()=>{
 const model=adapt(payload({outlook:{disagreements:section({rows:findings.filter(r=>r.category==='CONFLICT')}),gates:section({title:'Policy gates',rows:findings.filter(r=>r.category==='GATE')}),dataQuality:section({title:'Data-quality findings',rows:findings.filter(r=>r.category==='DATA_ERROR')})}}))
 assert.equal(model.outlook.disagreements.rows.length,1);assert.equal(model.outlook.gates.rows.length,27);assert.equal(model.outlook.dataQuality.rows.length,172)
 const html=render('outlook',{sections:model.outlook});assert.equal((html.match(/data-home-record="true"/g)||[]).length,13)
 assert.match(html,/Policy gates/);assert.match(html,/Data-quality findings/)
})
test('farther-out retained dates cannot leak into the near-term week rows and have separate findable evidence',()=>{
 const near={id:'near',label:'Near event'},later={id:'later',label:'Far event'}
 const model=adapt(payload({today:{week:section({rows:[near],recordedUpcoming:[later],windowLabel:'Jan1–Jan8 ET'})}}))
 assert.deepEqual(model.today.week.rows.map(r=>r.id),['near'])
 assert.deepEqual(model.today.recordedUpcoming.rows.map(r=>r.id),['later'])
 assert.match(model.today.recordedUpcoming.title,/outside week window/)
 assert.equal(model.today.week.windowLabel,'Jan1–Jan8 ET')
})
test('unsupported schemas remain scoped errors with no interpretation of unknown payload financial fields',()=>{
 const model=adapt({schema:'WealthHome@v999',today:{tiles:section({metrics:[{label:'Portfolio',value:'$987.65'}]})}})
 assert.match(model.error,/Unsupported Home schema/);assert.deepEqual(model.today,{})
 const absent=adapt(payload({today:{week:{available:false,reason:'Calendar not served'}}}))
 assert.equal(absent.today.week.available,false);assert.match(absent.today.week.reason,/Calendar not served/)
})
test('retained failed-read facts, compact summaries and rows turn grey without losing source/build clocks',()=>{
 const retained=payload({needs:{protect:section({buildClock:built,rows:[{label:'Active record',state:'green',clock:at,summaryFacts:[{label:'Coverage',value:'1.25 shares',state:'green'}],facts:[{label:'Coverage',value:'1.25 shares',state:'green'}]}]})}})
 const model=homeV2Model({data:null,lastGood:{ok:true,data:retained},error:'Synthetic timeout'})
 const row=model.needs.protect.rows[0]
 assert.equal(row.state,'grey');assert.equal(row.facts[0].state,'grey');assert.equal(row.summaryFacts[0].state,'grey')
 assert.match(row.summaryFacts[0].qualifier,/Last known/);assert.equal(row.clock,at);assert.equal(model.needs.protect.buildClock,built)
})
test('supported review owners use native Classic anchors; unsafe and unbuilt review destinations stay rejected',()=>{
 for(const href of['/v3/health','/v3/health?tab=jobs','/v3/approvals','/v3/approvals/review-7','/v3/watch?conflict=synthetic%3A7','/v3/ops/jobs-n8n?tab=quality&lane=synthetic','/v3/risk','/v3/trading?tab=Proposals','/v3/portfolio?tab=Redeploy','/v3/system','/v3/coordination','/v3/agents','/v3/intelligence?tab=research'])assert.deepEqual(homeLink(href),{href,external:false,classic:true})
 for(const href of['/v3/health/run','/v3/approvals/run/execute','/v3/unknown','/api/v2/approvals','//foreign.example/v3/health'])assert.equal(homeLink(href),null)
})
test('held and watch links retain supported destination context; financial strings and missing quantities are passed through exactly',()=>{
 const rows=['ANET','SPCX','NVDA','V'].map(symbol=>({label:symbol,symbol,scope:'held',href:'/wealth/portfolio/holdings?hv_query='+symbol+'&hv_account=SYNTHETIC',facts:[{label:'Coverage',value:'0.4985 shares'},{label:'Missing',value:null},{label:'Declared estimate',value:'$71.23'}]}));rows.push({label:'WATCHONLY',symbol:'WATCHONLY',scope:'watch',href:'/v3/watch/intelligence/WATCHONLY'})
 const model=adapt(payload({today:{movers:section({rows})}}));assert.equal(selectHomeRows(model.today.movers.rows,{scope:'held'}).total,4)
 assert.equal(selectHomeRows(model.today.movers.rows,{scope:'watch'}).total,1)
 for(const row of model.today.movers.rows.slice(0,4)){assert.match(row.href,/hv_query=.*&hv_account=SYNTHETIC/);assert.equal(row.facts[0].value,'0.4985 shares');assert.equal(row.facts[1].value,null);assert.equal(row.facts[2].value,'$71.23')}
})
test('last-available stance title, dated brief text and precise missing narrative boundary are visible without new synthesis',()=>{
 const historical=section({title:'Last available CIO stance',notes:['Last available stance (historical, not currently eligible): Synthetic neutral'],clock:at})
 const model=adapt(payload({today:{stance:historical,brief:section({notes:['Historical source only','This is a synthetic stored narrative.']})}}))
 assert.equal(model.today.stance.title,'Last available CIO stance');assert.equal(model.today.stance.clock,at)
 const html=render('narrative',{section:model.today.brief});assert.match(html,/synthetic stored narrative/);assert.match(html,/Read saved brief/);assert.match(html,/dated history/)
 assert.match(render('narrative',{section:section({notes:['Saved receipt found; summary.text absent']})}),/summary.text absent/)
})

test('registered public provenance is readable without allowing arbitrary opaque account tokens',()=>{
 const data=payload({today:{week:section({source:'canonical_symbol_calendar',rows:[{label:'Calendar source',source:'market_risk_context',facts:[{label:'Publisher',value:'Public publisher',source:'guarded_symbol_headlines'}]},{label:'Unknown opaque source',source:'synthetic_broker_account'}]})}})
 const m=adapt(data),w=m.today.week
 assert.equal(w.source,'Stored symbol calendar');assert.equal(w.rows[0].source,'Stored market-risk context');assert.equal(w.rows[0].facts[0].source,'Stored symbol headline candidates');assert.equal(w.rows[1].source,'[account withheld]')
})
test('projection, original source and browser request clocks are separate and cannot substitute for each other',()=>{
 const m=adapt(payload({built_at:built,today:{week:section({buildClock:'2040-01-02T03:06:00Z'})}}),{fetchedAt:'2040-01-02T04:00:00Z'})
 const s=m.today.week
 assert.equal(s.clock,at);assert.equal(s.buildClock,'2040-01-02T03:06:00Z');assert.equal(s.projectionClock,built);assert.equal(s.requestClock,'2040-01-02T04:00:00Z')
})

test('an explicit unknown field clock never borrows the newer section observation clock',()=>{
 const html=render('panel',{id:'clockGap',title:'Clock gap',icon:'clock',section:section({rows:[{label:'Missing observation',facts:[{label:'Current proof',value:null,source:'Synthetic independent proof',clock:null,qualifier:'Observation timestamp unavailable'}]}]})})
 const field=html.match(/role="tooltip" class="wealth-tooltip">([^<]*Observation timestamp unavailable[^<]*)</)
 assert.ok(field);assert.match(field[0],/source clock not served/)
 assert.doesNotMatch(field[0],new RegExp(at));assert.match(html,new RegExp('dateTime="'+at+'"'))
})

test('an explicit unknown row observation stays unknown in its drawer with section context labelled separately',()=>{
 const html=render('evidence',{row:{label:'Held movement observation',clock:null,source:'Synthetic stored movement'},section:section({clock:at})})
 const observation=html.split('<h3>Observation time</h3>')[1].split('<h3>Producer build time')[0]
 assert.match(observation,/source time not served/);assert.doesNotMatch(observation,/<time/)
 assert.match(html,/Section context observation · separate from this item/);assert.match(html,new RegExp('dateTime="'+at+'"'))
})
