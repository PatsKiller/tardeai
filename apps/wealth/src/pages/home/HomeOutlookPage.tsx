import type { Market, Overview } from './homeAdapter'
import type { RenderState } from '../../components/renderState'
import { HomeEvidenceButton, HomeGauge, HomePanel, HomeRows, HomeFact } from './HomeV2Parts'
import type { HomeV2Sections } from './HomeV2Parts'
export function HomeOutlookPage({sections={}}:{market?:RenderState<Market>;overview?:RenderState<Overview>;now?:number;sections?:HomeV2Sections}) {
 const disagreements=sections.disagreements,knownEmpty=disagreements?.available===true&&disagreements.rows?.length===0
 return <div className="home-v2" data-home-view="outlook"><section className="hero"><span className="home-v2-muted">Independent engines · dated evidence</span><HomeEvidenceButton sections={sections}/></section>
 <div className="home-v2-grid-two"><HomePanel id="temperature" title="Temperature · market risk" icon="thermometer" section={sections.temperature}><div className="home-v2-metrics">{sections.temperature?.metrics?.map((f,i)=><HomeFact key={i} fact={f} section={sections.temperature}/>)}</div><HomeGauge section={sections.temperature}/><HomeRows section={sections.temperature}/></HomePanel><HomePanel id="regime" title="Regime · separate engine" icon="compass" section={sections.regime}/></div>
 {!knownEmpty?<HomePanel id="disagreements" title="Where the engines disagree" icon="warning" section={disagreements} amber/>:null}
 <HomePanel id="sectors" title="Sectors" icon="pulse" section={sections.sectors}/>
 <HomePanel id="hedge" title="Hedge and rotation" icon="shield" section={sections.hedge}/>
 <div className="home-v2-grid-three"><HomePanel id="week" title="Week ahead" icon="calendar" section={sections.week}/><HomePanel id="futures" title="Futures and overseas" icon="clock" section={sections.futures}/><HomePanel id="headlines" title="Market headlines" icon="news" section={sections.headlines} limit={5} news/></div>
 <HomePanel id="marketMovers" title="Market movers · sampled scanner, not breadth" icon="swap" section={sections.marketMovers} limit={10}/>
 </div>
}
