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
