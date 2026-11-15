import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {incomeModel,incomeScope,incomeState} from '../../src/pages/portfolio/income/incomeAdapter.ts'
const now=Date.parse('2026-11-15T19:00:00Z'), env=data=>({data,error:null,lastGood:null,spec:{path:'/api/v2/dividends'}})
const payer={symbol:'TEST',annual_income:120,monthly_amort:10,yield_pct:3,frequency:'quarterly'}
test('7B1 missing/false has_data never invents zero income; an emitted zero remains forecast',()=>{
 assert.equal(incomeState(env({}),now).status,'UNKNOWN')
 const absent=incomeModel({has_data:false,total_annual:0,payers:[payer]});assert.equal(absent.annual,null);assert.equal(absent.legs.length,0)
 const zero=incomeModel({has_data:true,total_annual:0,payers:[{...payer,annual_income:0,monthly_amort:0}]})
 assert.equal(zero.annual,0);assert.equal(zero.legs[0].annual,0);assert.equal(zero.tax,'Unknown')
})
test('7B2 missing numeric fields differ from zero; producer tax/safety defaults never become evidence',()=>{
 for(const qualified of [true,false,undefined])for(const safety of ['unknown','watch',undefined]){
  const m=incomeModel({has_data:true,qualified_annual:120,payers:[{symbol:'TEST',qualified,safety},{...payer,yield_pct:0,annual_income:0}]})
  assert.equal(m.legs[0].yield,null);assert.equal(m.legs[0].annual,null);assert.equal(m.legs[1].yield,0);assert.equal(m.legs[1].annual,0)
  assert.equal(m.tax,'Unknown');assert.equal(m.safety,'Unknown');assert.equal(m.legs[0].tax,'Unknown')
 }
})
test('7B3 explicit zero amortization is preserved, never annual/12 or paid income',()=>{
 const m=incomeModel({has_data:true,payers:[{...payer,monthly_amort:0},{...payer,monthly_amort:undefined}]})
 assert.equal(m.legs[0].monthly,0);assert.equal(m.legs[1].monthly,null)
})
test('7B4 mixed account/unassigned legs survive once each, including repeated symbol/account rows',()=>{
 const m=incomeModel({has_data:true,account_attribution:'source_calendar',total_annual:360,payers:[{...payer,account:'synthetic-key'},payer,{...payer,account:'synthetic-key'}]})
 assert.equal(m.legs.length,3);assert.equal(incomeScope(m,'household').emittedAnnual,360)
 assert.equal(incomeScope(m,m.accounts.find(a=>a.ref!=='unassigned').ref).legs.length,2)
 assert.equal(incomeScope(m,'unassigned').legs.length,1);assert.doesNotMatch(JSON.stringify(m),/synthetic-key/)
})
test('7B5 account misses do not fall back to household or zero; rounding discrepancy remains visible',()=>{
 const m=incomeModel({has_data:true,total_annual:120.01,monthly_average:10,payers:[payer],monthly_summary:[{month:1,month_name:'Jan',total:10}],ex_div_alerts:[{symbol:'TEST',total_income:10}]})
 const miss=incomeScope(m,'missing');assert.equal(miss.legs.length,0);assert.equal(miss.annual,null);assert.equal(miss.months.length,0);assert.equal(miss.dates.length,0)
 assert.equal(incomeScope(m,'household').difference,0.01)
 const acct=incomeScope(m,'unassigned');assert.equal(acct.months.length,0);assert.equal(acct.dates.length,0)
})
test('7B6 unzoned build time stays literal, never parsed into source or receipt freshness',()=>{
 const s=incomeState(env({has_data:true,last_updated:'2026-11-15 13:00',payers:[payer]}),now)
 assert.equal(s.data.built,'2026-11-15 13:00');assert.equal(s.asOf,null);assert.equal(s.ageHours,null)
 assert.doesNotMatch(JSON.stringify(s.data),/received|lastPaid|paid_at/)
})
test('7B7 transport/nested errors, unknown and unqualified cached bodies cannot become a current forecast',()=>{
 assert.equal(incomeState(null,now).status,'LOADING')
 assert.equal(incomeState(env({data:{ok:false,error:'unavailable'}}),now).status,'UNKNOWN')
 const s=incomeState({...env(null),error:'timed out',lastGood:{has_data:true,payers:[payer]},lastGoodAgeSeconds:60},now)
 assert.equal(s.status,'ERROR');assert.equal(s.lastGood,null);assert.equal(s.lastGoodAgeSeconds,null)
 const live=fs.readFileSync(new URL('../../src/pages/portfolio/income/IncomeLive.tsx',import.meta.url),'utf8')
 assert.doesNotMatch(live,/income-dashboard|fetch\(|POST|setInterval|holdings/)
 assert.match(live,/getJson<unknown>\(INCOME_PATH/)
})
