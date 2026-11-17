import test from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import Module from 'node:module'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
const app=fileURLToPath(new URL('../../',import.meta.url))
const out=await build({entryPoints:[path.join(app,'src/shell/operatingHeaderModel.ts')],bundle:true,write:false,platform:'node',format:'cjs',logLevel:'silent'})
const m=new Module(path.join(app,'scripts/tests/header-corrective-virtual.cjs'));m.filename=path.join(app,'scripts/tests/header-corrective-virtual.cjs');m.paths=Module._nodeModulePaths(app);m._compile(out.outputFiles[0].text,m.filename)
const {headerModel,sourceClockLabel,clockDiagnostics}=m.exports
test('asynchronous response observation uses completion clock without hiding a true future source',()=>{
 const start=Date.parse('2040-01-01T00:00:00Z'),source='2040-01-01T00:00:00.033Z',end=start+40
 assert.match(sourceClockLabel(source,end,source),/<1 min/)
 assert.equal(clockDiagnostics(source,end,source).sourceDeltaMs,-7)
 const future='2040-01-01T00:00:10Z'
 assert.match(sourceClockLabel(future,end,source),/in the future/)
 assert.equal(clockDiagnostics(future,end,source).future,true)
})
test('client behind valid server response is a diagnostic with unverified age, never a fresh claim',()=>{
 const source='2040-01-01T00:00:05Z',server='2040-01-01T00:00:06Z',client=Date.parse('2040-01-01T00:00:00Z')
 assert.match(sourceClockLabel(source,client,server),/client clock precedes server response.*age unverified/)
 assert.equal(clockDiagnostics(source,client,server).future,false)
 assert.equal(clockDiagnostics(source,client,server).clientBehind,true)
 assert.match(sourceClockLabel(source,client),/in the future/)
})
test('clock labels preserve ET DST semantics and reject invalid observations',()=>{
 assert.match(sourceClockLabel('2040-07-01T16:00:00Z',Date.parse('2040-07-01T16:01:00Z')),/12:00 PM ET/)
 assert.match(sourceClockLabel('2040-01-01T16:00:00Z',Date.parse('2040-01-01T16:01:00Z')),/11:00 AM ET/)
 assert.equal(sourceClockLabel('not-a-date',Date.now()),'source time not served')
 assert.equal(sourceClockLabel('2040-01-01T16:00:00',Date.now()),'source time not served')
 assert.equal(sourceClockLabel(null,Date.now()),'source time not served')
})
test('temperature rounds display only and retains exact raw score in evidence',()=>{
 const input={schema:'WealthOperatingHeader@v1',cells:{temperature:{value:{tier:'YELLOW',score:41.8408},display:'YELLOW · 41.8408',verdict:'known',state:'amber'}}}
 const cell=headerModel(input).cells.find(c=>c.id==='temperature')
 assert.equal(cell.display,'YELLOW · 41.8');assert.match(cell.tooltip,/Raw engine score: 41.8408/)
 assert.equal(input.cells.temperature.value.score,41.8408)
})
test('unsupported schema and read failure cannot become an available operating capability',()=>{
 const cell={value:'LIVE',display:'LIVE',verdict:'known',state:'green'}
 const unsupported=headerModel({schema:'Other@v9',cells:{operating_mode:cell}}).cells.find(c=>c.id==='operating_mode')
 assert.equal(unsupported.display,'not served');assert.match(unsupported.tooltip,/Unsupported operating-header schema/)
 const failed=headerModel({schema:'WealthOperatingHeader@v1',cells:{operating_mode:cell}},'HTTP 403').cells.find(c=>c.id==='operating_mode')
 assert.equal(failed.tone,'grey');assert.equal(failed.verdict,'read failed');assert.match(failed.tooltip,/HTTP 403/)
 assert.equal(headerModel(null).queueTotal,null)
})

