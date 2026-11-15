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
const code=buildSync({stdin:{contents:"export * from './src/pages/portfolio/workspaceV2/adapter'; export * from './src/pages/portfolio/workspaceV2/Workspace'; export * from './src/pages/portfolio/workspaceV2/icons'; export * from './src/pages/portfolio/fixtures'",resolveDir:APP,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react-dom','react-router-dom','react/jsx-runtime'],loader:{'.css':'empty'},logLevel:'silent'}).outputFiles[0].text
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
 assert.equal(a.protectionSummary([row({protection:null})]).icon,'warning')
 assert.equal(a.protectionSummary([row({kind:'CASH'})]).icon,'na')
 assert.equal(a.protectionSummary([row({assetType:'MUTUAL_FUND'})]).icon,'na')
 assert.equal(view([row({marketValue:99,protection:{state:'GAP'}})]).gaps.length,0)
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
