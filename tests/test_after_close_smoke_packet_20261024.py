"""WP-36 strict smoke protocol: hermetic fake transport/clock; no sockets, live state or credentials."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'docs/ops/packets/after-close-crawler-20261024-wp36/strict-smoke.mjs'


def test_strict_observer_protocol_without_network(tmp_path):
    driver = tmp_path / 'protocol.mjs'
    driver.write_text(r'''
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { EventEmitter } from 'node:events'
import http from 'node:http'
const mod = await import(process.argv[2])
const { afterClose, policy, StrictTransport, Refused, routeRead, rawGet, HEAVY, LIVE_ORIGIN } = mod
const cases=[]
function pass(name){cases.push(name)}
assert.throws(()=>afterClose(undefined,new Date('2026-10-24T03:00:00Z')),/AFTER_CLOSE_FLAG_REQUIRED/)
afterClose('1',new Date('2026-10-24T03:00:00Z'))
afterClose('1',new Date('2026-10-24T14:00:00Z'))
for(const at of ['2026-10-23T08:00:00Z','2026-10-23T20:14:59Z'])assert.throws(()=>afterClose('1',new Date(at)),/MARKET_WINDOW_REFUSED/)
afterClose('1',new Date('2026-10-23T20:15:00Z'))
pass('explicit flag, ET/DST market window boundaries and weekend')
for(const method of ['HEAD','POST','PUT','PATCH','DELETE','OPTIONS'])assert.throws(()=>policy('/v3/retirement',method),/METHOD_REFUSED/)
pass('GET only including refusing HEAD')
for(const url of ['https://127.0.0.1:7777/v3/','http://localhost:7777/v3/','http://127.0.0.1:7778/v3/','http://example.invalid/','http://user:fixture@127.0.0.1:7777/v3/'])assert.throws(()=>policy(url,'GET'),/ORIGIN_REFUSED/)
pass('exact origin, port and no URL userinfo')
for(const headers of [{cookie:'fixture-only'},{Authorization:'fixture-only'},{'Proxy-Authorization':'fixture-only'}])assert.throws(()=>policy('/v3/retirement','GET',headers),/CLIENT_CREDENTIALS_REFUSED/)
assert.throws(()=>policy('/api/v2/health?token=fixture-only','GET'),/CREDENTIAL_QUERY_REFUSED/)
pass('credential headers and query inputs never reach transport')
for(const url of ['/api/v3/maturity/memory','/api/v2/hermes/sources','/api/v3/hermes/status','/api/v2/health/remediation','/api/v2/health/log','/api/v2/watchlist/items?symbols=AAA','/api/v2/ui/prefs/get?key=portfolio.shared-symbol-context']){
 assert.ok(HEAVY.test(url));assert.throws(()=>policy(url,'GET'),/OWNER_HELD_HEAVY_ENDPOINT/)
}
for(const url of ['/api/v3/maturity','/api/v2/hermes','/api/v3/hermes?x=1'])assert.throws(()=>policy(url,'GET'),/OWNER_HELD_HEAVY_ENDPOINT/)
pass('all existing HEAVY guard branches remain owner-held')
for(const url of ['/api/v2/broker/status','/api/v2/orders','/api/v2/stop/state','/api/v2/schwab/status','/api/v2/jobs/retry'])assert.throws(()=>policy(url,'GET'),/OWNER_HELD_BUSINESS_OR_AUTH_ENDPOINT|ACTION_URL_REFUSED/)
assert.throws(()=>policy('/api/v2/health?refresh=1','GET'),/ACTION_QUERY_REFUSED/)
pass('business/auth/action endpoints refused before network')
assert.throws(()=>new StrictTransport({gapMs:999}),/RATE_CONFIG_REFUSED/)
assert.throws(()=>new StrictTransport({origin:'http://localhost:7777'}),/TRANSPORT_ORIGIN_REFUSED/)
pass('rate/origin configuration fail closed')
let ms=0;const calls=[];const fake=async request=>{calls.push({path:request.url.pathname,at:ms});return {status:200,headers:{},body:Buffer.from('{}')}}
const t=new StrictTransport({clock:()=>ms,sleep:async n=>{ms+=n},send:fake,guard:()=>{}})
await Promise.all(['/v3/retirement','/v3/assets/example.js','/api/v2/health'].map(p=>t.get(p)))
assert.deepEqual(calls.map(c=>c.at),[0,1000,2000]);assert.equal(calls.length,3)
pass('global serialized >=1000ms spacing covers documents assets and APIs concurrently')
let earlyClock=0;const earlyStarts=[]
const early=new StrictTransport({clock:()=>earlyClock,sleep:async n=>{earlyClock+=Math.max(0.25,n-0.75)},guard:()=>{},send:async()=>{earlyStarts.push(earlyClock);return {status:200,headers:{},body:Buffer.alloc(0)}}})
await early.get('/v3/retirement');await early.get('/v3/reports')
assert.ok(earlyStarts[1]-earlyStarts[0]>=1000,JSON.stringify(earlyStarts))
pass('early timer wakeups cannot shorten the global interval')

for(const status of [401,403,500,503,302,404]){
 let sent=0
 const x=new StrictTransport({clock:()=>0,sleep:async()=>{},guard:()=>{},send:async()=>{sent++;return {status,headers:{},body:Buffer.alloc(0)}}})
 const queued=[x.get('/v3/retirement'),x.get('/v3/reports')]
 const results=await Promise.allSettled(queued)
 assert.equal(sent,1);assert.ok(results.every(x=>x.status==='rejected'));assert.ok(x.halted)
}
pass('auth redirects 4xx and 5xx stop queued requests without retries')
let sent=0
const timeout=new StrictTransport({guard:()=>{},send:async()=>{sent++;throw new Refused('REQUEST_TIMEOUT')}})
await assert.rejects(timeout.get('/v3/retirement'),/REQUEST_TIMEOUT/)
await assert.rejects(timeout.get('/v3/reports'),/REQUEST_TIMEOUT/);assert.equal(sent,1)
pass('timeout fail-stop without alternate route or retry')
let guardCalls=0,sentAfterGuard=0
const g=new StrictTransport({guard:()=>{if(++guardCalls>1)throw new Refused('MARKET_WINDOW_REFUSED')},send:async()=>{sentAfterGuard++;return {status:200,headers:{},body:Buffer.alloc(0)}}})
await assert.rejects(g.get('/v3/retirement'),/MARKET_WINDOW_REFUSED/);assert.equal(sentAfterGuard,0)
pass('market-window guard rechecked immediately before send')
let closedSent=0
const closed=new StrictTransport({guard:()=>{},send:async()=>{closedSent++;return {status:200,headers:{},body:Buffer.alloc(0)}}})
await assert.rejects(closed.get('/v3/retirement',{isActive:()=>false}),/VIEW_CLOSED/)
assert.equal(closedSent,0);assert.equal(closed.pending,0)
pass('closed-view requests never reach network and pending accounting settles')
let ids=0,clock=0
const identity=new StrictTransport({guard:()=>{},clock:()=>clock,sleep:async n=>{clock+=n},send:async()=>({status:200,headers:{},body:Buffer.from(JSON.stringify({git_sha:(++ids===1?'a':'b').repeat(40)}))})})
assert.equal(await identity.identity(),'a'.repeat(40))
await assert.rejects(identity.identity(),/SERVED_RELEASE_DRIFT/)
await assert.rejects(identity.get('/v3/retirement'),/SERVED_RELEASE_DRIFT/);assert.equal(ids,2)
pass('exact SHA pin and release drift stop subsequent requests')
const badIdentity=new StrictTransport({guard:()=>{},send:async()=>({status:200,headers:{},body:Buffer.from('{"git_sha":"short"}')})})
await assert.rejects(badIdentity.identity(),/BUILD_IDENTITY_UNPROVEN/)
pass('missing or short served identity cannot produce acceptance')
let full,aborted=false
const route={request:()=>({url:()=>LIVE_ORIGIN+'/v3/retirement',method:()=> 'GET',headers:()=>({}),allHeaders:async()=>({}),frame:()=>({page:()=>({isClosed:()=>false})})}),fulfill:async r=>{full=r},abort:async()=>{aborted=true}}
const transport=new StrictTransport({guard:()=>{},send:async()=>({status:200,headers:{'set-cookie':'fixture-only','www-authenticate':'fixture-only','content-type':'text/html'},body:Buffer.from('<html/>')})})
await routeRead(route,transport,[]);assert.equal(aborted,false);assert.deepEqual(full.headers,{'content-type':'text/html'})
pass('browser fulfillment never loads Set-Cookie or auth response headers')
let attempted=0
const notGet=new StrictTransport({guard:()=>{},send:async()=>{attempted++;throw Error('must not send')}})
const held=[];await routeRead({request:()=>({url:()=>LIVE_ORIGIN+'/api/v2/jobs/retry',method:()=> 'POST',headers:()=>({}),allHeaders:async()=>({})}),abort:async()=>{},fulfill:async()=>{throw Error('must abort')}},notGet,held)
assert.equal(attempted,0);assert.equal(held[0].code,'METHOD_REFUSED')
pass('browser mutation requests aborted before HTTP')
const saved=http.request;let rawOptions,rawCalls=0
http.request=(url,options,cb)=>{rawOptions=options;rawCalls++;const req=new EventEmitter();req.setTimeout=()=>{};req.end=()=>{const res=new EventEmitter();res.statusCode=302;res.headers={location:'http://example.invalid/','set-cookie':'fixture-only'};res.resume=()=>{};cb(res)};return req}
try{const r=await rawGet({url:new URL(LIVE_ORIGIN+'/v3/retirement'),timeoutMs:10,maxBytes:100});assert.equal(r.status,302);assert.equal(rawCalls,1);assert.equal(rawOptions.method,'GET');assert.equal(rawOptions.headers.cookie,undefined);assert.equal(rawOptions.headers.authorization,undefined)}finally{http.request=saved}
pass('direct HTTP has fixed GET whitelist headers and never follows redirects')
http.request=(url,options,cb)=>{const req=new EventEmitter();req.end=()=>{};req.destroy=e=>req.emit('error',e);return req}
try{await assert.rejects(rawGet({url:new URL(LIVE_ORIGIN+'/v3/retirement'),timeoutMs:5,maxBytes:100}),/REQUEST_TIMEOUT/)}finally{http.request=saved}
pass('absolute wall-clock deadline stops a hung request')
http.request=(url,options,cb)=>{const req=new EventEmitter();req.destroy=e=>req.emit('error',e);req.end=()=>{const res=new EventEmitter();res.statusCode=200;res.headers={};cb(res);res.emit('data',Buffer.from('too-large'));res.emit('end')};return req}
try{await assert.rejects(rawGet({url:new URL(LIVE_ORIGIN+'/v3/retirement'),timeoutMs:100,maxBytes:4}),/RESPONSE_SIZE_REFUSED/)}finally{http.request=saved}
pass('response size cap refuses an oversized response')

const source=await fs.readFile(process.argv[2].replace('file://',''),'utf8')
assert.ok(!/\.(click|dblclick|press|fill|addCookies|storageState|launchPersistentContext)\s*\(/.test(source))
assert.match(source,/routeWebSocket/);assert.match(source,/serviceWorkers: 'block'/);assert.match(source,/ws\.close\(\)/)
assert.ok(!source.includes('cc_client')&&!source.includes('cc_urlopen'))
pass('no click/profile/cookie/auth helper operations and WS/SW blocking present')
console.log(JSON.stringify({passed:cases.length,cases,real_network_requests:0}))
''')
    env = {k: v for k, v in os.environ.items() if k not in ('NODE_OPTIONS', 'NODE_PATH')}
    result = subprocess.run(['node', str(driver), MODULE.as_uri()], capture_output=True, text=True,
                            timeout=30, cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    proof = json.loads(result.stdout.strip().splitlines()[-1])
    assert proof['passed'] == 21 and proof['real_network_requests'] == 0
    print(json.dumps(proof, sort_keys=True))