const semanticWire=(id, value, changes={})=>({schema:'WealthOperatingHeader@v1',cells:{[id]:{value,display:id==='regime'?value.label:'Stored value',clock:'2040-01-01T00:00:00Z',stale_after_s:3600,verdict:'known',state:'grey',...changes}}})
const semanticCell=(id,value,changes={},readError=null)=>headerModel(semanticWire(id,value,changes),readError).cells.find(c=>c.id===id)
let readingModule
async function reading(cell){
 if(!readingModule){
  const bundled=await build({entryPoints:[path.join(app,'src/shell/OperatingHeader.tsx')],bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',loader:{'.css':'empty'},external:['react','react-dom'],logLevel:'silent'})
  const mod=new Module(path.join(app,'scripts/tests/header-reading-virtual.cjs'));mod.filename=path.join(app,'scripts/tests/header-reading-virtual.cjs');mod.paths=Module._nodeModulePaths(app);mod._compile(bundled.outputFiles[0].text,mod.filename);readingModule=mod.exports
 }
 const {createRequire}=await import('node:module'),require=createRequire(import.meta.url)
 return require('react-dom/server').renderToStaticMarkup(require('react').createElement(readingModule.OperatingHeaderReading,{cell}))
}
test('registered regime public labels precede privacy filtering and preserve explicit mapping',()=>{
 const cases=[['risk_on_trend','Risk-on trend','green'],['risk_off','Risk off','red'],['choppy_range','Choppy range','grey'],['high_volatility','High volatility','amber'],['low_volatility_grind','Low-volatility grind','green'],['broad_momentum','Broad momentum','grey'],['unknown','Unknown','grey']]
 for(const [key,label,tone] of cases){const c=semanticCell('regime',{label:key,score:3,confidence:0});assert.equal(c.display,label);assert.equal(c.regimeTone,tone);assert.equal(c.regimeScore,3);assert.equal(c.confidence,0)}
 assert.match(semanticCell('regime',{label:'broad_momentum'}).qualification,/mapping pending review/i)
})
test('unregistered/private-shaped regime names never bypass the unchanged sanitizer',()=>{
 for(const key of ['synthetic_private_account','future_state','__proto__','constructor']){
  const c=semanticCell('regime',{label:key});assert.equal(c.display,'Unrecognized regime');assert.equal(c.regimeTone,'grey');assert.ok(!JSON.stringify(c).includes(key))
 }
 assert.equal(semanticCell('regime',{label:null},{display:null}).display,'not served')
})
test('regime confidence is a fraction and score is engine points, never an inferred percentage',async()=>{
 const good=semanticCell('regime',{label:'risk_off',confidence:.125,score:7});const html=await reading(good)
 assert.match(html,/Confidence 12\.5%/);assert.match(html,/Score 7 points/)
 assert.equal(semanticCell('regime',{label:'risk_off',confidence:0,score:0}).confidence,0)
 for(const bad of [true,'0.5',-1,1.01,NaN,Infinity])assert.equal(semanticCell('regime',{label:'risk_off',confidence:bad}).confidence,null)
 for(const bad of [true,'7',-1,.5,NaN,Infinity])assert.equal(semanticCell('regime',{label:'risk_off',score:bad}).regimeScore,null)
 assert.doesNotMatch(await reading(semanticCell('regime',{label:'risk_off'})),/Confidence 0%|Score 0 points/)
})
test('all five served tiers render exact approved colors without deriving tier from score',async()=>{
 for(const tier of ['GREEN','BLUE','YELLOW','ORANGE','RED']){
  const color=`var(--status-${tier==='YELLOW'?'amber':tier.toLowerCase()})`,c=semanticCell('temperature',{tier,score:12.345});const html=await reading(c)
  assert.equal(c.temperatureTier,tier);assert.equal(c.temperatureColor,color);assert.match(html,new RegExp(`data-temperature-tier="${tier}"`));assert.ok(html.includes(`color:${color}`));assert.match(html,/12\.3/)
 }
 for(const tier of ['NONE','UNKNOWN','future_tier']){const c=semanticCell('temperature',{tier,score:99});assert.equal(c.temperatureColor,null);assert.ok(!['GREEN','BLUE','YELLOW','ORANGE','RED'].includes(c.temperatureTier))}
 for(const bad of [true,'41',-1,100.01,NaN,Infinity]){const c=semanticCell('temperature',{tier:'BLUE',score:bad},{display:'BLUE · invalid score'});assert.equal(c.temperatureScore,null);assert.equal(c.display,'BLUE');assert.doesNotMatch(await reading(c),/invalid score|Infinity|NaN/)}
 const unclassified=semanticCell('temperature',{tier:'synthetic_private_tier',score:99},{state:'green'});assert.equal(unclassified.tone,'grey');assert.equal(unclassified.display,'Unclassified tier · 99.0');assert.ok(!JSON.stringify(unclassified).includes('synthetic_private_tier'))
})
test('retained tier/state and read freshness remain separate in actual rendered reading',async()=>{
 for(const [verdict,label] of [['stale','Stale observation'],['partial','Partial observation'],['unknown','Freshness unknown']]){
  const c=semanticCell('temperature',{tier:'BLUE',score:24},{verdict});const html=await reading(c)
  assert.equal(c.temperatureColor,'var(--status-blue)');assert.match(html,new RegExp(label));assert.doesNotMatch(html,/>Current</)
 }
 const empty=await reading(headerModel(null).cells[0]);assert.doesNotMatch(empty,/data-tone="amber"|data-icon="warning"/);assert.match(empty,/Not served/)
 const failed=semanticCell('regime',{label:'risk_on_trend',score:4,confidence:.8},{},'HTTP 503');assert.equal(failed.tone,'grey');assert.equal(failed.regimeTone,'grey');assert.match(await reading(failed),/Current read failed/)
})
test('VIX stays neutral, stale warning is separate, and only supplied limits enter evidence',async()=>{
 const c=semanticCell('vix',{index:23},{display:'23',verdict:'stale',state:'red',stale_after_s:129600});const html=await reading(c)
 assert.equal(c.tone,'grey');assert.match(html,/data-tone="grey"/);assert.match(html,/data-icon="warning"/);assert.match(html,/Stale observation/);assert.match(c.tooltip,/Freshness limit: 129600 seconds/)
 assert.doesNotMatch(semanticCell('vix',{index:23},{stale_after_s:null}).tooltip,/Freshness limit:/)
})
test('signed estimates keep monetary sign while freshness remains amber',async()=>{
 const loss=semanticCell('session_pl',{amount:-2.5},{display:'-$2.50',verdict:'stale'});const html=await reading(loss)
 assert.match(html,/data-tone="red"/);assert.match(html,/▼ -\$2\.50/);assert.match(html,/Estimate · interval unverified/);assert.match(html,/Stale observation/)
 const zero=await reading(semanticCell('session_pl',{amount:0},{display:'$0'}));assert.doesNotMatch(zero,/▲|▼/)
})
test('mode uses the exact approved target glyph and all eight cells stay in order',async()=>{
 const model=headerModel(null);assert.deepEqual(model.cells.map(c=>c.id),['session','session_pl','account_value','temperature','regime','vix','operating_mode','health'])
 const c=semanticCell('operating_mode',{executionMode:null},{display:'Advisory · execution unknown'});assert.equal(c.icon,'target');const html=await reading(c);assert.match(html,/data-icon="target"/);assert.match(html,/r="9"/);assert.match(html,/r="4"/);assert.match(html,/execution unknown/)
})
