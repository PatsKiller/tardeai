import test from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import Module from 'node:module'
import {fileURLToPath} from 'node:url'
import path from 'node:path'
const app=fileURLToPath(new URL('../',import.meta.url))
const output=await build({stdin:{contents:`import React from 'react';import{renderToStaticMarkup}from'react-dom/server';import{MemoryRouter}from'react-router-dom';import{DrawerProvider}from'./src/components/Drawer';import{HomePanel,HomeRowEvidence,HomeStoredNarrative,selectHomeRows,compactHomeRowFacts,homeLink}from'./src/pages/home/HomeV2Parts';import{HomeNeedsPage}from'./src/pages/home/HomeNeedsPage';import{HomeTodayPage}from'./src/pages/home/HomeTodayPage';import{HomeOutlookPage}from'./src/pages/home/HomeOutlookPage';import{homeV2Model}from'./src/pages/home/homeV2Adapter';export{selectHomeRows,compactHomeRowFacts,homeLink,homeV2Model};export function render(kind,props){const C={panel:HomePanel,evidence:HomeRowEvidence,narrative:HomeStoredNarrative,needs:HomeNeedsPage,outlook:HomeOutlookPage,today:HomeTodayPage}[kind];return renderToStaticMarkup(<MemoryRouter><DrawerProvider><C {...props}/></DrawerProvider></MemoryRouter>)}`,resolveDir:app,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',target:'node22',loader:{'.css':'empty'},logLevel:'silent',define:{'process.env.NODE_ENV':'"production"'}})
const module=new Module(path.join(app,'tests/home-corrective-virtual.cjs'));module.filename=path.join(app,'tests/home-corrective-virtual.cjs');module.paths=Module._nodeModulePaths(app);module._compile(output.outputFiles[0].text,module.filename)
const{render,selectHomeRows,compactHomeRowFacts,homeV2Model,homeLink}=module.exports
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
 assert.match(html,/1–6 of 9 served task groups/);assert.match(html,/Open protection inventory/);assert.doesNotMatch(html,/Position observation 0/);assert.match(render('panel',{id:'inventory',title:'Separate position inventory',icon:'shield',section:model.needs.protectionInventory}),/1–6 of 25 served account positions/)
 assert.match(html,/Re-entry watch/);assert.doesNotMatch(html,/Since you were stopped out/)
 assert.equal(model.needs.summary.metrics.find(f=>f.label==='Protect money').value,'9')
 assert.equal(model.needs.summary.metrics.find(f=>f.label==='Fix system').value,'0')
 assert.equal(model.needs.summary.metrics.find(f=>f.label==='Queue freshness').value,null)
})
test('separated conflicts render distinct truthful sections with engine details instead of a 200-card disagreement group',()=>{
 const model=adapt(payload({outlook:{disagreements:section({rows:findings.filter(r=>r.category==='CONFLICT')}),gates:section({title:'Policy gates',rows:findings.filter(r=>r.category==='GATE')}),dataQuality:section({title:'Data-quality findings',rows:findings.filter(r=>r.category==='DATA_ERROR')})}}))
 assert.equal(model.outlook.disagreements.rows.length,1);assert.equal(model.outlook.gates.rows.length,27);assert.equal(model.outlook.dataQuality.rows.length,172)
 const html=render('outlook',{sections:model.outlook});assert.equal((html.match(/data-home-record="true"/g)||[]).length,0)
 assert.match(html,/Open registered findings/);assert.match(render('panel',{id:'gates',title:'Policy gates',icon:'shield',section:model.outlook.gates}),/1–6 of 27/);assert.match(render('panel',{id:'dataQuality',title:'Data-quality findings',icon:'gear',section:model.outlook.dataQuality}),/1–6 of 172/)
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


test('compact protection retains proof state, dated level and exact fractional coverage without duplicate canonical labels',()=>{
 const row={label:'SYN',symbol:'SYN',detail:'Synthetic account · Partial resting coverage · canonical applicability served',clock:null,source:'Synthetic stop producer',facts:[{label:'Protection',value:'Partial resting coverage',state:'amber'},{label:'Canonical order verdict',value:'PROTECTED'},{label:'Recorded advisory/order level',value:'$71.23'},{label:'Distance',value:null},{label:'Covered shares',value:'0.4985'},{label:'Uncovered shares',value:'0.025'}]}
 assert.deepEqual(compactHomeRowFacts(row).map(f=>f.label),['Protection','Recorded advisory/order level','Distance','Covered shares','Uncovered shares'])
 const card=render('panel',{id:'stops',title:'Stops',icon:'shield',section:section({rows:[row]})})
 assert.match(card,/Synthetic account/);assert.match(card,/Partial resting coverage/);assert.match(card,/0.4985/);assert.match(card,/0.025/);assert.match(card,/\$71.23/)
 assert.doesNotMatch(card,/Canonical order verdict|canonical applicability served/)
 assert.match(card,/Observation · source time not served/);assert.match(card,/home-v2-ticker">SYN/)
 const detail=render('evidence',{row,section:section({})})
 assert.match(detail,/Canonical order verdict/);assert.match(detail,/canonical applicability served/);assert.match(detail,/Synthetic stop producer/)
})
test('a long actionable reason has a concise real excerpt while Evidence retains every exact reason and own clock',()=>{
 const reason='Investigate the retained upstream schema mismatch. '+ 'Registered evidence remains independently reviewable. '.repeat(8)
 const row={id:'synthetic:long',label:'Review stored source',summary:reason,detail:reason,clock:at,href:'/v3/health',facts:[]}
 const card=render('panel',{id:'fix',title:'Fix system',icon:'gear',section:section({rows:[row]})})
 assert.ok(card.includes(reason.slice(0,110).trimEnd()+'…'));assert.ok(!card.includes(reason));assert.match(card,/href="\/v3\/health"/)
 const evidence=render('evidence',{row,section:section({})})
 assert.ok(evidence.includes(reason));assert.match(evidence,new RegExp('dateTime="'+at+'"'))
 assert.ok(render('evidence',{row:{...row,detail:undefined},section:section({})}).includes(reason))
 const distinct=render('evidence',{row:{...row,summary:'Separate registered action reason',detail:'Independent retained source detail'},section:section({})});assert.match(distinct,/Separate registered action reason/);assert.match(distinct,/Independent retained source detail/)
})
test('stance uses concise retained readings and an honest compact unavailable gauge without repeated visible per-field provenance',()=>{
 const stance=section({title:'Last available CIO stance',notes:['Historical synthetic stance · own dated record'],metrics:[{label:'Tier',value:'YELLOW',source:'Synthetic stance source',clock:at,qualifier:'Independent tier detail'},{label:'Score',value:'41.8',source:'Synthetic score source',clock:at,qualifier:'Independent score detail'},{label:'Buys',value:'Small sizes only',source:'Synthetic buy source',clock:at,qualifier:'Independent buy detail'}]})
 const html=render('today',{sections:{stance}})
 assert.match(html,/Historical synthetic stance/);assert.match(html,/Small sizes only/);assert.match(html,/41.8/);assert.match(html,/Gauge unavailable/)
 assert.doesNotMatch(html,/Independent tier detail|Independent score detail|Independent buy detail/)
 assert.match(html,/Source evidence/);assert.match(html,/Engine-owned gauge cut-offs and marker are not served/)
})


test('one-letter served symbols outrank incidental prose while account labels and explicit symbol queries remain searchable',()=>{
 const list=[{id:'visa:one',label:'Visa',symbol:'V',scope:'held',scopeLabel:'Synthetic retirement account',detail:'Stored coverage'},{id:'telecom:one',label:'Telecom',symbol:'T',scope:'held',scopeLabel:'Synthetic taxable account'},{id:'unrelated',label:'A very active review',symbol:'OTHER',detail:'V and T occur in narrative only'}]
 assert.deepEqual(selectHomeRows(list,{query:'V'}).filtered.map(r=>r.id),['visa:one'])
 assert.deepEqual(selectHomeRows(list,{query:'t'}).filtered.map(r=>r.id),['telecom:one'])
 assert.deepEqual(selectHomeRows(list,{query:'symbol:V'}).filtered.map(r=>r.id),['visa:one'])
 assert.deepEqual(selectHomeRows(list,{query:'account:taxable'}).filtered.map(r=>r.id),['telecom:one'])
 assert.equal(selectHomeRows(list,{query:'V',scope:'watch'}).total,0)
 assert.equal(selectHomeRows(list,{query:'retirement'}).total,1)
})
test('all eleven sector tiles can render together without expanding the general ten-row browse limit',()=>{
 const sectors=Array.from({length:11},(_,i)=>({id:'sector:'+i,label:'Synthetic sector '+i,facts:[{label:'Condition',value:'Observed'}]}))
 const html=render('outlook',{sections:{sectors:section({rows:sectors})}})
 assert.equal((html.match(/data-home-record="true"/g)||[]).length,11)
 assert.match(html,/Synthetic sector 10/);assert.equal(selectHomeRows(sectors,{pageSize:99}).visible.length,10)
})
test('known complete zero, missing queue, unpublished queue and stale observation remain distinct',()=>{
 const known=section({available:false,rows:[],complete:true,totalCount:0,emptyState:'known-zero',unit:'task groups'})
 const zero=render('panel',{id:'decide',title:'Decide',icon:'bell',section:known})
 assert.match(zero,/known empty/);assert.match(zero,/No task groups in this complete observed population/);assert.doesNotMatch(zero,/class="home-v2-unavailable"/)
 const absent=render('panel',{id:'fix',title:'Fix system',icon:'gear',section:section({available:false,rows:[],complete:false,totalCount:null})})
 assert.match(absent,/class="home-v2-unavailable"/);assert.doesNotMatch(absent,/known empty|No task groups/)
 const unpublished=render('panel',{id:'fix',title:'Fix system',icon:'gear',section:section({available:false,emptyState:'not-published',reason:'No published queue contract'})})
 assert.match(unpublished,/not published/)
 const stale=render('panel',{id:'decide',title:'Decide',icon:'bell',section:section({verdict:'stale',emptyState:'stale',rows:[],complete:false,totalCount:0})})
 assert.match(stale,/stale/);assert.doesNotMatch(stale,/known empty/)
})
test('generic owning desk links expose an honest subject/account/record handoff rather than fabricated deep-link completion',()=>{
 const html=render('evidence',{row:{id:'synthetic-task:7',version:'2',label:'Review synthetic protection',symbol:'SYN',scopeLabel:'Synthetic family account',href:'/v3/risk',cta:'Review canonical quantity coverage'},section:section({})})
 for(const text of['Subject-specific review handoff','SYN','Synthetic family account','synthetic-task:7','selecting this exact record is not supported','Review canonical quantity coverage'])assert.ok(html.includes(text),text)
 assert.doesNotMatch(html,/risk\?symbol|risk#synthetic/);assert.match(html,/<section class="home-v2-handoff">/);assert.doesNotMatch(html,/<aside/)
})
test('typed public publisher and engine labels survive while unrelated opaque identifiers remain withheld',()=>{
 const model=adapt(payload({today:{news:section({rows:[{label:'Synthetic story',facts:[{label:'Publisher',value:'sec_edgar'},{label:'Engine',value:'market_risk'},{label:'Publisher',value:'synthetic_broker_account'}]}]})}}))
 const facts=model.today.news.rows[0].facts
 assert.equal(facts[0].value,'SEC EDGAR');assert.equal(facts[1].value,'Market risk');assert.equal(facts[2].value,'[account withheld]')
})
test('partial source inventory retains total, returned cap and typed classification correction without rewriting original event facts',()=>{
 const model=adapt(payload({needs:{incidents:section({sourceTotal:6510,returnedCount:200,sourceCap:200,coverageLabel:'200 returned of 6510 recorded',rows:[{id:'synthetic-incident',label:'Research health',categoryLabel:'Platform health',originalKind:'stored_misc',correctionReason:'Original typed event is health',facts:[{label:'Original recorded category',value:'Orphaned stop'}]}]})}}))
 const s=model.needs.incidents;assert.equal(s.sourceTotal,6510);assert.equal(s.returnedCount,200);assert.equal(s.sourceCap,200)
 const evidence=render('evidence',{row:s.rows[0],section:s});for(const v of['Platform health','stored_misc','Original typed event is health','Orphaned stop'])assert.ok(evidence.includes(v),v)
})
test('Today has separate held and watch mover contracts and retains re-entry context on demand',()=>{
 const html=render('today',{sections:{movers:section({rows:[{label:'Held synthetic',symbol:'HELD',scope:'held'}]}),watchMovers:section({rows:[{label:'Watch synthetic',symbol:'WATCH',scope:'watch'}]}),watch:section({rows:[{label:'Retained re-entry synthetic'}]})}})
 assert.match(html,/Held synthetic/);assert.match(html,/Watch synthetic/);assert.match(html,/Open retained re-entry context/);assert.doesNotMatch(html,/Retained re-entry synthetic/)
 assert.match(html,/home-v2-ticker">HELD/);assert.match(html,/home-v2-ticker">WATCH/)
})

test('re-entry truth preserves unknown separately from false and displays real served names only',()=>{
 const model=adapt(payload({needs:{reentry:section({rows:[{label:'Synthetic watch',clock:at,state:'amber',progress:[true,false,null,'unknown',0],conditions:[{label:'Validation current',value:null},{label:'Saved setup',value:false},{label:'Source joined',value:true}]}]})}}))
 const row=model.needs.reentry.rows[0]
 assert.deepEqual(row.progress,[true,false,null,null,null]);assert.deepEqual(row.conditions.map(c=>c.value),[null,false,true])
 const detail=render('evidence',{row,section:model.needs.reentry})
 assert.match(detail,/Validation current: unknown/);assert.match(detail,/Saved setup: not met/);assert.match(detail,/Source joined: met/)
 const unnamed=render('evidence',{row:{...row,conditions:[]},section:model.needs.reentry})
 assert.match(unnamed,/Condition 2 · name not served: not met/);assert.match(unnamed,/Condition 3 · name not served: unknown/)
})
test('scoped journal meaning remains visible while all stored partial ledger evidence is retained',()=>{
 const model=adapt(payload({today:{tiles:section({metrics:[{label:'Realized P/L',value:'$12.34',qualifier:'Partial ledger',accountScope:'Synthetic broker only',timeWindow:'all_time',interval:'Closed through synthetic date',basis:'Known basis subset',details:[{label:'Unknown basis records',value:'7'},{label:'Proceeds, not profit',value:'$56.78'}]}]})}}))
 const fact=model.today.tiles.metrics[0]
 for(const q of ['Partial ledger','Synthetic broker only','all_time','Closed through synthetic date','Known basis subset'])assert.ok(fact.qualifier.includes(q))
 const html=render('today',{sections:model.today});assert.match(html,/Synthetic broker only/);assert.match(html,/Known basis subset/)
 const detail=render('evidence',{row:{label:'Ledger',facts:[fact]}})
 assert.match(detail,/Unknown basis records/);assert.match(detail,/Proceeds, not profit/)
})
test('explicit stale empty observation cannot become a complete current zero queue',()=>{
 const html=render('panel',{id:'fix',title:'Fix system',icon:'gear',section:section({available:false,rows:[],complete:true,totalCount:0,emptyState:'stale'})})
 assert.doesNotMatch(html,/No records in this complete observed population/);assert.match(html,/not served/)
})

test('expired or failed-refresh known zero is retained history and cannot assert a current empty population',()=>{
 const base=section({rows:[],complete:true,totalCount:0,unit:'task groups',emptyState:'known-zero'})
 for(const ss of[{...base,verdict:'stale'},{...base,readFailed:true}]){
  const html=render('panel',{id:'fix',title:'Fix system',icon:'gear',section:ss})
  assert.doesNotMatch(html,/known empty|No task groups in this complete observed population/)
  assert.match(html,/Retained observation: zero task groups; current population is unknown/)
 }
 const model=adapt(payload({needs:{fix:base}}),{error:'Synthetic failed refresh'})
 assert.equal(model.needs.fix.readFailed,true)
 assert.doesNotMatch(render('panel',{id:'fix',title:'Fix system',icon:'gear',section:model.needs.fix}),/known empty|No task groups in this complete observed population/)
})
test('retained re-entry truth stays readable but failed reads cannot retain green condition confirmation',()=>{
 const base=section({rows:[{label:'Saved watch',conditions:[{label:'Validation current',value:true}],progress:[true,false,null,true,true]}]})
 const model=adapt(payload({needs:{reentry:base}}),{error:'Synthetic failed refresh'})
 const html=render('evidence',{row:model.needs.reentry.rows[0],section:model.needs.reentry})
 assert.match(html,/saved met; current truth unknown/);assert.doesNotMatch(html,/data-tone="green"/)
 const unnamed=render('evidence',{row:{...model.needs.reentry.rows[0],conditions:[]},section:model.needs.reentry})
 assert.match(unnamed,/current truth unknown/);assert.doesNotMatch(unnamed,/class="on"/)
 const dated=render('evidence',{row:{label:'Dated watch',state:'grey',clock:null,conditions:[{label:'Stored check',value:true}]},section:section({})})
 assert.match(dated,/saved met; current truth unknown/);assert.doesNotMatch(dated,/data-tone="green"/)
})
test('gauge provenance retains its independent clock and source policy rather than borrowing stance time',()=>{
 const model=adapt(payload({today:{stance:section({metrics:[{label:'Score',value:'25'}],gauge:{scoreLabel:'Stored score only',marker:'25%',bands:[{width:'100%',state:'grey'}],ticks:[],policyVersion:'Synthetic scale v1',source:'Synthetic engine',clock:built,qualifier:'Score only; no weighted contribution claim'}})}}))
 assert.equal(model.today.stance.clock,at);assert.equal(model.today.stance.gauge.clock,built)
 assert.equal(model.today.stance.gauge.qualifier,'Score only; no weighted contribution claim')
 const html=render('today',{sections:model.today})
 assert.match(html,/Gauge observation/);assert.ok(html.includes(built));assert.match(html,/Synthetic scale v1/)
})

test('journal Evidence retains source calculation quality verdict and evaluation metadata without deriving currentness or age',()=>{
 const model=adapt(payload({today:{tiles:section({metrics:[{label:'Realized P/L',value:'$12.34',clock:at,calculationVersion:'Synthetic calculation v2',quality:'partial known basis',verdict:'stale',evaluated_at:built,age_s:0}]})}}))
 const fact=model.today.tiles.metrics[0]
 assert.equal(fact.calculationVersion,'Synthetic calculation v2');assert.equal(fact.quality,'partial known basis');assert.equal(fact.verdict,'stale');assert.equal(fact.evaluatedAt,built);assert.equal(fact.ageSeconds,0)
 const detail=render('evidence',{row:{label:'Scoped journal',facts:[fact]}})
 for(const value of ['Calculation version','Synthetic calculation v2','partial known basis','Source freshness verdict','stale','0 seconds at source evaluation',built])assert.ok(detail.includes(value),value)
 const invalid=adapt(payload({today:{tiles:section({metrics:[{label:'Realized P/L',value:'0',evaluated_at:'2040-01-02T03:10:00',age_s:-1}]})}})).today.tiles.metrics[0]
 assert.equal(invalid.evaluatedAt,null);assert.equal(invalid.ageSeconds,null)
})

test('compact default filters remain discoverable and duplicate subject CTAs stay in full Evidence',()=>{
 const row={label:'Synthetic subject',href:'/v3/risk',cta:'Review specific retained subject',links:[{label:'Supporting reader',href:'/v3/health'}],clock:at,facts:[{label:'Protection',value:'Unknown'},{label:'Position observation',value:at},{label:'Order observation',value:null}],summaryFacts:[{label:'Position observation',value:at},{label:'Order observation',value:null}]}
 const html=render('panel',{id:'movers',title:'Movers',icon:'pulse',section:section({rows:[row]})})
 assert.match(html,/<details class="home-v2-filter-disclosure">/);assert.match(html,/Find or filter/);assert.doesNotMatch(html,/<details[^>]* open/);assert.match(html,/Symbol, account or record/);assert.match(html,/Synthetic subject/)
 assert.doesNotMatch(html,/Review specific retained subject|Supporting reader/);assert.ok(html.includes(`dateTime="${at}"`));assert.doesNotMatch(html,/>Observation ·/)
 const full=render('evidence',{row,section:section({})});assert.match(full,/Review specific retained subject/);assert.match(full,/Supporting reader/);assert.match(full,/Position observation/);assert.match(full,/2040/)
})

test('compact stance preserves verbatim source meaning and gauge policy provenance without main generic navigation',()=>{
 const sentence='Dated synthetic stance remains qualified by its independent engine record.'
 const qualifier='Score alone does not determine tier: synthetic gates and hysteresis remain authoritative.'
 const stance=section({summary:'Independent source coverage remains visible',notes:[sentence],links:[{label:'Generic owning desk',href:'/v3/risk'}],gauge:{clock:at,source:'Synthetic policy',policyVersion:'SyntheticPolicy@v1',scoreLabel:'Stored score',marker:'30%',bands:[{width:'100%',state:'grey'}],ticks:[],qualifier}})
 const html=render('today',{sections:{stance}});assert.ok(html.includes(sentence));assert.match(html,/Independent source coverage remains visible/);assert.match(html,/Score scale only · policy in Evidence/);assert.ok(html.includes(qualifier));assert.match(html,/SyntheticPolicy@v1/);assert.ok(html.includes(`dateTime="${at}"`));assert.doesNotMatch(html,/Generic owning desk/)
})
