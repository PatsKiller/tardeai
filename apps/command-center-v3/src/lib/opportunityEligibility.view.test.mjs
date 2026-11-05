// Real OpportunitiesHub/widget renders against captured native op.assess -> api.get_list outputs. The CIO
// current-head fixture was made by the native _apply_event fold. No DB/provider, source context or trading action.
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
process.env.NODE_ENV='production'
const require=createRequire(import.meta.url),ts=require('typescript')
for(const ext of['.ts','.tsx'])require.extensions[ext]=(module,file)=>module._compile(ts.transpileModule(readFileSync(file,'utf8'),{
 fileName:file,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,esModuleInterop:true},
}).outputText,file)
require.extensions['.css']=()=>{}
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server'),{MemoryRouter}=require('react-router-dom')
const fixtures={
  "ready": {
    "ok": true,
    "as_of": "2026-11-04T18:54:29.167699+00:00",
    "top_list": {
      "market_risk_tier": "GREEN",
      "notice": "Market risk GREEN.",
      "eligible": 1,
      "research_only": 0,
      "coverage_floor": 0.8
    },
    "total": 1,
    "items": [
      {
        "symbol": "SYNQ",
        "rank": 1,
        "research_rank": 1,
        "conviction": 94.2,
        "coverage": 0.9,
        "type": "new_position",
        "stance": "WATCH",
        "technical_condition": "range",
        "upside_pct": 50.0,
        "risk_reward": {
          "entry_ref": 100.0,
          "entry_source": "entry_plan.suggested_entry",
          "current_price": 100.0,
          "entry_zone": null,
          "invalidation_level": 90.0,
          "invalidation_source": "entry_plan",
          "targets": [
            {
              "label": "Plan target",
              "px": 150.0,
              "source": "entry_plan",
              "tier": "T1",
              "reward_pct": 50.0,
              "primary": true
            }
          ],
          "risk_per_share": 10.0,
          "risk_pct": 10.0,
          "primary_target": 150.0,
          "reward_pct": 50.0,
          "rr": 5.0,
          "level_trust": 1.0
        },
        "top_eligibility": {
          "eligible": true,
          "missing": [],
          "reason": "CIO-reviewed with technical coverage",
          "coverage_floor": 0.8,
          "entry_held": false
        },
        "cio_review": {
          "reviewed": true,
          "stance": "WATCH",
          "as_of": "2026-11-04T18:54:29.167699Z",
          "thesis_version": "symbol_synq@v1",
          "source": "cio_theses_projection.current"
        }
      }
    ],
    "research_candidates": []
  },
  "unreviewed": {
    "ok": true,
    "as_of": "2026-11-04T18:54:29.167699+00:00",
    "top_list": {
      "market_risk_tier": "GREEN",
      "notice": "Market risk GREEN.",
      "eligible": 0,
      "research_only": 1,
      "coverage_floor": 0.8
    },
    "total": 0,
    "items": [],
    "research_candidates": [
      {
        "symbol": "SYNQ",
        "rank": null,
        "research_rank": 1,
        "conviction": 94.2,
        "coverage": 0.9,
        "type": "new_position",
        "stance": null,
        "technical_condition": "range",
        "upside_pct": 50.0,
        "risk_reward": {
          "entry_ref": 100.0,
          "entry_source": "entry_plan.suggested_entry",
          "current_price": 100.0,
          "entry_zone": null,
          "invalidation_level": 90.0,
          "invalidation_source": "entry_plan",
          "targets": [
            {
              "label": "Plan target",
              "px": 150.0,
              "source": "entry_plan",
              "tier": "T1",
              "reward_pct": 50.0,
              "primary": true
            }
          ],
          "risk_per_share": 10.0,
          "risk_pct": 10.0,
          "primary_target": 150.0,
          "reward_pct": 50.0,
          "rr": 5.0,
          "level_trust": 1.0
        },
        "top_eligibility": {
          "eligible": false,
          "missing": [
            "technical coverage not yet verified",
            "CIO research thesis",
            "CIO stance",
            "dated CIO review"
          ],
          "reason": "Unreviewed for the top list \u2014 data missing: technical coverage not yet verified; CIO research thesis; CIO stance; dated CIO review",
          "coverage_floor": 0.8,
          "entry_held": false
        },
        "cio_review": {
          "reviewed": false,
          "stance": null,
          "as_of": null,
          "thesis_version": null,
          "source": "cio_theses_projection.current"
        }
      }
    ]
  },
  "red": {
    "ok": true,
    "as_of": "2026-11-04T18:54:29.167699+00:00",
    "top_list": {
      "market_risk_tier": "RED",
      "notice": "Market risk RED: new long ideas are held.",
      "eligible": 0,
      "research_only": 1,
      "coverage_floor": 0.8
    },
    "total": 0,
    "items": [],
    "research_candidates": [
      {
        "symbol": "SYNQ",
        "rank": null,
        "research_rank": 1,
        "conviction": 94.2,
        "coverage": 0.9,
        "type": "new_position",
        "stance": "WATCH",
        "technical_condition": "range",
        "upside_pct": 50.0,
        "risk_reward": {
          "entry_ref": 100.0,
          "entry_source": "entry_plan.suggested_entry",
          "current_price": 100.0,
          "entry_zone": null,
          "invalidation_level": 90.0,
          "invalidation_source": "entry_plan",
          "targets": [
            {
              "label": "Plan target",
              "px": 150.0,
              "source": "entry_plan",
              "tier": "T1",
              "reward_pct": 50.0,
              "primary": true
            }
          ],
          "risk_per_share": 10.0,
          "risk_pct": 10.0,
          "primary_target": 150.0,
          "reward_pct": 50.0,
          "rr": 5.0,
          "level_trust": 1.0
        },
        "top_eligibility": {
          "eligible": false,
          "missing": [],
          "reason": "New long ideas held \u2014 market risk red",
          "coverage_floor": 0.8,
          "entry_held": true
        },
        "cio_review": {
          "reviewed": true,
          "stance": "WATCH",
          "as_of": "2026-11-04T18:54:29.167699Z",
          "thesis_version": "symbol_synq@v1",
          "source": "cio_theses_projection.current"
        }
      }
    ]
  },
  "legacy": {
    "ok": true,
    "as_of": "2026-11-04T18:54:29.167699+00:00",
    "total": 1,
    "items": [
      {
        "symbol": "SYNQ",
        "rank": 1,
        "research_rank": 1,
        "conviction": 94.2,
        "coverage": 0.9,
        "type": "new_position",
        "stance": "WATCH",
        "technical_condition": "range",
        "upside_pct": 50.0,
        "risk_reward": {
          "entry_ref": 100.0,
          "entry_source": "entry_plan.suggested_entry",
          "current_price": 100.0,
          "entry_zone": null,
          "invalidation_level": 90.0,
          "invalidation_source": "entry_plan",
          "targets": [
            {
              "label": "Plan target",
              "px": 150.0,
              "source": "entry_plan",
              "tier": "T1",
              "reward_pct": 50.0,
              "primary": true
            }
          ],
          "risk_per_share": 10.0,
          "risk_pct": 10.0,
          "primary_target": 150.0,
          "reward_pct": 50.0,
          "rr": 5.0,
          "level_trust": 1.0
        }
      }
    ],
    "research_candidates": []
  }
}
// Qualification receipt transport fixtures; native backend tests regenerate each input's source/clock.
fixtures.ready.items[0].top_eligibility.technical = { verified: true, as_of: '2026-11-04T17:30:00Z' }
for (const name of ['unreviewed', 'red']) for (const row of fixtures[name].research_candidates) {
 row.top_eligibility.technical = { verified: false, as_of: '2020-01-01T00:00:00Z' }
}
globalThis.window={matchMedia:()=>({matches:false})}
let current
require('../hooks/useApi.ts').useApi=url=>url.startsWith('/api/v3/data-broker/watch-universe')||url.startsWith('/api/v3/opportunities')
 ?{data:current,loading:false,error:null,refetch(){}}:{data:null,loading:false,error:null,refetch(){}}
