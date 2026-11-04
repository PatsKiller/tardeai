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
console.log(`commsFeedCard actual renders: ${passed} passed, ${failed} failed`)
process.exitCode=failed?1:0
