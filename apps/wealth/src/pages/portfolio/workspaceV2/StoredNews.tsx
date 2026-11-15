// Stored candidates only: explicit user GET, bounded concurrency, no producer or broker invocation.
import { useEffect, useRef, useState } from 'react'
import { getJson } from '../../../api/client'

type Wire = Record<string, unknown>
export interface StoredHeadline { title:string; source:string|null; url:string|null; publishedAt:string|null }
export interface StoredNewsRead {symbol:string;headlines:StoredHeadline[];latest:string|null;rejected:number|null;globalStoredCount:number|null;discarded:number;observedAt:string|null;error:string|null}
export interface StoredNewsProps {symbols:readonly string[]}
export interface NewsCandidate extends StoredHeadline {id:string;symbols:string[];variants:StoredHeadline[];entityMatch:'UNVERIFIED'}
const object=(v:unknown):Wire=>v!==null&&typeof v==='object'&&!Array.isArray(v)?v as Wire:{}
const text=(v:unknown):string|null=>typeof v==='string'&&v.trim()?v:null
const count=(v:unknown):number|null=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0?v:null
export function headlineUrl(v:unknown):string|null {
 const raw=text(v)?.trim();if(!raw)return null
 try{const u=new URL(raw);return (u.protocol==='https:'||u.protocol==='http:')&&!u.username&&!u.password?raw:null}catch{return null}
}
/** Exact normalization, without entity or semantic matching. Punctuation is retained. */
export const normalizedTitle=(title:string)=>title.normalize('NFKC').trim().replace(/\s+/gu,' ').toLowerCase()
/** Preserve the original link for navigation. Only explicit tracking fields and the fragment leave the dedup key. */
export function canonicalHeadlineUrl(raw:unknown):string|null {
 const safe=headlineUrl(raw);if(!safe)return null
 const u=new URL(safe);u.hash=''
 for(const key of [...u.searchParams.keys()])if(/^utm_/i.test(key)||/^(?:gclid|dclid|fbclid|msclkid|mc_cid|mc_eid|_hsenc|_hsmi)$/i.test(key))u.searchParams.delete(key)
 return u.href
}
function clock(v:string|null,label:string):string {
 if(!v)return label+' not served'
 if(!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(v))return label+' '+v+' · time zone not served'
 const at=Date.parse(v);return Number.isFinite(at)?label+' '+new Date(at).toISOString()+' (UTC)':label+' invalid · '+v
}
export const publishedClock=(v:string|null)=>clock(v,'Published')
const instant=(v:string|null)=>v&&/(?:Z|[+-]\d{2}:?\d{2})$/i.test(v)&&Number.isFinite(Date.parse(v))?Date.parse(v):null
const failed=(symbol:string,error:string):StoredNewsRead=>({symbol,headlines:[],latest:null,rejected:null,globalStoredCount:null,discarded:0,observedAt:null,error})
export function decodeStoredNews(body:unknown,symbol:string,observedAt:string|null=null):StoredNewsRead {
 const root=object(body),data=object(root.data)
 if(root.ok===false||data.ok!==true||data.symbol!==symbol||!Array.isArray(data.headlines))return failed(symbol,'Stored news response unavailable or incomplete')
 const headlines:StoredHeadline[]=[];let discarded=0
 for(const h of data.headlines){const r=object(h),title=text(r.title);if(title)headlines.push({title,source:text(r.source),url:headlineUrl(r.url),publishedAt:text(r.published_at)});else discarded++}
 return {symbol,headlines,latest:text(object(data.ingest).latest),rejected:count(data.guard_rejected),globalStoredCount:count(object(data.ingest).guarded_72h),discarded,observedAt,error:null}
}
/** Dedup by normalized exact title OR canonical URL, including transitive connections. All query tags and source variants survive. */
export function deduplicateNews(reads:readonly StoredNewsRead[]):{stories:NewsCandidate[];returned:number;duplicates:number} {
 const inputs=reads.filter(r=>!r.error).flatMap(r=>r.headlines.map(h=>({h,symbol:r.symbol})))
 const parent=inputs.map((_,i)=>i),titles=new Map<string,number>(),urls=new Map<string,number>()
 const find=(i:number):number=>{while(parent[i]!==i){parent[i]=parent[parent[i]];i=parent[i]}return i}
 const join=(a:number,b:number)=>{const x=find(a),y=find(b);if(x!==y)parent[y]=x}
 for(const [i,{h}] of inputs.entries()){
  const title=normalizedTitle(h.title),url=canonicalHeadlineUrl(h.url)
  if(title){const prev=titles.get(title);if(prev!==undefined)join(i,prev);else titles.set(title,i)}
  if(url){const prev=urls.get(url);if(prev!==undefined)join(i,prev);else urls.set(url,i)}
 }
 const groups=new Map<number,typeof inputs>()
 for(const [i,item]of inputs.entries()){const key=find(i),g=groups.get(key)||[];g.push(item);groups.set(key,g)}
 const stories:NewsCandidate[]=[...groups.values()].map(g=>{
  g.sort((a,b)=>(instant(b.h.publishedAt)??-Infinity)-(instant(a.h.publishedAt)??-Infinity)||a.h.title.localeCompare(b.h.title)||a.symbol.localeCompare(b.symbol))
  const h=g[0].h,symbols=[...new Set(g.map(v=>v.symbol))].sort(),variants:StoredHeadline[]=[]
  for(const item of g)if(!variants.some(v=>v.title===item.h.title&&v.url===item.h.url&&v.source===item.h.source&&v.publishedAt===item.h.publishedAt))variants.push(item.h)
  return {...h,id:JSON.stringify([normalizedTitle(h.title),canonicalHeadlineUrl(h.url),symbols]),symbols,variants,entityMatch:'UNVERIFIED' as const}
 })
 stories.sort((a,b)=>(instant(b.publishedAt)??-Infinity)-(instant(a.publishedAt)??-Infinity)||a.id.localeCompare(b.id))
 return {stories,returned:inputs.length,duplicates:inputs.length-stories.length}
}
export function newsSummary(reads:readonly StoredNewsRead[],requested:number) {
 const good=reads.filter(r=>r.error===null),dedup=deduplicateNews(good),guard=good.filter(r=>r.rejected!==null)
 // These diagnostics are global observations repeated by each query; summing would multiply the feed count.
 const global=[...new Map(good.map(r=>[JSON.stringify([r.latest,r.globalStoredCount]),{latest:r.latest,count:r.globalStoredCount}])).values()]
 return {...dedup,successes:good.length,failures:reads.length-good.length,requested,partial:good.length<requested,
  rejected:{value:guard.length?guard.reduce((s,r)=>s+r.rejected!,0):null,n:guard.length,m:good.length},global,
  discarded:good.reduce((s,r)=>s+r.discarded,0),entityMatch:'UNVERIFIED' as const,ingestCompletionAt:null}
}
/** Four requests at most; cancellation/current-run fence also prevents late results from publishing. */
export async function readStoredNewsBatch(symbols:readonly string[],signal:AbortSignal,request:(symbol:string,signal:AbortSignal)=>Promise<StoredNewsRead>,onResult:(read:StoredNewsRead)=>void,isCurrent:()=>boolean=()=>true):Promise<void> {
 let cursor=0
 async function worker(){while(cursor<symbols.length&&!signal.aborted&&isCurrent()){
  const symbol=symbols[cursor++];let result:StoredNewsRead
  try{result=await request(symbol,signal)}catch{result=failed(symbol,'Stored news read failed')}
  if(signal.aborted||!isCurrent())return
  onResult(result)
 }}
 await Promise.all(Array.from({length:Math.min(4,symbols.length)},worker))
}
export function StoredNews({symbols}:StoredNewsProps) {
 const names=[...new Set(symbols.map(s=>s.toUpperCase().trim()).filter(Boolean))].sort(),key=names.join('|')
 const allowed=names.filter(s=>/^[A-Z0-9]{1,8}$/.test(s)),unsupported=names.length-allowed.length
 const controller=useRef<AbortController|null>(null),generation=useRef(0)
 const [state,setState]=useState<{key:string;started:boolean;busy:boolean;reads:StoredNewsRead[]}>({key,started:false,busy:false,reads:[]})
 useEffect(()=>{generation.current++;controller.current?.abort();setState({key,started:false,busy:false,reads:[]});return()=>{generation.current++;controller.current?.abort()}},[key])
 const current=state.key===key?state:{key,started:false,busy:false,reads:[]}
 async function load(){
  controller.current?.abort();const ctl=new AbortController();controller.current=ctl;const run=++generation.current,reads:StoredNewsRead[]=[]
  const isCurrent=()=>!ctl.signal.aborted&&generation.current===run
  setState({key,started:true,busy:true,reads:[]})
  await readStoredNewsBatch(allowed,ctl.signal,async(symbol,signal)=>{
   const env=await getJson<unknown>('/api/v2/news/symbol-headlines?symbol='+encodeURIComponent(symbol)+'&hours=72',signal)
   return env.ok&&env.data!==null?decodeStoredNews(env.data,symbol,env.fetchedAt):failed(symbol,env.timedOut?'Stored news read timed out':'Stored news read failed')
  },result=>{reads.push(result);setState({key,started:true,busy:true,reads:[...reads]})},isCurrent)
  if(isCurrent())setState({key,started:true,busy:false,reads:[...reads]})
 }
 const summary=newsSummary(current.reads,names.length),successes=current.reads.filter(r=>r.error===null)
 return <div aria-busy={current.busy}>
  <p>Source-tagged news candidates for {names.length} filtered holdings at or above the floor. Entity match unverified: this reader supplies ticker tags, without issuer-match evidence. Titles alone do not establish relevance.</p>
  <button type="button" className="hv-link" onClick={load} disabled={current.busy||!allowed.length}>{current.busy?'Reading stored news…':current.started?'Refresh stored news':'Load stored news'}</button>
  {!names.length?<p>No eligible holding in this slice. No news read requested.</p>:null}
  {unsupported?<p>{unsupported} symbol{unsupported===1?'':'s'} cannot be queried by this reader; coverage is partial.</p>:null}
  {current.started?<p role="status">{summary.successes} of {names.length} holdings read{summary.partial?' · partial':''}; {summary.returned} candidate records → {summary.stories.length} distinct stories; {summary.duplicates} duplicate record{summary.duplicates===1?'':'s'} combined. A zero return does not establish a current news feed.</p>:<p>News has not been read for this filter selection.</p>}
  {current.started?<details><summary>Query coverage, source clocks and deduplication evidence</summary>
   <p>Window: 72 hours by source publication time. Actual ingest completion time and ingest freshness verdict are not served. The wire's ingest.latest is the latest global stored publication; ingest.guarded_72h is the global article count, without a guard predicate. These observations are not added across queries.</p>
   {summary.global.map((g,i)=><p key={i}>Global stored articles (72h): {g.count??'not served'} · {clock(g.latest,'Latest global publication')}</p>)}
   <p>Guard rejections summed per query: {summary.rejected.value??'not served'} · counts served for {summary.rejected.n} of {summary.rejected.m} successful reads; the same source record may be counted by multiple queries. Malformed candidate records omitted: {summary.discarded}.</p>
   <p>Deduplication combines exact normalized titles or matching source URLs after removing only known tracking parameters and fragments. Original links and source variants are retained. Entity-match evidence remains unavailable.</p>
   {[...current.reads].sort((a,b)=>a.symbol.localeCompare(b.symbol)).map(r=><p key={r.symbol}>{r.symbol} · {r.error||r.headlines.length+' candidate records'} · guard rejected {r.rejected??'not served'} · global 72h count {r.globalStoredCount??'not served'} · {clock(r.latest,'Global latest stored publication')} · {clock(r.observedAt,'Browser read started')} · actual ingest completion clock not served.</p>)}
  </details>:null}
  {current.reads.filter(r=>r.error!==null).map(r=><p key={r.symbol}>{r.symbol} · {r.error}; no empty-news verdict inferred.</p>)}
  {summary.stories.map(h=><div key={h.id}><strong>Source tags: {h.symbols.join(', ')}</strong> · {h.url?<a href={h.url} target="_blank" rel="noopener noreferrer">{h.title}</a>:<span>{h.title} · safe source link not served</span>}<small>{h.source||'Source not served'} · {publishedClock(h.publishedAt)} · entity match unverified</small>
   {h.variants.length>1?<details><summary>{h.variants.length} source variants · original links and clocks</summary>{h.variants.map((v,i)=><p key={i}>{v.url?<a href={v.url} target="_blank" rel="noopener noreferrer">{v.title}</a>:v.title}<small>{v.source||'Source not served'} · {publishedClock(v.publishedAt)}</small></p>)}</details>:null}
  </div>)}
  {successes.filter(r=>!r.headlines.length).map(r=><p key={r.symbol}>{r.symbol} · no source-tagged candidates returned by the 72-hour query; ingest freshness and entity relevance unverified.</p>)}
 </div>
}
