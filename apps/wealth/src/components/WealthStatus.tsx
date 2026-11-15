import { useId } from 'react'
import '../styles/status.css'
export type WealthIconName='closed'|'open'|'warning'|'na'|'plug'|'calendar'|'news'|'shield'|'check'|'ban'|'clock'|'thermometer'|'compass'|'pulse'|'heart'|'wallet'|'target'|'bell'|'swap'|'gear'
export type WealthTone='green'|'amber'|'red'|'grey'
export function WealthIcon({name,dataIcon=name,className=''}:{name:WealthIconName;dataIcon?:string;className?:string}) {
 const paths={
 closed:<><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></>,
 open:<><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.6-1.7"/></>,
 warning:<><path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4"/><path d="M12 17v.5"/></>,
 na:<><circle cx="12" cy="12" r="9"/><path d="M8 12h8"/></>,
 plug:<path d="M9 3v5M15 3v5M7 8h10v4a5 5 0 0 1-10 0V8zM12 17v4"/>,
 calendar:<><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/></>,
 news:<><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 9h6M7 13h10M7 16h10"/></>,
 check:<><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></>,
 ban:<><circle cx="12" cy="12" r="9"/><path d="m6 6 12 12"/></>,
 clock:<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
 thermometer:<><path d="M10 14V5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0z"/><path d="M12 11v5"/></>,
 compass:<><circle cx="12" cy="12" r="9"/><path d="m15 9-2 4-4 2 2-4 4-2z"/></>,
 pulse:<path d="M3 12h4l2-6 4 12 2-6h6"/>,
 heart:<path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10z"/>,
 wallet:<><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M16 12h2M3 10h18"/></>,
 target:<><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/></>,
 bell:<><path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4l2-2z"/><path d="M10 20h4"/></>,
 swap:<path d="M4 8h14l-3-3M20 16H6l3 3"/>,
 gear:<><circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/></>,
 shield:<path d="M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6l-7-3z"/>
 }
 return <svg className={className} data-icon={dataIcon} focusable="false" aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>
}
export function WealthStatus({icon,tone,label,detail,className='',summary,dataIcon}:{icon:WealthIconName;tone:WealthTone;label:string;detail:string;className?:string;summary?:string;dataIcon?:string}) {
 const id=useId()
 return <span className={'wealth-status '+className} data-tone={tone} tabIndex={0} aria-describedby={id}><WealthIcon name={icon} dataIcon={dataIcon}/>{label}{summary?<small>{summary}</small>:null}<span id={id} role="tooltip" className="wealth-tooltip">{label}: {detail}</span></span>
}
export function SignedValue({value,children}:{value:number|null;children:import('react').ReactNode}) {
 const tone=value===null||value===0?'grey':value>0?'green':'red'
 return <span className="wealth-sign" data-tone={tone}>{value!==null&&value!==0?<span aria-hidden="true">{value>0?'▲ +':'▼ '}</span>:null}{typeof children==='string'?children.replace('-', '−'):children}</span>
}
