// Functional SVG paths from the operator's approved markup. Text always supplies the meaning.
export type IconName='locked'|'unlocked'|'warning'|'news'|'calendar'|'shield'|'na'
export function WorkspaceIcon({name}:{name:IconName}) {
 const paths={
 locked:<><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></>,
 unlocked:<><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.6-1.7"/></>,
 warning:<><path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4"/><path d="M12 17v.5"/></>,
 news:<><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 9h6M7 13h10M7 16h10"/></>,
 calendar:<><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/></>,
 shield:<path d="M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6l-7-3z"/>,
 na:<><circle cx="12" cy="12" r="9"/><path d="M8 12h8"/></>
 }
 return <svg className="hv-icon" data-icon={name} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{paths[name]}</svg>
}
