import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

const G='#0ecb81',R='#f6465d',Y='#f0b90b',B='#4a90f4',DIM='#848e9c',
  CYAN='#00d2d3',PURPLE='#a855f7',ROSE='#fb7185',ORANGE='#f97316',TEAL='#2dd4bf',GOLD='#eab308'
const rgba=(c:string,a:number)=>{const m:Record<string,string>={[G]:'14,203,129',[R]:'246,70,93',[Y]:'240,185,11',[B]:'74,144,244',[CYAN]:'0,210,211',[PURPLE]:'168,85,247',[ROSE]:'251,113,133',[ORANGE]:'249,115,22',[TEAL]:'45,212,191',[GOLD]:'234,179,8'};return`rgba(${m[c]||'128,128,128'},${a})`}

const AGENT_CLR:Record<string,string>={Maria:ROSE,maria:ROSE,Risk:ORANGE,risk_agent:ORANGE,Steph:TEAL,steph:TEAL,Alex:PURPLE,alex:PURPLE,Tax:G,tax_agent:G,Aegis:GOLD,aegis:GOLD,synthesis:GOLD,Iris:CYAN,operator:'#aaa',system:DIM}
const ac=(n:string)=>AGENT_CLR[n]||DIM
const SEV_CLR:Record<string,string>={critical:R,high:ORANGE,medium:Y,low:B,info:DIM}
const STATUS_CLR:Record<string,string>={blocked:R,ready:G,running:B,waiting:Y,stale:ORANGE,completed:'#555'}

function timeAgo(ts:string|null|undefined):string{if(!ts)return'never';const d=new Date(ts);if(isNaN(d.getTime()))return'never';const s=Math.floor((Date.now()-d.getTime())/1000);if(s<60)return'now';if(s<3600)return`${Math.floor(s/60)}m`;if(s<86400)return`${Math.floor(s/3600)}h`;return`${Math.floor(s/86400)}d`}
const fc=(ts:string|null|undefined,h=24)=>{if(!ts)return R;const hrs=(Date.now()-new Date(ts).getTime())/3.6e6;return hrs<h?G:hrs<h*3?Y:R}

function AgentChip({name}:{name:string}){const c=ac(name);return<span style={{display:'inline-flex',alignItems:'center',gap:3,padding:'1px 6px',borderRadius:3,fontSize:9,fontWeight:700,background:rgba(c,.15),color:c,whiteSpace:'nowrap'}}><span style={{width:5,height:5,borderRadius:'50%',background:c}}/>{name}</span>}
function SevStripe({severity}:{severity:string}){const c=SEV_CLR[severity]||DIM;return<span style={{padding:'1px 6px',borderRadius:10,fontSize:8,fontWeight:800,background:rgba(c,.15),color:c,textTransform:'uppercase'}}>{severity}</span>}
function StatusPill({status}:{status:string}){const c=STATUS_CLR[status]||DIM;return<span style={{padding:'1px 6px',borderRadius:10,fontSize:8,fontWeight:800,background:rgba(c,.12),color:c,textTransform:'uppercase'}}>{status}</span>}

