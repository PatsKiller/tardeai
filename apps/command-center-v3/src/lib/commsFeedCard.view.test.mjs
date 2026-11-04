// Render the actual components with synthetic messages; no transport or live data.
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
const require = createRequire(import.meta.url)
const ts = require('typescript')
for (const extension of ['.ts', '.tsx']) require.extensions[extension] = (module, file) => {
  module._compile(ts.transpileModule(readFileSync(file, 'utf8'), {compilerOptions: {
    jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, esModuleInterop: true,
  }}).outputText, file)
}
const React = require('react')
const {renderToStaticMarkup} = require('react-dom/server')
const {FeedCard} = require('../components/decision/FeedCards.tsx')
const {MessageDrawer} = require('../components/comms/MessageDrawer.tsx')
const base = {event_id:'synthetic-entry', category:'high_conviction_opportunity', priority:'high',
  direction:'OUTBOUND', actionable:true, action_hint:'Review entry', headline:'HIGH CONVICTION ENTRY',
  priority_score:77, levels:{conviction:80,entry_ref:10,target:14}, sanitized_body:'Original entry message'}
const render = (e, drawer=false) => renderToStaticMarkup(React.createElement(drawer ? MessageDrawer : FeedCard,
  {e, id:e.event_id, selected:false, picked:false, onPick(){}, onOpen(){}, onClose(){}, onAction(){}}))
let passed=0, failed=0
for (const symbols of [undefined, [], null, [''], ['  '], [null], [42], 'AAA', ['—'], ['['], ['...'], ['?!']]) {
  for (const drawer of [false,true]) {
    try {
      const html=render({...base,symbols},drawer)
      assert.match(html,/Incomplete message/)
      assert.match(html,/subject is missing/i)
      assert.doesNotMatch(html,/▶|>80<|>HIGH CONVICTION ENTRY</)
      if(drawer) assert.match(html,/Original entry message/)
      passed++
    } catch(error) {failed++; console.error(`FAIL symbols=${JSON.stringify(symbols)} drawer=${drawer}: ${error.message.split('\n')[0]}`)}
  }
}
for (const e of [ {...base,symbols:['AAA']}, {...base,symbols:[' ','AAA']},
  ...['BRK.B','RDS-A','^SYNTH','SYNTH=F','SYNTH[Q]','SYNTH[','0700.HK'].map(symbol => ({...base,symbols:[symbol]})),
  {...base,category:'operational_issue',headline:'Service warning',action_hint:'Inspect service',symbols:[]},
  {...base,direction:'INBOUND',symbols:[]} ]) {
  for(const drawer of [false,true]) {
    try {const html=render(e,drawer);assert.doesNotMatch(html,/Incomplete message/);assert.match(html,/▶/);passed++}
    catch(error){failed++;console.error(`FAIL identified or general message drawer=${drawer}: ${error.message.split('\n')[0]}`)}
  }
}
// Native capture: from_alert_event -> CommunicationEvent.to_row -> classify with config/comms_categories.yaml
// -> update_params action binding -> communications_portal._project_hub. The body has no ticker, so the parsed
// list is empty while the producer's explicit identity survives. Only render-consumed projected fields retained.
const canonicalProjection = {
  "event_id": "synthetic-canonical-entry",
  "direction": "OUTBOUND",
  "entity_refs": {
    "symbol": "SYNX"
  },
  "subject_key": "alert:cio_entry_alert:SYNX",
  "symbols": [],
  "category": "high_conviction_opportunity",
  "priority": "high",
  "priority_score": 77.0,
  "actionable": true,
  "action_hint": "Review entry",
  "headline": "HIGH CONVICTION ENTRY",
  "sanitized_body": "HIGH CONVICTION ENTRY\nBuy ready inside entry zone."
}
for (const symbols of [[], undefined, null, [' '], ['—'], 'SYNX']) for (const drawer of [false,true]) {
  try {
    const html=render({...canonicalProjection,symbols},drawer)
    assert.match(html,/data-symbol-link="SYNX"/)
    assert.doesNotMatch(html,/Incomplete message|subject is missing/i)
    assert.match(html,/▶/)
    assert.match(html,/Review entry/)
    passed++
  } catch(error) {failed++;console.error(`FAIL canonical identity symbols=${JSON.stringify(symbols)} drawer=${drawer}: ${error.message.split('\n')[0]}`)}
}
// Identity presence does not grant actionability or manufacture opportunity/quote facts.
for (const drawer of [false,true]) for (const controls of [{actionable:false}, {action_hint:null}]) {
  try {
    const html=render({...canonicalProjection,...controls},drawer)
    assert.match(html,/data-symbol-link="SYNX"/)
    assert.doesNotMatch(html,/Incomplete message|subject is missing/i)
    if (controls.actionable === false) assert.doesNotMatch(html,/▶/)
    if (controls.action_hint === null) assert.doesNotMatch(html,/▶\s*Review entry/)
    assert.equal(html,render({...canonicalProjection,...controls,symbols:['SYNX']},drawer))
    assert.doesNotMatch(html,/\$10\.00|>80<|80\/100/)
    passed++
  } catch(error) {failed++;console.error(`FAIL canonical identity cannot enable an action drawer=${drawer}: ${error.message.split('\n')[0]}`)}
}
// A subject key or prose may mention a ticker without establishing a canonical symbol. Malformed structured refs
// must not manufacture identity; a valid parsed symbol still works when optional structured refs are malformed.
for (const entity_refs of [undefined,null,[],{}, {symbol:[]},{symbol:42},{symbol:' '},{symbol:'—'}]) {
  for (const drawer of [false,true]) {
    try {
      const missing=render({...canonicalProjection,entity_refs,headline:'HIGH CONVICTION ENTRY SYNX'},drawer)
      assert.match(missing,/Incomplete message/)
      assert.doesNotMatch(missing,/data-symbol-link="SYNX"|▶/)
      const known=render({...canonicalProjection,entity_refs,symbols:['SYNX']},drawer)
      assert.match(known,/data-symbol-link="SYNX"/)
      assert.doesNotMatch(known,/Incomplete message/)
      passed++
    } catch(error) {failed++;console.error(`FAIL identity boundary refs=${JSON.stringify(entity_refs)} drawer=${drawer}: ${error.message.split('\n')[0]}`)}
  }
}
console.log(`commsFeedCard actual renders: ${passed} passed, ${failed} failed`)
process.exitCode=failed?1:0
