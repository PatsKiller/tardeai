import type { HomeTodayModel } from './homeAdapter'
import { HomeEvidenceButton, HomeFact, HomeGauge, HomeMetricTiles, HomePanel, HomeRows } from './HomeV2Parts'
import type { HomeV2Sections } from './HomeV2Parts'
export function HomeTodayPage({sections={},cio}:{model?:HomeTodayModel;now?:number;cio?:()=>void;sections?:HomeV2Sections}) {
 const stance=sections.stance,stanceFacts=['Buys','Stops to decide','Unprotected','Re-entry'].map(label=>stance?.metrics?.find(f=>f.label.toLowerCase()===label.toLowerCase())||{label,value:null,qualifier:`${label}: stored field not served`})
 return <div className="home-v2" data-home-view="today"><section className="hero"><span className="home-v2-muted">Stored decisions and source evidence · read-only</span><div className="home-v2-links">{cio?<button onClick={cio}>CIO context</button>:null}<HomeEvidenceButton sections={sections}/></div></section>
 <HomePanel id="stance" title="Today's stance" icon="thermometer" section={stance?{...stance,notes:stance.notes?.slice(1)}:undefined}><div className="home-v2-stance"><div><p className="home-v2-stance-line">{stance?.notes?.[0]||'Stance not served'}</p><div className="home-v2-metrics">{stance?.metrics?.filter(f=>['tier','score'].includes(f.label.toLowerCase())).map((f,i)=><HomeFact fact={f} key={i} section={stance}/>)}</div><HomeGauge section={stance}/></div><div className="home-v2-metrics">{stanceFacts.map((fact,i)=><HomeFact fact={fact} key={i} section={stance}/>)}</div></div><HomeRows section={sections.stance}/></HomePanel>
 <HomeMetricTiles id="tiles" labels={['Portfolio','Session P&L','Year to date ≈','Realized','Trading record']} section={sections.tiles}/>
 <div className="home-v2-grid-two"><HomePanel id="movers" title="What moved your book" icon="pulse" section={sections.movers} limit={5}/><HomePanel id="stops" title="Stops" icon="shield" section={sections.stops}/></div>
 <div className="home-v2-grid-two"><HomePanel id="week" title="This week · earnings and events" icon="calendar" section={sections.week}/><HomePanel id="news" title="Read first · top stories for your book" icon="news" section={sections.news} limit={5} news/></div>
 <div className="home-v2-grid-three"><HomePanel id="accounts" title="Accounts" icon="wallet" section={sections.accounts}/><HomePanel id="setups" title="Setups · latest scan" icon="target" section={sections.setups} limit={5}/><HomePanel id="watch" title="Watchlist movers" icon="swap" section={sections.watch} limit={6}/></div>
 <div className="home-v2-grid-two"><HomePanel id="brief" title="CIO brief · stored history" icon="news" section={sections.brief}/><HomePanel id="pulse" title="System pulse" icon="heart" section={sections.pulse}/></div>
 </div>
}
