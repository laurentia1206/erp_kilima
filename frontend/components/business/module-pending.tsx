'use client';
import { useCallback } from 'react';
import { useResource, type ScreenProps } from './shared';

interface PilotTask { id: string; type: string; module: string; action: string; reference: string; vue: string; niveau: string; echeance_depassee: boolean }
interface PilotFeed { taches?: PilotTask[] }

/** Bannière commune : opérations du module courant qui attendent une action
 *  de l'utilisateur (même source que le Suivi des tâches). */
export function ModulePendingBanner(props: ScreenProps) {
  const { bridge, state } = props;
  const load = useCallback(() => bridge.api<PilotFeed>(`/pilotage/taches?societe_id=${state.companyId}`), [bridge, state.companyId]);
  const result = useResource(load);
  if (state.view === 'pilotage' || state.view === 'accueil') return null;
  const group = state.groups.find(g => g.items.some(i => i.view === state.view));
  if (!group || !result.data?.taches) return null;
  const views = new Set(group.items.map(i => i.view));
  const pending = result.data.taches.filter(t => views.has(t.vue));
  if (!pending.length) return null;
  const parType = new Map<string, { action: string; vue: string; n: number; retard: boolean }>();
  for (const t of pending) { const e = parType.get(t.type) || { action: t.action, vue: t.vue, n: 0, retard: false }; e.n += 1; e.retard = e.retard || t.echeance_depassee || t.niveau === 'escalade'; parType.set(t.type, e); }
  return <p className="banner module-pending" role="status"><i className="ti ti-bell-ringing" aria-hidden="true" /> <strong>{pending.length} opération{pending.length > 1 ? 's' : ''} de ce module attend{pending.length > 1 ? 'ent' : ''} votre action :</strong> {[...parType.values()].map((e, i) => <span key={i}>{i > 0 && ' · '}{e.n > 1 ? `${e.n} × ` : ''}{e.action}{e.retard ? ' ⚠' : ''}{e.vue !== state.view && <> (<a href="#" onClick={ev => { ev.preventDefault(); bridge.navigate(e.vue); }}>ouvrir</a>)</>}</span>)} — <a href="#" onClick={ev => { ev.preventDefault(); bridge.navigate('pilotage'); }}>tout voir dans le Suivi des tâches</a></p>;
}
