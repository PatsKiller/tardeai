import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {questionPath,questionsState,questionDetailState,questionsModel,questionDetailModel} from '../../src/pages/intel/questions/questionsAdapter.ts'
const now=Date.parse('2026-11-15T19:00:00Z')
const env=data=>({data,error:null,lastGood:null,spec:{path:'/api/v2/cio/asks'}})
test('request clock is not question ledger freshness',()=>{
 const s=questionsState(env({ok:true,data:{as_of:'2026-11-15T19:00:00Z',threads:[]}}),now)
 assert.equal(s.asOf,null);assert.equal(s.ageHours,null)
 assert.equal(s.status,'UNKNOWN');assert.equal(s.data,null);assert.match(s.reason,/absence is unproven/)
})
test('transport and nested unavailable errors cannot become an empty settled list',()=>{
 assert.equal(questionsState({...env(null),error:'timed out'},now).status,'ERROR')
 assert.equal(questionsState(env({data:{ok:false,error:'unreadable'}}),now).status,'UNKNOWN')
 assert.equal(questionDetailState(env({data:{}}),now).status,'UNKNOWN')
 const denied=questionDetailState({...env(null),error:'HTTP 403'},now)
 assert.equal(denied.status,'ERROR');assert.equal(denied.reason,'HTTP 403')
 assert.match(questionDetailState(env({ok:false,error:'AGENT_CALLER_REFUSED'}),now).reason,/AGENT_CALLER_REFUSED/)
})
test('stored answer date is produced_at, never request or thread update time',()=>{
 const d=questionDetailModel({thread:{updated_at:'2026-11-15T19:00:00Z',turns:[{question:'Synthetic question',answers:[{summary:'Stored answer',produced_at:'2026-11-01T12:00:00Z',what_changed:'Synthetic correction'}]}]}})
 assert.equal(d.turns[0].answers[0].at,'2026-11-01T12:00:00Z')
 assert.equal(d.turns[0].answers[0].changed,'Synthetic correction')
 assert.equal(questionDetailModel({thread:{turns:[{answers:[{summary:'Undated'}]}]}}).turns[0].answers[0].at,'')
})
test('thread URLs are exact read-only GET paths; invalid references are refused',()=>{
 assert.equal(questionPath(),'/api/v2/cio/asks')
 assert.equal(questionPath('thr_0123456789abcdef'),'/api/v2/cio/asks/thr_0123456789abcdef')
 assert.equal(questionPath('../ask'),null)
 const live=fs.readFileSync(new URL('../../src/pages/intel/questions/QuestionsLive.tsx',import.meta.url),'utf8')
 assert.match(live,/getJson<unknown>/)
 assert.doesNotMatch(live,/fetch\(|POST|setInterval|\/api\/v2\/cio\/ask['"]/)
})
test('known raw account keys never survive question output, and unsafe source links disappear',()=>{
 const list=questionsModel({account_labels:{'synthetic-secret-key':'Example retirement'},threads:[{title:'synthetic-secret-key',last_answer_excerpt:'synthetic-secret-key',thread_id:'thr_0123456789abcdef'}]})
 assert.doesNotMatch(JSON.stringify(list),/synthetic-secret-key/)
 const d=questionDetailModel({account_labels:{'synthetic-secret-key':'Example retirement'},thread:{title:'synthetic-secret-key',turns:[{question:'synthetic-secret-key',answers:[{summary:'synthetic-secret-key',sources:[{url:'javascript:evil()'}]}]}]}})
 assert.doesNotMatch(JSON.stringify(d),/synthetic-secret-key|javascript:/)
 const prose=questionDetailModel({thread:{title:'Is LIQUIDITY WEAKENING?',turns:[{answers:[{summary:'OVERWEIGHT unchanged; VOLATILITY normal.'}]}]}})
 assert.equal(prose.title,'Is LIQUIDITY WEAKENING?');assert.equal(prose.turns[0].answers[0].summary,'OVERWEIGHT unchanged; VOLATILITY normal.')
})
