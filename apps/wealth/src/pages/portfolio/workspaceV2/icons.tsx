// Compatibility names delegate to the single approved Wealth SVG definition.
import { WealthIcon } from '../../../components/WealthStatus'
import type { WealthIconName } from '../../../components/WealthStatus'
export type IconName='locked'|'unlocked'|'warning'|'news'|'calendar'|'shield'|'na'|'plug'
export function WorkspaceIcon({name}:{name:IconName}) {
 const shared:WealthIconName=name==='locked'?'closed':name==='unlocked'?'open':name
 return <WealthIcon name={shared} dataIcon={name} className="hv-icon"/>
}
