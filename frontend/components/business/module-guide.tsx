import { moduleGuides } from '../../lib/module-guides';
import type { ScreenProps } from './shared';
export function ModuleGuide({bridge,state}: ScreenProps) {
  if(state.user?.super_administrateur) return null;
  const group=moduleGuides.find(g=>g.views.includes(state.view));
  if(!group)return null;
  const allowed=state.groups.flatMap(g=>g.items);
  return <details className="module-guide"><summary><span className="module-guide-category">{group.name}</span><span>{group.purpose}</span><span className="module-guide-toggle">Repères du module</span></summary><div className="module-guide-body"><p>{group.tip}</p><div>{group.links.filter(v=>v!==state.view&&allowed.some(i=>i.view===v)).map(v=><button type="button" className="btn btn-sm" key={v} onClick={()=>bridge.navigate(v)}>{allowed.find(i=>i.view===v)?.label} →</button>)}</div></div></details>;
}
