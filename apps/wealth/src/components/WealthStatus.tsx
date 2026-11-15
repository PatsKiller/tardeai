import { useId } from 'react'
import '../styles/status.css'
export type WealthIconName='closed'|'open'|'warning'|'na'|'plug'|'calendar'|'news'|'shield'
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
