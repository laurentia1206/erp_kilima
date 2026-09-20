'use client';
import { useCallback, useEffect, useState } from 'react';
import { Dialog, ErrorNotice, Pages, dateTime, message, today, useResource, type ScreenProps } from './shared';

const kinds: Record<string, string> = { donnees: 'Modification de données', metier: 'Opération métier', securite: 'Sécurité', consultation: 'Consultation / export', historique: 'Historique' };
interface Filters { portee: string; du: string; au: string; utilisateur_id: string; module: string; categorie: string; q: string; requete_id: string }
interface RecordRow { id: number; date: string; utilisateur: string; action: string; module: string; categorie: string; table: string; document: string; adresse_ip: string; requete_id: string; champs_modifies: string[]; methode: string; chemin: string; origine: string; avant?: unknown; apres?: unknown }
interface Journal { resultats: RecordRow[]; total: number; page: number; taille_page: number; borne: number; utilisateurs: { id: string; nom: string }[]; modules: string[] }
const initial = (global: boolean): Filters => { const before = new Date(); before.setDate(before.getDate() - 7); return { portee: global ? 'global' : 'societe', du: before.toLocaleDateString('fr-CA', { timeZone: 'Africa/Lubumbashi' }), au: today(), utilisateur_id: '', module: '', categorie: '', q: '', requete_id: '' }; };
const queryString = (company: string | null, filters: Filters, page: number, bound: number) => {
  const query = new URLSearchParams({ page: String(page) });
  if (company) query.set('societe_id', company);
  Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); });
  if (bound) query.set('borne', String(bound));
  return query;
};
export function Audit({ bridge, state }: ScreenProps) {
  const [draft, setDraft] = useState(() => initial(!!state.user?.super_administrateur));
  const [query, setQuery] = useState({ filters: draft, page: 1, bound: 0 });
  const [detail, setDetail] = useState<number | null>(null), [exporting, setExporting] = useState(false), [exportError, setExportError] = useState('');
  const load = useCallback(async () => {
    const params = queryString(state.companyId, query.filters, query.page, query.bound);
    const result = await bridge.api<Journal>('/audit/journal?' + params);
    if (result.borne) params.set('borne', String(result.borne));
    return { ...result, params: params.toString(), at: new Date().toLocaleTimeString('fr-FR') };
  }, [bridge, state.companyId, query]);
  const protectionLoad = useCallback(() => bridge.api<{ active: boolean; limite: string }>('/audit/protection?' + queryString(state.companyId, query.filters, 1, 0)), [bridge, state.companyId, query.filters]);
  const result = useResource(load), protection = useResource(protectionLoad);
  const { data, busy, error } = result;
  useEffect(() => { if (exporting) return bridge.holdNavigation(); }, [bridge, exporting]);
  const apply = (filters: Filters) => { setQuery({ filters: { ...filters }, page: 1, bound: 0 }); setExportError(''); };
  const reset = () => { const filters = initial(!!state.user?.super_administrateur); setDraft(filters); apply(filters); };
  const update = (key: keyof Filters, value: string) => setDraft(previous => ({ ...previous, [key]: value }));
  const download = async (format: 'pdf' | 'xlsx') => {
    if (!data || busy || exporting) return;
    setExporting(true); setExportError('');
    try { await bridge.download('/audit/export?' + data.params + '&format_export=' + format, 'journal-audit.' + format); } catch (e) { setExportError(message(e)); } finally { setExporting(false); }
  };
  const company = state.companies.find(c => c.id === state.companyId);
  return <>
    <div className="audit-head"><div><h2>{state.user?.super_administrateur ? 'Journal des utilisateurs' : 'Journal de traçabilité'}</h2><p className="muted">{state.user?.super_administrateur ? 'Comptes et habilitations' : company?.nom} · Heures de Lubumbashi · Données confidentielles</p></div><div className="audit-actions"><button className="btn" disabled={busy || exporting} onClick={() => { apply(query.filters); protection.refresh(); }}>Actualiser</button><button className="btn" disabled={busy || exporting || !data?.total || !!error} onClick={() => download('xlsx')}>Excel</button><button className="btn" disabled={busy || exporting || !data?.total || !!error} onClick={() => download('pdf')}>PDF</button></div></div>
    <div className={`audit-protection${protection.error || protection.data?.active === false ? ' audit-danger' : ''}`} role="status" title={protection.data?.limite}>{protection.busy ? 'Vérification de la protection du journal…' : protection.error ? 'Protection non vérifiée : ' + protection.error : protection.data?.active ? 'Protection en place · Modification et suppression des traces bloquées' : 'Protection incomplète — contactez votre informaticien.'}</div>
    <form className="card audit-filters" onSubmit={e => { e.preventDefault(); apply(draft); }}>
      <label>Périmètre<select className="form-input" value={draft.portee} onChange={e => { const filters = { ...draft, portee: e.target.value, utilisateur_id: '', module: '' }; setDraft(filters); apply(filters); }}>{state.user?.super_administrateur ? <option value="global">Utilisateurs et habilitations</option> : <><option value="societe">Société active</option><option value="partage">Clients / fournisseurs partagés</option>{state.companies.some(c => c.roles.includes('ADMIN_SYS')) && <option value="global">Sécurité et réglages globaux</option>}</>}</select></label>
      <label>Du<input className="form-input" type="date" value={draft.du} onChange={e => update('du', e.target.value)} /></label><label>Au<input className="form-input" type="date" value={draft.au} onChange={e => update('au', e.target.value)} /></label>
      <label>Utilisateur<select className="form-input" value={draft.utilisateur_id} onChange={e => update('utilisateur_id', e.target.value)}><option value="">Tous les utilisateurs</option>{data?.utilisateurs.map(u => <option key={u.id} value={u.id}>{u.nom}</option>)}</select></label>
      <label>Module<select className="form-input" value={draft.module} onChange={e => update('module', e.target.value)}><option value="">Tous les modules</option>{data?.modules.map(m => <option key={m} value={m}>{m}</option>)}</select></label>
      <label>Type<select className="form-input" value={draft.categorie} onChange={e => update('categorie', e.target.value)}><option value="">Tous les événements</option>{Object.entries(kinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>Action ou référence<input className="form-input" maxLength={100} value={draft.q} onChange={e => update('q', e.target.value)} placeholder="Article, validation, référence…" /></label>
      <label>Identifiant de requête<input className="form-input" maxLength={36} value={draft.requete_id} onChange={e => update('requete_id', e.target.value)} placeholder="Regrouper une opération" /></label>
      <button className="btn btn-primary" disabled={exporting}>Appliquer les filtres</button><button className="btn" type="button" disabled={exporting} onClick={reset}>Réinitialiser</button>
    </form>
    <p className="muted audit-note">Une opération peut produire plusieurs traces liées par un identifiant de requête. Les champs RH sensibles et les secrets sont masqués. Les exports utilisent les filtres appliqués, même si vous préparez une autre recherche.</p>
    <ErrorNotice error={error || exportError} />
    {busy && <p role="status">Chargement du journal…</p>}{exporting && <p role="status">Préparation du document…</p>}
    {data && !busy && !error && <><div className="audit-count"><b>{data.total} événements</b><span>Situation chargée à {data.at}</span></div><div className="card audit-table"><table><thead><tr><th>Date / heure</th><th>Utilisateur</th><th>Action</th><th>Document / module</th><th>Type</th><th>Détail</th></tr></thead><tbody>{data.resultats.map(r => <tr key={r.id}><td>{dateTime(r.date)}<small>N° {r.id}</small></td><td>{r.utilisateur}<small>{r.adresse_ip || 'IP non disponible'}</small></td><td><b>{r.action}</b><small>{r.champs_modifies?.slice(0, 5).join(', ')}{r.champs_modifies?.length > 5 ? '…' : ''}</small></td><td>{r.table}<small>{r.document || 'Sans référence'} · {r.module}</small></td><td><span className="audit-type">{kinds[r.categorie] || r.categorie}</span></td><td><button className="btn btn-sm" onClick={() => setDetail(r.id)}>Examiner</button></td></tr>)}{!data.resultats.length && <tr><td colSpan={6} className="audit-empty">Aucun événement pour ces filtres.</td></tr>}</tbody></table></div><Pages page={data.page} pages={Math.max(1, Math.ceil(data.total / data.taille_page))} disabled={exporting} change={page => setQuery(previous => ({ ...previous, page, bound: data.borne }))} />
      {detail !== null && <AuditDetail bridge={bridge} state={state} id={detail} params={data.params} onClose={() => setDetail(null)} onRelated={requete_id => { const filters = { ...query.filters, requete_id }; setDraft(filters); apply(filters); }} />}
    </>}
  </>;
}
function AuditDetail({ bridge, id, params, onClose, onRelated }: ScreenProps & { id: number; params: string; onClose: () => void; onRelated: (id: string) => void }) {
  const load = useCallback(() => bridge.api<RecordRow>(`/audit/journal/${id}?${params}`), [bridge, id, params]);
  const { data: row, busy, error } = useResource(load);
  const object = (v: unknown): Record<string, unknown> => v && typeof v === 'object' ? v as Record<string, unknown> : { valeur: v };
  const before = object(row?.avant), after = object(row?.apres);
  const keys = row?.champs_modifies?.length ? row.champs_modifies : Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));
  const value = (v: unknown) => v === undefined ? 'Non enregistré' : v === null ? 'Vide' : typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v);
  return <Dialog bridge={bridge} title={`Trace n° ${id}${row ? ' · ' + row.action : ''}`} onClose={onClose} footer={close => <><button className="btn" onClick={close}>Fermer</button>{row?.requete_id && <button className="btn btn-primary" onClick={() => { close(); onRelated(row.requete_id); }}>Voir les traces liées</button>}</>}>
    <ErrorNotice error={error} />{busy && <p role="status">Chargement de la trace…</p>}{row && <><p><b>{row.utilisateur}</b> · {dateTime(row.date)} · {kinds[row.categorie] || row.categorie}</p><p>{row.table} · {row.document || 'Sans référence'}</p><p className="muted">IP : {row.adresse_ip || 'Non disponible'} · {row.methode} {row.chemin}</p><div className="audit-diff"><table><thead><tr><th>Champ</th><th>Avant</th><th>Après</th></tr></thead><tbody>{keys.map(key => <tr key={key}><th>{key}</th><td><pre>{value(before[key])}</pre></td><td><pre>{value(after[key])}</pre></td></tr>)}</tbody></table></div><p className="muted">Requête : {row.requete_id || 'Non disponible sur cette trace'} · Origine : {row.origine}</p></>}
  </Dialog>;
}
