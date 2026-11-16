import { useState } from 'react'
import type { Market, ReviewQueue } from './homeAdapter'
import type { RenderState } from '../../components/renderState'
import { HomeSecondary, HomeEvidenceButton, HomeMetricTiles, HomePanel, HomeFact, HomeClock, HomeUnavailable } from './HomeV2Parts'
import type { HomeV2Sections } from './HomeV2Parts'
export function HomeNeedsPage({sections={}}:{queue?:RenderState<ReviewQueue>;market?:RenderState<Market>;now?:number;sections?:HomeV2Sections}) {
 const [history,setHistory]=useState(false)
 return <div className="home-v2" data-home-view="needs"><section className="hero"><span className="home-v2-muted">Your review queue · links open the existing owning desk</span><HomeEvidenceButton sections={sections}/></section>
 <HomeMetricTiles id="summary" labels={['Money decisions today','Protect money','Decide','Fix system','Queue freshness']} section={sections.summary}/>
 <div className="home-v2-grid-two"><HomePanel id="protect" title="Protect money" icon="shield" section={sections.protect}/><HomePanel id="decide" title="Decide" icon="bell" section={sections.decide}/></div>
 <div className="home-v2-grid-two"><HomePanel id="reentry" presentation="reentry" title="Re-entry watch" icon="swap" section={sections.reentry}/><HomePanel id="fix" title="Fix system" icon="gear" section={sections.fix} limit={6}/></div>
 {sections.protectionInventory?<HomeSecondary title="protection inventory · positions, not task groups"><HomePanel id="protectionInventory" title="Protection inventory · positions, not queue tasks" icon="shield" section={sections.protectionInventory}/></HomeSecondary>:null}
 {sections.sourceNotices?<HomeSecondary title="source-quality notices · separate population"><HomePanel id="sourceNotices" title="Source-quality notices · separate from task queue" icon="gear" section={sections.sourceNotices}/></HomeSecondary>:null}
 <section className="home-v2-history" data-home-history="true"><button className="home-v2-history-toggle" aria-expanded={history} aria-controls="home-v2-incident-records" onClick={()=>setHistory(!history)}>{history?'Hide':'Show'} recorded incidents · history, not current gaps{sections.incidents?.totalLabel?' · '+sections.incidents.totalLabel:''}</button>{!sections.incidents?.available?<HomeUnavailable reason={sections.incidents?.reason||'Recorded incident source not served.'}/>:null}{sections.incidents?.metrics?.length?<div className="home-v2-metrics">{sections.incidents.metrics.map((f,i)=><HomeFact fact={f} section={sections.incidents} key={i}/>)}</div>:null}<HomeClock clock={sections.incidents?.clock} source={sections.incidents?.source}/><div id="home-v2-incident-records" hidden={!history}>{history?<HomePanel id="incidents" title="Recorded incidents · history, not current gaps" icon="clock" section={sections.incidents}/>:null}</div></section>
 </div>
}