const {default:Hub,TopOpportunitiesWidget}=require('../pages/OpportunitiesHub.tsx')
const render=(Component,filtered=false)=>renderToStaticMarkup(React.createElement(MemoryRouter,{initialEntries:['/watch?tab=opportunities&preset=top5'+(filtered?'&type=new_position':'')]},React.createElement(Component)))
let passed=0,failed=0
for(const [name,fixture]of Object.entries(fixtures))for(const [label,Component]of[['hub',Hub],['filtered-hub',Hub],['widget',TopOpportunitiesWidget]]){
 try{
  current=fixture;const html=render(Component,label==='filtered-hub')
  assert.doesNotMatch(html,/curated by the CIO/i)
  assert.match(html,/SYNQ/)
  assert.match(html,/data-technical-as-of/)
  if(name==='ready') { assert.match(html,/Technical input clocks verified/); assert.match(html,/dateTime="2026-11-04T17:30:00Z"/) }
  else { assert.match(html,/Technical input clocks not verified/); if(name!=='legacy')assert.match(html,/dateTime="2020-01-01T00:00:00Z"/) }
  if(name==='ready'){
   assert.doesNotMatch(html,/data-research-symbol="SYNQ"/)
   assert.match(html,/CIO|reviewed/)
   if(label.endsWith('hub'))assert.match(html,/data-cio-reviewed-as-of/)
  }else{
   assert.match(html,/data-research-symbol="SYNQ"/)
   assert.match(html,/Read full record/)
   assert.doesNotMatch(html,/data-opportunity-row="SYNQ"/)
   if(name==='red') {assert.match(html,/Market risk RED/);assert.doesNotMatch(html.match(/<article[^>]*data-research-symbol[\s\S]*?<\/article>/)?.[0]||'',/New Position|new position/)}
   if(name==='legacy')assert.match(html,/not been verified|unavailable|not verified/)
   if(name==='unreviewed')assert.match(html,/CIO research thesis/)
  }
  passed++
 }catch(e){failed++;console.error(`FAIL ${name}/${label}: ${e.message.split('\n')[0]}`)}
}
console.log(`opportunity eligibility actual renders: ${passed} passed, ${failed} failed`)
process.exitCode=failed?1:0