export default function AgentCollaboration(){
  const [rk,setRk]=useState(0)
  const [selectedMission,setSelectedMission]=useState<any>(null)
  const {data:collab}=useApi<any>(`/api/v2/agent-collaboration?_r=${rk}`,60000)

  const summary=collab?.summary||{}
  const johnActions:any[]=collab?.john_next_actions||[]
  const missions:any[]=collab?.mission_groups||[]
  const network:any[]=collab?.agent_network||[]
  const trustColor=summary.system_trust_state==='fresh'?G:summary.system_trust_state==='weekend'?B:summary.system_trust_state==='stale'?Y:R

  return(
    <div style={{padding:'16px 24px',maxWidth:1400}}>
      <PageHeader title="Agent Collaboration" subtitle="Mission-control view — what agents are doing, what's blocked, what needs John" actions={
        <button onClick={()=>{setRk(k=>k+1);setSelectedMission(null)}} style={{fontSize:10,padding:'4px 12px',border:'none',borderRadius:4,background:'var(--accent)',color:'#fff',cursor:'pointer',fontWeight:700}}>Refresh</button>
      }/>

      {/* ═══ COMMAND STRIP ═══ */}
      <div style={{display:'flex',gap:6,marginBottom:14,flexWrap:'wrap'}}>
        {([
          ['Missions',summary.total_missions,B],
          ['Ready for John',summary.ready_for_operator,G],
          ['Blocked',summary.blocked_missions,R],
          ['Stale',summary.stale_missions,ORANGE],
        ] as [string,number,string][]).map(([l,v,c])=>(
          <div key={l} style={{flex:'1 1 100px',padding:'8px 12px',borderRadius:6,background:(v??0)>0?rgba(c,.08):'var(--bg1)',border:`1px solid ${(v??0)>0?c+'44':'var(--border)'}`}}>
            <div style={{fontSize:8,color:DIM,textTransform:'uppercase',letterSpacing:'.4px',fontWeight:700}}>{l}</div>
            <div style={{fontSize:22,fontWeight:800,color:(v??0)>0?c:DIM}}>{v??0}</div>
          </div>
        ))}
        <div style={{flex:'1 1 130px',padding:'8px 12px',borderRadius:6,background:rgba(trustColor,.08),border:`1px solid ${trustColor}33`}}>
          <div style={{fontSize:8,color:DIM,textTransform:'uppercase',letterSpacing:'.4px',fontWeight:700}}>System Trust</div>
          <div style={{fontSize:16,fontWeight:800,color:trustColor,marginTop:2}}>{(summary.system_trust_state||'—').toUpperCase()}</div>
          <div style={{fontSize:9,color:fc(summary.last_aegis_synthesis_at,12)}}>Aegis: {timeAgo(summary.last_aegis_synthesis_at)}</div>
        </div>
      </div>

      {/* ═══ JOHN'S NEXT ACTIONS ═══ */}
      {johnActions.length>0&&(
        <div style={{marginBottom:16}}>
          <div style={{fontSize:11,fontWeight:700,color:G,textTransform:'uppercase',letterSpacing:'.5px',marginBottom:6}}>John's Next Actions</div>
          <div style={{display:'flex',flexDirection:'column',gap:4}}>
            {johnActions.map((a,i)=>{
              const c=SEV_CLR[a.severity]||DIM
              return(
                <div key={i} onClick={()=>{
                  const m=missions.find((m:any)=>m.mission_id===a.mission_id)
                  if(m)setSelectedMission(m)
                }} style={{
                  padding:'8px 12px',borderRadius:6,cursor:'pointer',
                  background:rgba(c,.06),border:`1px solid ${c}22`,
                  borderLeft:`3px solid ${c}`,transition:'all .1s',
                }}>
                  <div style={{display:'flex',alignItems:'center',gap:6}}>
                    <SevStripe severity={a.severity}/>
                    <span style={{fontWeight:700,fontSize:12}}>{a.label}</span>
                    {a.url&&<span style={{marginLeft:'auto',fontSize:9,color:B,cursor:'pointer'}}>Open →</span>}
                  </div>
                  <div style={{fontSize:10,color:DIM,marginTop:2}}>{a.reason}</div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ═══ TWO PANE: MISSIONS + DETAIL ═══ */}
      <div style={{display:'flex',gap:14,alignItems:'flex-start'}}>

        {/* LEFT: Mission Groups */}
        <div style={{flex:selectedMission?'0 0 45%':'1',minWidth:0}}>
          <div style={{fontSize:11,fontWeight:700,color:DIM,textTransform:'uppercase',letterSpacing:'.5px',marginBottom:6}}>Mission Groups</div>
          {!missions.length?(
            <Card title=""><div style={{textAlign:'center',padding:32,color:DIM}}>No active missions. System idle.</div></Card>
          ):(
            <div style={{display:'flex',flexDirection:'column',gap:6}}>
              {missions.map((m:any)=>{
                const isSelected=selectedMission?.mission_id===m.mission_id
                const sevC=SEV_CLR[m.severity]||DIM
                const statusC=STATUS_CLR[m.status]||DIM
                return(
                  <div key={m.mission_id} onClick={()=>setSelectedMission(isSelected?null:m)} style={{
                    padding:'10px 14px',borderRadius:8,cursor:'pointer',
                    background:isSelected?rgba(B,.08):'var(--bg1)',
                    border:isSelected?`1px solid ${B}55`:'1px solid var(--border)',
                    borderLeft:`4px solid ${sevC}`,
                    transition:'all .12s',
                  }}>
                    {/* Row 1: title + badges */}
                    <div style={{display:'flex',alignItems:'center',gap:6,marginBottom:4}}>
                      <span style={{fontWeight:700,fontSize:13,flex:1}}>{m.title}</span>
                      <SevStripe severity={m.severity}/>
                      <StatusPill status={m.status}/>
                    </div>
                    {/* Row 2: stats + agents */}
                    <div style={{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap',marginBottom:4}}>
                      <span style={{fontSize:10,color:DIM}}>{m.thread_count} threads</span>
                      {m.blocked_count>0&&<span style={{fontSize:10,color:R,fontWeight:700}}>{m.blocked_count} blocked</span>}
                      {m.ready_count>0&&<span style={{fontSize:10,color:G,fontWeight:700}}>{m.ready_count} ready</span>}
                      <span style={{fontSize:9,color:DIM}}>Owner: <span style={{color:ac(m.primary_owner||'system'),fontWeight:600}}>{m.primary_owner}</span></span>
                      <span style={{fontSize:9,color:fc(m.updated_at)}}>{timeAgo(m.updated_at)}</span>
                    </div>
                    {/* Row 3: agents */}
                    {(m.agents||[]).length>0&&(
                      <div style={{display:'flex',gap:3,flexWrap:'wrap',marginBottom:4}}>
                        {(m.agents as string[]).slice(0,5).map((a:string)=><AgentChip key={a} name={a}/>)}
                      </div>
                    )}
                    {/* Row 4: next action */}
                    {m.next_action&&(
                      <div style={{fontSize:10,color:statusC,fontWeight:600}}>→ {m.next_action.label}</div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* RIGHT: Selected Mission Detail */}
        {selectedMission&&(
          <div style={{flex:'0 0 53%',maxHeight:'calc(100vh - 200px)',overflowY:'auto'}}>
            <Card title="">
              <div style={{position:'relative'}}>
                <button onClick={()=>setSelectedMission(null)} style={{position:'absolute',top:-4,right:0,background:'none',border:'none',color:DIM,cursor:'pointer',fontSize:14}}>✕</button>

                {/* Mission header */}
                <div style={{marginBottom:14}}>
                  <div style={{fontSize:18,fontWeight:800,marginBottom:4}}>{selectedMission.title}</div>
                  <div style={{display:'flex',gap:6,alignItems:'center'}}>
                    <SevStripe severity={selectedMission.severity}/>
                    <StatusPill status={selectedMission.status}/>
                    <span style={{fontSize:10,color:DIM}}>Owner: <span style={{fontWeight:700,color:ac(selectedMission.primary_owner||'system')}}>{selectedMission.primary_owner}</span></span>
                    <span style={{fontSize:9,color:fc(selectedMission.updated_at)}}>{timeAgo(selectedMission.updated_at)}</span>
                  </div>
                </div>

                {/* Why this matters */}
                {selectedMission.next_action?.reason&&(
                  <div style={{marginBottom:14,padding:'8px 12px',borderRadius:6,background:'var(--bg0)'}}>
                    <div style={{fontSize:9,fontWeight:700,color:DIM,textTransform:'uppercase',marginBottom:3}}>Why This Matters</div>
                    <div style={{fontSize:11}}>{selectedMission.next_action.reason}</div>
                  </div>
                )}

                {/* Blocker */}
                {selectedMission.primary_blocker&&(
                  <div style={{marginBottom:14,padding:'8px 12px',borderRadius:6,background:rgba(R,.08),border:`1px solid ${R}22`}}>
                    <div style={{fontSize:9,fontWeight:700,color:R,textTransform:'uppercase',marginBottom:3}}>Blocker</div>
                    <div style={{fontSize:11,color:R,fontWeight:600}}>{selectedMission.primary_blocker}</div>
                  </div>
                )}

                {/* Agents involved */}
                {(selectedMission.agents||[]).length>0&&(
                  <div style={{marginBottom:14}}>
                    <div style={{fontSize:9,fontWeight:700,color:DIM,textTransform:'uppercase',marginBottom:4}}>Agents Involved</div>
                    <div style={{display:'flex',gap:4,flexWrap:'wrap'}}>
                      {(selectedMission.agents as string[]).map((a:string)=><AgentChip key={a} name={a}/>)}
                    </div>
                  </div>
                )}

                {/* Next action for operator */}
                {selectedMission.next_action&&(
                  <div style={{marginBottom:14}}>
                    <div style={{fontSize:9,fontWeight:700,color:G,textTransform:'uppercase',marginBottom:4}}>What John Should Do</div>
                    <div style={{padding:'8px 12px',borderRadius:6,background:rgba(G,.08),border:`1px solid ${G}22`,fontSize:11,color:G,fontWeight:600,cursor:selectedMission.next_action.url?'pointer':'default'}}
                      onClick={()=>{if(selectedMission.next_action.url)window.location.href=selectedMission.next_action.url}}>
                      {selectedMission.next_action.label}
                      {selectedMission.next_action.url&&<span style={{marginLeft:8,fontSize:9}}>→ Open page</span>}
                    </div>
                  </div>
                )}

                {/* Threads inside this mission */}
                {(selectedMission.threads||[]).length>0&&(
                  <div style={{marginBottom:14}}>
                    <div style={{fontSize:9,fontWeight:700,color:DIM,textTransform:'uppercase',marginBottom:6}}>Items in This Mission ({selectedMission.threads.length})</div>
                    <div style={{maxHeight:300,overflowY:'auto'}}>
                      {(selectedMission.threads as any[]).map((t:any,i:number)=>(
                        <div key={i} style={{
                          padding:'6px 10px',marginBottom:3,borderRadius:4,
                          background:'var(--bg0)',borderLeft:`3px solid ${STATUS_CLR[t.status]||DIM}`,
                          fontSize:11,
                        }}>
                          <div style={{display:'flex',alignItems:'center',gap:6}}>
                            <span style={{fontWeight:700}}>{t.subject}</span>
                            <StatusPill status={t.status}/>
                            {t.thesis&&<span style={{fontSize:9,color:t.thesis==='triggered'?R:t.thesis==='danger'?R:t.thesis==='warning'?Y:t.thesis==='intact'?G:DIM,fontWeight:600}}>{t.thesis}</span>}
                            {t.signal&&<span style={{fontSize:9,color:DIM}}>{t.signal}</span>}
                            {t.confidence!=null&&<span style={{fontSize:9,color:DIM}}>conf: {Number(t.confidence).toFixed(2)}</span>}
                          </div>
                          {t.detail&&<div style={{fontSize:10,color:DIM,marginTop:2}}>{t.detail}</div>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Mission stats */}
                <div style={{fontSize:9,color:DIM,display:'flex',gap:12}}>
                  <span>Threads: {selectedMission.thread_count}</span>
                  <span>Blocked: {selectedMission.blocked_count}</span>
                  <span>Ready: {selectedMission.ready_count}</span>
                </div>
              </div>
            </Card>
          </div>
        )}
      </div>

      {/* ═══ AGENT NETWORK (when no mission selected) ═══ */}
      {!selectedMission&&network.length>0&&(
        <div style={{marginTop:16}}>
          <Card title="Agent Handoff Network">
            <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(280px,1fr))',gap:6}}>
              {network.filter((e:any)=>e.from_agent!=='synthesis'&&e.to_agent!=='human_review').slice(0,8).map((e:any,i:number)=>(
                <div key={i} style={{display:'flex',alignItems:'center',gap:5,padding:'5px 8px',borderRadius:4,background:'var(--bg0)'}}>
                  <AgentChip name={e.from_agent}/><span style={{color:DIM,fontSize:10}}>→</span><AgentChip name={e.to_agent}/>
                  <span style={{marginLeft:'auto',fontSize:10,fontWeight:700}}>{e.cnt}</span>
                  {(e.escalated||0)>0&&<span style={{fontSize:9,color:R,fontWeight:700}}>{e.escalated} esc</span>}
                  <span style={{fontSize:8,color:fc(e.latest)}}>{timeAgo(e.latest)}</span>
                </div>
              ))}
            </div>
            {network.some((e:any)=>e.to_agent==='human_review')&&(<>
              <div style={{fontSize:9,fontWeight:700,color:DIM,textTransform:'uppercase',marginTop:10,marginBottom:4}}>Escalations to Operator</div>
              <div style={{display:'flex',gap:6,flexWrap:'wrap'}}>
                {network.filter((e:any)=>e.to_agent==='human_review').map((e:any,i:number)=>(
                  <div key={i} style={{display:'flex',alignItems:'center',gap:4,padding:'4px 8px',borderRadius:4,background:rgba(ORANGE,.08),fontSize:10}}>
                    <AgentChip name={e.from_agent}/><span style={{color:ORANGE}}>→ Operator</span>
                    <span style={{fontWeight:700}}>{e.cnt}</span>
                  </div>
                ))}
              </div>
            </>)}
          </Card>
        </div>
      )}
    </div>
  )
}
