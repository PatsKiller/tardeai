// Synthetic acceptance for the user-approved Holdings workspace. No network, portfolio data or producers.
import test from 'node:test'
import assert from 'node:assert/strict'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {createRequire,Module} from 'node:module'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {MemoryRouter} from 'react-router-dom'
const APP=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..'),require=createRequire(import.meta.url)
const {buildSync}=require('esbuild')
const code=buildSync({stdin:{contents:"export * from './src/pages/portfolio/workspaceV2/adapter'; export * from './src/pages/portfolio/workspaceV2/Workspace'; export * from './src/pages/portfolio/workspaceV2/icons'; export * from './src/components/WealthStatus'; export * from './src/pages/portfolio/fixtures'; export {protectionFields} from './src/pages/portfolio/detail'; export * from './src/pages/portfolio/workspaceV2/StoredNews'",resolveDir:APP,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react-dom','react-router-dom','react/jsx-runtime'],loader:{'.css':'empty'},logLevel:'silent'}).outputFiles[0].text
const filename=path.join(APP,'holdings-acceptance.cjs'),module=new Module(filename);module.filename=filename;module.paths=Module._nodeModulePaths(APP);module._compile(code,filename)
const a=module.exports
const row=(changes={})=>({...structuredClone(a.FIXTURE_BOOK.rows.find(r=>r.kind==='SECURITY')),symbol:'QZAA',accountKey:'SYN_A',accountLabel:'Synthetic A',assetType:'EQUITY',kind:'SECURITY',profileSource:'synthetic',marketValue:200,shares:2,avgCost:80,price:100,gainLoss:40,gainLossPct:25,dayChange:4,fundamentals:{sector:'Technology'},protection:{state:'PROTECTED',stop:90,basis:'synthetic',asOf:'2040-01-01T12:00:00Z',stale:false,nextStep:'Inspect recorded stop',reason:'Synthetic recorded resting stop'},...changes})
const book=rows=>({...structuredClone(a.FIXTURE_BOOK),rows})
const view=(rows,f={})=>a.workspace(book(rows),{...a.DEFAULT,...f})
test('covered sums preserve all-null, partial, zero and finite input distinctions',()=>{
 assert.deepEqual(a.sum([null,null]),{value:null,n:0,m:2});assert.deepEqual(a.sum([0,null,Infinity,NaN]),{value:0,n:1,m:4})
 assert.match(a.coverage(a.sum([1,null])),/partial · 1 of 2/)
 assert.equal(view([]).totals.value.value,null)
})
test('grouped quantities, value and blended remaining basis use explicit independent arithmetic',()=>{
 const rs=[row(),row({accountKey:'SYN_B',accountLabel:'Synthetic B',shares:3,marketValue:300,avgCost:90,gainLoss:30})],original=structuredClone(rs),v=view(rs,{period:'purchase'}),g=v.groups[0]
 assert.equal(g.rows.length,2);assert.equal(g.shares.value,5);assert.equal(g.value.value,500)
 assert.equal(g.cost.value,86);assert.equal(g.unrealized.value,70);assert.equal(g.costPct,70/430*100)
 assert.equal(g.weight,100);assert.deepEqual(rs,original)
})
test('partial basis or prices never become invented blended cost, identical price, or full denominator',()=>{
 let g=view([row(),row({avgCost:null,price:101,accountKey:'SYN_B'})]).groups[0]
 assert.equal(g.cost.value,null);assert.equal(g.cost.n,1);assert.equal(g.mixedPrice,true);assert.equal(g.price,null)
 const v=view([row(),row({symbol:'QZBB',marketValue:null})])
 assert.equal(v.groups[0].weight,null);assert.equal(v.totals.value.n,1);assert.equal(v.totals.value.m,2)
 const single=row({shares:0.1,avgCost:3.333333333333333})
 assert.equal(view([single]).groups.at(-1).cost.value,single.avgCost)
})
test('small rows collapse, significant losses pin, cash stays separate, account grouping keeps source order',()=>{
 const rs=[row({symbol:'QZSM',marketValue:50,gainLoss:-5}),row({symbol:'QZPIN',marketValue:10,gainLoss:-100}),row({symbol:'QZCASH',kind:'CASH',assetType:'CASH',marketValue:50})]
 const v=view(rs);assert.deepEqual(v.groups.map(g=>g.kind),['security','small','cash'])
 assert.equal(v.groups[0].label,'QZPIN');assert.equal(v.totals.invested.value,60);assert.equal(v.totals.cash.value,50)
 assert.deepEqual(view(rs,{group:'account'}).groups.map(g=>g.rows[0].symbol),rs.map(r=>r.symbol))
})
test('AND filters apply to totals, movers, protection panel and export as one population',()=>{
 const rs=[row(),row({symbol:'QZBB',accountKey:'SYN_B',gainLoss:-50}),row({symbol:'QZCC',gainLoss:-20,protection:{state:'GAP',reason:'synthetic gap',stale:null}})]
 const f={...a.DEFAULT,period:'purchase',account:'SYN_A',sector:'Technology',result:'gainers',protection:'PROTECTED',size:'material',query:'QZAA'}
 const v=a.workspace(book(rs),f);assert.equal(v.rows.length,1);assert.equal(v.totals.value.value,200);assert.equal(v.contributors[0].pnl.value,40);assert.equal(v.gaps.length,0)
 const csv=a.exportCsv(v,f);assert.match(csv,/QZAA/);assert.doesNotMatch(csv,/QZBB|QZCC/)
 assert.match(csv,/Since purchase unrealized only/);assert.equal(csv.split('\r\n').length,3)
 for(const field of ['account','sector','result','protection','size','query']){const miss={...f,[field]:'no-match'};assert.equal(a.workspace(book(rs),miss).rows.length,0,field)}
})
test('filter categories respect served asset type, zero results, unknown protection and unknown value',()=>{
 const rs=[row(),row({symbol:'QZF',assetType:'ETF',fundamentals:{sector:'Technology'}}),row({symbol:'QZC',kind:'CASH',assetType:'CASH'}),row({symbol:'QZU',marketValue:null,gainLoss:null,protection:null}),row({symbol:'QZZ',marketValue:0,gainLoss:0})]
 assert.equal(view(rs,{sector:'Funds'}).rows.length,1);assert.equal(view(rs,{sector:'Cash'}).rows.length,1)
 assert.equal(view(rs,{size:'unpriced'}).rows[0].symbol,'QZU')
 assert.equal(view(rs,{period:'purchase',result:'gainers'}).rows.length,2)
 assert.equal(view(rs,{protection:'UNKNOWN'}).rows[0].symbol,'QZU')
 assert.equal(view(rs,{protection:'not-applicable'}).rows[0].symbol,'QZC')
})
test('URL preserves unrelated query and round-trips all filters; reset removes only workspace keys',()=>{
 const f={...a.DEFAULT,period:'purchase',sector:'Funds',account:'SYN_B',result:'losers',protection:'GAP',size:'small',query:'QZ < &',group:'account'}
 const p=a.searchFor(new URLSearchParams('retained=yes'),f)
 assert.deepEqual(a.fromSearch(p),f);assert.equal(p.get('retained'),'yes')
 assert.equal(a.searchFor(p,a.DEFAULT).toString(),'retained=yes')
 assert.equal(a.fromSearch(new URLSearchParams('hv_period=YTD')).period,'session')
})
test('top three contributors/detractors plus other reconcile filtered served price changes',()=>{
 const rs=[9,8,7,6,-5,-4,-3,-2].map((dayChange,i)=>row({symbol:'QZ'+i,dayChange}))
 const v=view(rs);assert.equal(v.contributors.length,3);assert.equal(v.detractors.length,3)
 assert.equal([...v.contributors,...v.detractors].reduce((n,g)=>n+g.pnl.value,0)+v.other.value,16)
})
test('protection icons distinguish protected, gap, partial, pending, stale, unknown and not applicable',()=>{
 assert.equal(a.protectionSummary([row()]).icon,'locked')
 assert.equal(a.protectionSummary([row({protection:{state:'GAP'}})]).icon,'unlocked')
 assert.match(a.protectionSummary([row(),row({protection:{state:'GAP'}})]).label,/Partially/)
 for(const changes of [{stale:true},{stale:null},{stop:null},{asOf:null},{asOf:'invalid'},{reason:'pending activation'}]){
  const r=row();Object.assign(r.protection,changes);const p=a.protectionSummary([r]);assert.equal(p.icon,'unlocked');assert.doesNotMatch(p.label,/^Protected/)
 }
 assert.equal(a.protectionSummary([row({protection:null})]).icon,'na')
 assert.equal(a.protectionSummary([row({kind:'CASH'})]).icon,'na')
 assert.equal(view([row({marketValue:99,protection:{state:'GAP'}})]).gaps.length,0)
})
test('mutual-fund asset labels never replace served protection verdicts with invented exemption',()=>{
 const protectedFund=row({assetType:'MUTUAL_FUND'}),gapFund=row({symbol:'QZFG',assetType:'MUTUAL_FUND',protection:{state:'GAP',reason:'Synthetic successful read found no resting stop',asOf:'2040-01-01T12:00:00Z',stale:false}})
 const unknownFund=row({symbol:'QZFU',assetType:'MUTUAL_FUND',protection:{state:'UNKNOWN',reason:'Synthetic observation unavailable'}}),missingFund=row({symbol:'QZFM',assetType:'MUTUAL_FUND',protection:null})
 const rs=[protectedFund,gapFund,unknownFund,missingFund],original=structuredClone(rs)
 assert.deepEqual(rs.map(a.applicability),['PROTECTED','GAP','UNKNOWN','UNKNOWN'])
 assert.equal(a.protectionSummary([protectedFund]).label,'Protected · recorded')
 assert.equal(a.protectionSummary([gapFund]).tone,'loss');assert.match(a.protectionSummary([gapFund]).label,/reported gap/)
 for(const r of [unknownFund,missingFund]){assert.equal(a.protectionSummary([r]).label,'Protection unknown');assert.equal(a.protectionSummary([r]).tone,'unknown')}
 for(const changes of [{stale:true},{stale:null},{stop:null},{asOf:null},{reason:'pending activation'}]){
  const r=structuredClone(protectedFund);Object.assign(r.protection,changes)
  assert.equal(a.protectionSummary([r]).tone,'partial');assert.doesNotMatch(a.protectionSummary([r]).label,/^Protected/)
 }
 assert.equal(a.protectionSummary([protectedFund,gapFund]).tone,'partial')
 assert.equal(a.protectionSummary([row({kind:'CASH',protection:null}),gapFund]).tone,'loss')
 assert.deepEqual(rs,original)
})
test('mutual-fund filters, gap panel and CSV share the producer verdict without changing the material floor',()=>{
 const rs=[row({symbol:'QZFG',assetType:'MUTUAL_FUND',protection:{state:'GAP'}}),row({symbol:'QZFS',assetType:'MUTUAL_FUND',marketValue:99,protection:{state:'GAP'}}),row({symbol:'QZFU',assetType:'MUTUAL_FUND',protection:null}),row({symbol:'QZFC',kind:'CASH',assetType:'MUTUAL_FUND',protection:null})]
 assert.deepEqual(view(rs,{protection:'GAP'}).rows.map(r=>r.symbol),['QZFG','QZFS'])
 assert.deepEqual(view(rs,{protection:'UNKNOWN'}).rows.map(r=>r.symbol),['QZFU'])
 assert.deepEqual(view(rs,{protection:'not-applicable'}).rows.map(r=>r.symbol),['QZFC'])
 assert.deepEqual(view(rs).gaps.map(r=>r.symbol),['QZFG'])
 assert.equal(a.protectionSummary([rs[1]]).tone,'unknown')
 const csv=a.exportCsv(view(rs),a.DEFAULT),lines=csv.split('\r\n')
 assert.match(lines.find(l=>l.includes('QZFG')),/,"GAP",/)
 assert.match(lines.find(l=>l.includes('QZFU')),/,"UNKNOWN",/)
 assert.doesNotMatch(csv,/Mutual fund · resting stop not applicable/)
})
test('rendered mutual-fund gap uses canonical evidence without a contradictory exemption caption',()=>{
 const rs=[row({symbol:'QZFG',assetType:'MUTUAL_FUND',protection:{state:'GAP',reason:'Synthetic read found no resting stop',asOf:'2040-01-01T12:00:00Z',stale:false}}),row({symbol:'QZFU',assetType:'MUTUAL_FUND',protection:null})]
 const html=renderToStaticMarkup(React.createElement(MemoryRouter,null,React.createElement(a.HoldingsWorkspace,{book:book(rs),notice:null,evidence:null,onRowOpen:()=>{}})))
 const panel=html.split('Protection gaps</h3>')[1].split('</article>')[0]
 assert.match(panel,/QZFG/);assert.match(panel,/Synthetic read found no resting stop/)
 assert.match(html,/Unprotected · reported gap/);assert.match(html,/Protection unknown/)
 assert.doesNotMatch(html,/mutual fund · resting stop not applicable|Resting stop not applicable/i)
})
test('functional SVGs preserve approved paths and supply no icon-only financial meaning',()=>{
 const closed=renderToStaticMarkup(React.createElement(a.WorkspaceIcon,{name:'locked'})),open=renderToStaticMarkup(React.createElement(a.WorkspaceIcon,{name:'unlocked'}))
 assert.match(closed,/M8 11V7a4 4 0 0 1 8 0v4/);assert.match(open,/M8 11V7a4 4 0 0 1 7.6-1.7/)
 assert.match(closed,/aria-hidden="true"/)
 for(const name of ['news','calendar','shield','warning','na'])assert.match(renderToStaticMarkup(React.createElement(a.WorkspaceIcon,{name})),new RegExp('data-icon="'+name+'"'))
})
test('CSV quotes unsafe labels and retains unknown independently from zero',()=>{
 const v=view([row({symbol:'QZ"AA',marketValue:null,gainLoss:0})],{period:'purchase'}),csv=a.exportCsv(v,{...a.DEFAULT,period:'purchase'})
 assert.match(csv,/QZ""AA/);assert.match(csv,/"not served"/);assert.match(csv,/"0"/)
})

test('security grouping precedes the small-position floor and keeps partial value visible',()=>{
 const v=view([row({marketValue:70}),row({marketValue:70,accountKey:'SYN_B'})])
 assert.equal(v.groups.length,1);assert.equal(v.groups[0].kind,'security');assert.equal(v.groups[0].value.value,140)
 const partial=view([row({marketValue:20}),row({marketValue:null,accountKey:'SYN_B'})]).groups[0]
 assert.equal(partial.kind,'security');assert.equal(partial.value.n,1);assert.equal(partial.value.m,2)
 const pinned=view([row({marketValue:20,gainLoss:-60}),row({marketValue:20,gainLoss:-60,accountKey:'SYN_B'})]).groups[0]
 assert.equal(pinned.kind,'security');assert.equal(pinned.unrealized.value,-120)
})
test('collapsed small securities still rank as movers and account movers name their account',()=>{
 const rs=[row({symbol:'QZSM',marketValue:50,dayChange:100}),row({symbol:'QZLG',marketValue:1000,dayChange:1})]
 const v=view(rs);assert.equal(v.groups.find(g=>g.kind==='small').rows[0].symbol,'QZSM')
 assert.equal(v.contributors[0].label,'QZSM');assert.equal(v.contributors[0].pnl.value,100)
 const flat=view(rs,{group:'account'});assert.equal(flat.contributors[0].moverLabel,'QZSM · Synthetic A')
 assert.equal([...v.contributors,...v.detractors].reduce((n,g)=>n+g.pnl.value,0)+(v.other.value??0),101)
})
test('expanded accounts retain filtered weights and cash never receives an invested percentage',()=>{
 const rs=[row(),row({accountKey:'SYN_B',accountLabel:'Synthetic B',marketValue:300}),row({symbol:'QZC',kind:'CASH',assetType:'CASH',marketValue:500})]
 const v=view(rs),g=v.groups.find(g=>g.kind==='security'),cash=v.groups.find(g=>g.kind==='cash')
 assert.deepEqual(g.children.map(c=>c.weight),[20,30]);assert.deepEqual(g.children.map(c=>c.investedWeight),[40,60])
 assert.equal(cash.cash,true);assert.equal(cash.children[0].cash,true);assert.equal(cash.children[0].investedWeight,null)
 const flat=view(rs,{group:'account'}).groups[2];assert.equal(flat.cash,true);assert.equal(flat.investedWeight,null);assert.equal(flat.pnl.value,null)
 const partial=view([row(),row({symbol:'QZU',marketValue:null})]).groups[0]
 assert.equal(partial.children[0].weight,null);assert.equal(partial.children[0].investedWeight,null)
})
test('partial protection uses a closed amber lock; only material served gaps use red',()=>{
 const partial=a.protectionSummary([row(),row({protection:{state:'GAP'},accountLabel:'Synthetic B'})])
 assert.equal(partial.icon,'locked');assert.equal(partial.tone,'partial');assert.match(partial.detail,/Synthetic B/)
 const small=a.protectionSummary([row({marketValue:99,protection:{state:'GAP'}})])
 assert.equal(small.icon,'unlocked');assert.equal(small.tone,'unknown')
 const unknown=a.protectionSummary([row({marketValue:null,protection:{state:'GAP'}})])
 assert.equal(unknown.tone,'unknown');assert.match(unknown.label,/value unknown/)
 assert.equal(a.protectionSummary([row({marketValue:100,protection:{state:'GAP'}})]).tone,'loss')
 const pending=row();pending.protection.reason='Recorded, pending activation'
 assert.equal(a.protectionSummary([pending]).icon,'unlocked');assert.match(a.protectionSummary([pending]).detail,/pending activation/)
})

test('shared signed readings preserve unknown and zero and identify both signs without relying on colour',()=>{
 const read=(value,text)=>renderToStaticMarkup(React.createElement(a.SignedValue,{value},text))
 assert.match(read(12,'$12.00'),/data-tone="green".*▲ \+/)
 assert.match(read(-12,'-$12.00'),/data-tone="red".*▼ .*−\$12.00/)
 for(const [v,label]of [[0,'$0.00'],[null,'not served']]){const html=read(v,label);assert.match(html,/data-tone="grey"/);assert.doesNotMatch(html,/▲|▼/);assert.ok(html.includes(label))}
})
test('shared statuses connect mouse and keyboard tooltips to state, reason and source clock',()=>{
 for(const [icon,tone,label]of [['closed','green','Protected'],['closed','amber','Partial'],['open','amber','Planned only'],['open','red','Gap'],['open','grey','Below floor'],['na','grey','Unknown'],['plug','grey','Waiting on a producer']]){
  const html=renderToStaticMarkup(React.createElement(a.WealthStatus,{icon,tone,label,detail:'Synthetic reason; read 2040-01-01T12:00:00Z'}))
  assert.match(html,/tabindex="0"/);assert.match(html,/aria-describedby="[^"]+"/);assert.match(html,/role="tooltip"/);assert.ok(html.includes(label));assert.ok(html.includes('Synthetic reason; read 2040-01-01T12:00:00Z'))
 }
 const plug=renderToStaticMarkup(React.createElement(a.WorkspaceIcon,{name:'plug'}));assert.match(plug,/M9 3v5M15 3v5M7 8h10v4a5 5 0 0 1-10 0V8zM12 17v4/)
})

test('empty cash selection is true zero while missing cash value stays unknown',()=>{
 const v=view([row()]);assert.deepEqual(v.totals.cash,{value:0,n:0,m:0});assert.equal(v.totals.cashPct,0)
 const missing=view([row(),row({kind:'CASH',assetType:'CASH',marketValue:null,symbol:'QZCASH'})]);assert.equal(missing.totals.cash.value,null);assert.equal(missing.totals.cashPct,null)
 assert.deepEqual(view([]).totals.cash,{value:0,n:0,m:0})
})
test('named reconciliation preserves distinct source definitions and withholds filtered comparison',()=>{
 const rows=[row({dayChange:4}),row({symbol:'QZBB',dayChange:-1}),row({kind:'CASH',symbol:'QZCASH',assetType:'CASH',dayChange:99})]
 const b=book(rows);b.measures=[{id:'price_move_estimate',status:'MEASURED',valueUsd:2.5,asOf:'2040-01-01T12:00:00Z',definition:'Synthetic prior-close baseline',reason:'fixture',label:'Synthetic shell estimate'}]
 const v=a.workspace(b,{...a.DEFAULT});assert.equal(v.reconciliation.storedRows.value,3);assert.equal(v.reconciliation.canonical,2.5);assert.equal(v.reconciliation.difference,-.5);assert.match(v.reconciliation.definition,/prior-close/);assert.equal(v.reconciliation.canonicalAt,'2040-01-01T12:00:00Z')
 const filtered=a.workspace(b,{...a.DEFAULT,query:'QZAA'});assert.equal(filtered.reconciliation.fullPopulation,false);assert.equal(filtered.reconciliation.difference,null)
 rows[1].dayChange=null;assert.equal(a.workspace(b,{...a.DEFAULT}).reconciliation.difference,null)
 b.measures[0].status='UNAVAILABLE';assert.equal(a.workspace(b,{...a.DEFAULT}).reconciliation.canonical,null)
})
test('shared allocation and chips count underlying positions once before account expansion',()=>{
 const rs=[row(),row({accountKey:'SYN_B',marketValue:300}),row({kind:'CASH',assetType:'CASH',symbol:'QZCASH',marketValue:500})]
 const v=view(rs);assert.equal(v.identities.nonCashPositions,2);assert.equal(v.identities.securities,1);assert.equal(v.allocation.denominator,1000)
 assert.equal(v.allocation.segments.find(s=>s.name==='QZAA').pct,50);assert.equal(v.allocation.segments.find(s=>s.kind==='cash').pct,50)
 assert.equal(view(rs,{sector:'Technology'}).sectorChips.find(s=>s.name==='Cash').pct,50)
 assert.equal(v.groups[0].children.length,2);assert.equal(v.allocation.rows,3)
})

test('raw drawer missing protection is unknown for securities and not applicable only for cash',()=>{const security=a.protectionFields(row({protection:null}));assert.match(security[0].value,/UNKNOWN/);assert.doesNotMatch(security[0].value,/cash/);assert.match(a.protectionFields(row({kind:'CASH',protection:null}))[0].value,/not applicable/)})

test('no omitted movers means true zero Other; omitted missing inputs remain partial',()=>{assert.deepEqual(view([row()]).other,{value:0,n:0,m:0});assert.deepEqual(view([row(),row({symbol:'QZUNK',dayChange:null})]).other,{value:null,n:0,m:1})})

test('stored-news deduplication, entity evidence, clocks and bounded cancellation',async()=>{
const m=a
let cases=0
async function test(name,fn){await fn();cases++;console.log('PASS '+name)}
const story=(title='Synthetic company report',url='https://example.test/article?id=1',extra={})=>({title,url,source:'Synthetic source',publishedAt:'2026-01-02T14:00:00Z',...extra})
const read=(symbol='FAKE_A',headlines=[story()],extra={})=>({symbol,headlines,latest:'2026-01-02T15:00:00Z',rejected:2,globalStoredCount:20,discarded:0,observedAt:null,error:null,...extra})
const wire=(headlines,extra={})=>({ok:true,data:{ok:true,symbol:'FAKE_A',headlines:headlines.map(h=>({title:h.title,source:h.source,url:h.url,published_at:h.publishedAt})),guard_rejected:2,ingest:{latest:'2026-01-02T15:00:00Z',guarded_72h:20},...extra}})
await test('safe original URL preserved including tracking fields',()=>{const url='https://example.test/article?id=1&utm_source=test#section';assert.equal(m.headlineUrl(url),url);assert.equal(m.canonicalHeadlineUrl(url),'https://example.test/article?id=1')})
await test('unsafe URLs and embedded credentials withheld',()=>{for(const v of ['javascript:alert(1)','data:text/html,x','file:///etc/passwd','https://user:secret@example.test/x','//example.test/x','not a url'])assert.equal(m.headlineUrl(v),null)})
await test('canonical key removes only declared tracking fields',()=>{assert.equal(m.canonicalHeadlineUrl('https://example.test/a?utm_Source=x&gclid=y&fbclid=z&ref=story&page=2#read'),'https://example.test/a?ref=story&page=2')})
await test('functional query parameters prevent different stories from merging',()=>{const d=m.deduplicateNews([read('FAKE_A',[story('Story one','https://example.test/article?id=1'),story('Story two','https://example.test/article?id=2')])]);assert.equal(d.stories.length,2);assert.equal(d.duplicates,0)})
await test('normalized exact title combines case whitespace and unicode compatibility only',()=>{assert.equal(m.normalizedTitle('  ＡLPHA \n results  '),'alpha results');const d=m.deduplicateNews([read('FAKE_A',[story('Synthetic company report')]),read('FAKE_B',[story(' SYNTHETIC   company report ','https://other.test/report')])]);assert.equal(d.stories.length,1);assert.deepEqual(d.stories[0].symbols,['FAKE_A','FAKE_B']);assert.equal(d.stories[0].variants.length,2)})
await test('punctuation-distinct or semantically similar titles stay distinct',()=>{const d=m.deduplicateNews([read('FAKE_A',[story('Report: sales rise','https://example.test/1'),story('Report sales rise','https://example.test/2'),story('Sales increased','https://example.test/3')])]);assert.equal(d.stories.length,3)})
await test('tracking URL duplicate combines even when exact titles differ',()=>{const a=story('Original title','https://example.test/article?id=1&utm_campaign=first'),b=story('Updated title','https://example.test/article?id=1&utm_campaign=next#story');const d=m.deduplicateNews([read('FAKE_A',[a]),read('FAKE_B',[b])]);assert.equal(d.stories.length,1);assert.equal(d.duplicates,1);assert.deepEqual(new Set(d.stories[0].variants.map(s=>s.url)),new Set([a.url,b.url]))})
await test('transitive title OR URL matches merge complete query tag union',()=>{const d=m.deduplicateNews([read('FAKE_A',[story('First','https://example.test/one')]),read('FAKE_B',[story('Second','https://example.test/two')]),read('FAKE_C',[story('First','https://example.test/two')])]);assert.equal(d.stories.length,1);assert.equal(d.duplicates,2);assert.deepEqual(d.stories[0].symbols,['FAKE_A','FAKE_B','FAKE_C']);assert.equal(d.stories[0].variants.length,3)})
await test('same record repeated once has union tags without duplicate variant clutter',()=>{const d=m.deduplicateNews([read('FAKE_A'),read('FAKE_B')]);assert.equal(d.returned,2);assert.equal(d.duplicates,1);assert.equal(d.stories[0].variants.length,1)})
await test('unsafe URLs do not become shared empty-URL dedup keys',()=>{const d=m.deduplicateNews([read('FAKE_A',[story('One',null),story('Two',null)])]);assert.equal(d.stories.length,2)})
await test('decoder keeps exact source/title/publication and does not trust entity fields',()=>{const h=story('  Exact title\n kept  ');const r=m.decodeStoredNews(wire([h],{entity_match:'VERIFIED'}),'FAKE_A','2026-01-02T16:00:00Z');assert.equal(r.headlines[0].title,h.title);assert.equal(r.headlines[0].publishedAt,h.publishedAt);assert.equal(r.observedAt,'2026-01-02T16:00:00Z');assert.equal(m.deduplicateNews([r]).stories[0].entityMatch,'UNVERIFIED')})
await test('ambiguous acronym and unrelated-entity candidates remain visible and unverified',()=>{const rs=[read('FAKE_NOC',[story('NOC as a Service market','https://example.test/noc')]),read('FAKE_ANET',[story('Backblaze results','https://example.test/bb')])];const d=m.deduplicateNews(rs);assert.equal(d.stories.length,2);assert.ok(d.stories.every(s=>s.entityMatch==='UNVERIFIED'))})
await test('decoder rejects mismatched symbol and missing nested contract',()=>{assert.ok(m.decodeStoredNews(wire([story()]),'FAKE_OTHER').error);assert.ok(m.decodeStoredNews({ok:true},'FAKE_A').error);assert.ok(m.decodeStoredNews({ok:false,data:wire([story()]).data},'FAKE_A').error)})
await test('missing diagnostics stay unknown rather than zero',()=>{const r=m.decodeStoredNews(wire([story()],{guard_rejected:null,ingest:{}}),'FAKE_A');assert.equal(r.latest,null);assert.equal(r.globalStoredCount,null);assert.equal(r.rejected,null);const s=m.newsSummary([r],1);assert.equal(s.rejected.value,null);assert.equal(s.ingestCompletionAt,null)})
await test('genuine zero diagnostics preserved distinctly',()=>{const r=m.decodeStoredNews(wire([],{guard_rejected:0,ingest:{guarded_72h:0,latest:null}}),'FAKE_A');assert.equal(r.rejected,0);assert.equal(r.globalStoredCount,0);assert.equal(m.newsSummary([r],1).rejected.value,0)})
await test('invalid diagnostic counts never become valid measurements',()=>{for(const v of [-1,1.5,NaN,Infinity,'12']){const r=m.decodeStoredNews(wire([],{guard_rejected:v,ingest:{guarded_72h:v}}),'FAKE_A');assert.equal(r.rejected,null);assert.equal(r.globalStoredCount,null)}})
await test('malformed title records counted while unsafe source link is withheld',()=>{const w=wire([story('Kept','javascript:alert(1)')]);w.data.headlines.push({title:' '},null);const r=m.decodeStoredNews(w,'FAKE_A');assert.equal(r.headlines.length,1);assert.equal(r.headlines[0].url,null);assert.equal(r.discarded,2)})
await test('global 72h observations deduplicate instead of summing feed count',()=>{const s=m.newsSummary([read('FAKE_A'),read('FAKE_B')],2);assert.equal(s.global.length,1);assert.equal(s.global[0].count,20);assert.equal(s.rejected.value,4);assert.equal(s.ingestCompletionAt,null)})
await test('different global query observations remain distinct rather than invent consistency',()=>{const s=m.newsSummary([read('FAKE_A'),read('FAKE_B',[],{globalStoredCount:21,latest:'2026-01-02T15:01:00Z'})],2);assert.equal(s.global.length,2)})
await test('failed read cannot contribute headlines or a false zero news verdict',()=>{const s=m.newsSummary([read('FAKE_A'),read('FAKE_B',[story('Do not expose')],{error:'Failed'})],3);assert.equal(s.successes,1);assert.equal(s.failures,1);assert.equal(s.partial,true);assert.equal(s.returned,1);assert.equal(s.global.length,1)})
await test('publication timezone is explicit and missing timezone is never inferred',()=>{assert.equal(m.publishedClock('2026-01-02T09:00:00-05:00'),'Published 2026-01-02T14:00:00.000Z (UTC)');assert.match(m.publishedClock('2026-01-02T09:00:00'),/time zone not served/);assert.equal(m.publishedClock(null),'Published not served');assert.match(m.publishedClock('not-validZ'),/invalid/)})
await test('missing publication timestamps sort deterministically behind dated records',()=>{const d=m.deduplicateNews([read('FAKE_A',[story('Undated','https://example.test/u',{publishedAt:null}),story('Dated','https://example.test/d')])]);assert.equal(d.stories[0].title,'Dated');assert.equal(d.stories[1].publishedAt,null)})
await test('batch caps concurrency at four and reads each symbol once',async()=>{let active=0,max=0;const found=[],symbols=Array.from({length:13},(_,i)=>'FAKE'+i);await m.readStoredNewsBatch(symbols,new AbortController().signal,async(symbol)=>{active++;max=Math.max(max,active);await new Promise(resolve=>setImmediate(resolve));active--;return read(symbol)},r=>found.push(r.symbol));assert.equal(max,4);assert.equal(found.length,13);assert.equal(new Set(found).size,13)})
await test('aborted batch fences late responses and schedules no remaining requests',async()=>{const ctl=new AbortController();let requests=0,results=0;const pending=[];const p=m.readStoredNewsBatch(['A','B','C','D','E'],ctl.signal,async symbol=>{requests++;return new Promise(resolve=>pending.push(()=>resolve(read(symbol))))},()=>results++);assert.equal(requests,4);ctl.abort();pending.forEach(resolve=>resolve());await p;assert.equal(requests,4);assert.equal(results,0)})
await test('generation change fences late results without relying on transport abort',async()=>{let current=true,results=0;const pending=[];const p=m.readStoredNewsBatch(['A','B','C','D','E'],new AbortController().signal,async symbol=>new Promise(resolve=>pending.push(()=>resolve(read(symbol)))),()=>results++,()=>current);current=false;pending.forEach(resolve=>resolve());await p;assert.equal(results,0);assert.equal(pending.length,4)})
await test('request exceptions become explicit failures and do not stop independent reads',async()=>{const results=[];await m.readStoredNewsBatch(['A','B'],new AbortController().signal,async symbol=>{if(symbol==='A')throw new Error('synthetic');return read(symbol)},r=>results.push(r));assert.equal(results.length,2);assert.ok(results.find(r=>r.symbol==='A').error);assert.equal(results.find(r=>r.symbol==='B').error,null)})
assert.equal(cases,26)
})


test('mixed known gaps stay visible in primary protection summary before pending records',()=>{
 const pending=row();pending.protection.reason='Pending activation'
 const gap=row({accountKey:'SYN_B',protection:{state:'GAP'}})
 const mixed=a.protectionSummary([pending,gap]);assert.match(mixed.label,/gap/i);assert.equal(mixed.tone,'loss');assert.equal(mixed.icon,'unlocked');assert.match(mixed.detail,/1 gap/)
 const active=a.protectionSummary([row(),gap]);assert.match(active.label,/reported gap/);assert.equal(active.icon,'locked');assert.equal(active.tone,'partial')
 const below=a.protectionSummary([pending,row({marketValue:99,protection:{state:'GAP'}})]);assert.equal(below.tone,'partial')
 const unknown=a.protectionSummary([pending,row({protection:null})]);assert.doesNotMatch(unknown.label,/gap/i)
})
test('exact holding links reveal the existing small/account row without altering floor or loss pins',()=>{
 const rs=[row({symbol:'QZSM',marketValue:20,gainLoss:0}),row({symbol:'QZSM',accountKey:'SYN_B',accountLabel:'Synthetic B',marketValue:30,gainLoss:0}),row({symbol:'QZPIN',marketValue:10,gainLoss:-100}),row({symbol:'QZOTHER',marketValue:10,gainLoss:0})]
 const f={...a.DEFAULT,query:' qzsm ',account:'SYN_B'},v=a.workspace(book(rs),f),target=a.holdingLinkTarget(v.groups,f)
 assert.deepEqual(target,{expand:['small'],rowKey:'small-0'});assert.equal(v.groups[0].kind,'small');assert.equal(v.groups[0].children[0].rows[0].accountKey,'SYN_B')
 const all=view(rs);assert.equal(all.groups.find(g=>g.label==='QZPIN').kind,'security');assert.equal(all.groups.find(g=>g.kind==='small').rows.length,3)
 assert.equal(a.holdingLinkTarget(all.groups,{query:'QZ',account:''}),null);assert.equal(a.holdingLinkTarget(all.groups,{query:'',account:'SYN_B'}),null)
 assert.equal(a.holdingLinkTarget(all.groups,{query:'QZSM',account:'SYN_MISSING'}),null)
 const flat=view(rs,{query:'QZSM',account:'SYN_B',group:'account'});assert.deepEqual(a.holdingLinkTarget(flat.groups,f),{expand:[],rowKey:'row-0'})
 const pinned=view(rs,{query:'QZPIN'});assert.deepEqual(a.holdingLinkTarget(pinned.groups,{query:'QZPIN',account:''}),{expand:['security-QZPIN'],rowKey:'security-QZPIN-0'})
})
