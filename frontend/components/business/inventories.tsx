'use client';
import { ScreenTitle } from './screen-presentation';
import { useCallback, useRef, useState } from 'react';
import { accountingStatus, cost, countPayload, inventoryStatus, quantity, validCount, type Depot, type DepotState, type Inventory, type StockLine } from '../../lib/stock-forms';
import { DataTable } from './data-table';
import { Field } from './field';
import { Dialog, ErrorNotice, ReportPreview, message, number, today, useResource, type ScreenProps, type Report } from './shared';

export function Inventories({ bridge, state }: ScreenProps) {
  const [month, setMonth] = useState(today().slice(0, 7)), [depotId, setDepotId] = useState(''), [counting, setCounting] = useState(false), [detail, setDetail] = useState<Inventory | null>(null), [success, setSuccess] = useState('');
  const load = useCallback(async () => {
    const [depots, inventories] = await Promise.all([bridge.api<Depot[]>(`/stock/depots?societe_id=${state.companyId}&toutes=1`), bridge.api<Inventory[]>(`/stock/inventaires?societe_id=${state.companyId}${month ? `&mois=${month}` : ''}`)]);
    return { depots, inventories };
  }, [bridge, state.companyId, month]);
  const result = useResource(load), disabled = result.busy || !!result.error;
  const rows = (result.data?.inventories || []).filter(i => !depotId || i.depot_id === depotId);
  const validated = rows.filter(i => i.statut === 'valide'), lines = validated.flatMap(i => i.lignes);
  const saved = (i: Inventory) => { setCounting(false); setSuccess(`${i.numero} préparé : le stock reste inchangé jusqu’à validation.`); result.refresh(); };
  return <>
    <div className="audit-head"><div><ScreenTitle>Inventaires & écarts</ScreenTitle><p className="muted">Comptage physique par dépôt · montants en USD</p></div><div className="audit-actions"><button className="btn" disabled={result.busy} onClick={result.refresh}><i className="ti ti-refresh" aria-hidden="true" /> Actualiser</button><button className="btn btn-primary" disabled={disabled || !result.data?.depots.some(d => d.actif)} onClick={() => setCounting(true)}>Nouveau comptage</button></div></div>
    <p className="banner">1. Saisir le comptage → 2. Contrôler les écarts → 3. Validation comptable / DFI. Le stock est ajusté uniquement à la validation. Pour la cuisine, générez les consommations théoriques avant de compter.</p>
    <ErrorNotice error={result.error} />{success && <p role="status" className="business-success">{success}</p>}{result.busy && <p role="status">Chargement des inventaires…</p>}
    <div className="business-toolbar"><Field label="Mois de l’inventaire" type="month" value={month} onChange={setMonth} /><label>Dépôt<select className="form-select" value={depotId} onChange={e => setDepotId(e.target.value)}><option value="">Tous les dépôts</option>{result.data?.depots.map(d => <option value={d.id} key={d.id}>{d.libelle}{d.actif ? '' : ' (inactif)'}</option>)}</select></label></div>
    <div className="caisse-cards">{[['Comptages à valider', rows.filter(i => i.statut === 'brouillon').length], ['Inventaires validés', validated.length], ['Manquants validés (USD)', number(lines.reduce((s, l) => s + Math.max(0, -l.ecart_valeur), 0))], ['Excédents validés (USD)', number(lines.reduce((s, l) => s + Math.max(0, l.ecart_valeur), 0))]].map(([label, value]) => <article className="caisse-card" key={label}><p className="muted">{label}</p><strong>{disabled ? '—' : value}</strong></article>)}</div>
    {result.data && <DataTable bridge={bridge} state={state} title="Registre des inventaires" subtitle={month ? `Période ${month}` : '50 derniers inventaires'} disabled={disabled} columns={['Numéro', 'Date', 'Dépôt', 'État', 'Écart (USD)', 'Pièce comptable', 'État comptable']} rows={rows.map(i => [i.numero, i.date, i.depot, inventoryStatus[i.statut], i.ecart_valeur, i.ecriture || '—', accountingStatus(i.statut_comptable)])} actions={row => <button className="btn btn-sm" disabled={disabled} onClick={() => setDetail(rows.find(i => i.numero === row[0])!)}><i className="ti ti-eye" aria-hidden="true" /> Consulter</button>} />}
    {counting && result.data && <CountDialog bridge={bridge} state={state} depots={result.data.depots.filter(d => d.actif)} initialDepot={depotId} onClose={() => setCounting(false)} onSaved={saved} />}
    {detail && <InventoryDetail bridge={bridge} state={state} inventory={detail} onClose={() => setDetail(null)} onChanged={i => { setDetail(i); result.refresh(); }} />}
  </>;
}

export function CountDialog({ bridge, state, depots, initialDepot, onClose, onSaved }: ScreenProps & { depots: Depot[]; initialDepot?: string; onClose: () => void; onSaved: (i: Inventory) => void }) {
  const [depotId, setDepotId] = useState(depots.find(d => d.id === initialDepot)?.id || ''), [started, setStarted] = useState(!!depots.find(d => d.id === initialDepot)), [busy, setBusy] = useState(false);
  return <Dialog bridge={bridge} title="Préparer un comptage" onClose={onClose} busy={busy} footer={close => <><button className="btn" disabled={busy} onClick={close}>Fermer</button>{started && <button className="btn btn-primary" type="submit" form="count-form" disabled={busy}>{busy ? 'Enregistrement…' : 'Soumettre à validation'}</button>}</>}>
    {!started ? <div className="business-toolbar"><label>Dépôt à compter<select className="form-select" value={depotId} onChange={e => setDepotId(e.target.value)}><option value="">Choisir un dépôt…</option>{depots.map(d => <option key={d.id} value={d.id}>{d.libelle}</option>)}</select></label><button className="btn btn-primary" disabled={!depotId} onClick={() => setStarted(true)}>Commencer le comptage</button></div> : <CountLoader bridge={bridge} state={state} depotId={depotId} busy={busy} setBusy={setBusy} onSaved={onSaved} />}
  </Dialog>;
}
function CountLoader(props: ScreenProps & { depotId: string; busy: boolean; setBusy: (b: boolean) => void; onSaved: (i: Inventory) => void }) {
  const { bridge, state, depotId } = props;
  const load = useCallback(() => bridge.api<DepotState>(`/stock/depots-etat?societe_id=${state.companyId}&depot_id=${depotId}&inventaire=1`), [bridge, state.companyId, depotId]);
  const result = useResource(load);
  return <><ErrorNotice error={result.error} />{result.error && <button className="btn" onClick={result.refresh}>Réessayer</button>}{result.busy && <p role="status">Lecture du stock théorique…</p>}{result.data && !result.busy && !result.error && <CountForm {...props} initial={result.data} />}</>;
}
function CountForm({ bridge, state, depotId, initial, busy, setBusy, onSaved }: ScreenProps & { depotId: string; initial: DepotState; busy: boolean; setBusy: (b: boolean) => void; onSaved: (i: Inventory) => void }) {
  const [rows, setRows] = useState<StockLine[]>(initial.articles), [counts, setCounts] = useState<Record<string, string>>({}), [note, setNote] = useState(''), [error, setError] = useState(''), [extra, setExtra] = useState('');
  const pending = useRef(false);
  const available = initial.catalogue.filter(a => !rows.some(r => r.article_id === a.article_id));
  const done = rows.filter(r => validCount(counts[r.article_id] || '')).length;
  const deltas = rows.filter(r => validCount(counts[r.article_id] || '')).map(r => Math.round((Number(counts[r.article_id]) - r.qte) * r.cump * 100) / 100);
  return <form id="count-form" onSubmit={async e => {
    e.preventDefault(); if (pending.current) return; setError('');
    try { const lignes = countPayload(rows, counts); pending.current = true; setBusy(true); const saved = await bridge.api<Inventory>(`/stock/inventaires?societe_id=${state.companyId}`, { method: 'POST', body: { depot_id: depotId, note: note.trim(), lignes } }); onSaved(saved); }
    catch (cause) { setError(message(cause)); } finally { pending.current = false; setBusy(false); }
  }}><h3>{initial.depot.libelle}</h3><p className="banner">Saisissez les quantités réellement constatées. Une case vide n’est pas un zéro. L’enregistrement prépare un brouillon sans mouvement de stock.</p>
    <fieldset className="business-fieldset" disabled={busy}><div className="business-toolbar"><label>Ajouter un article absent du stock<select className="form-select" value={extra} onChange={e => setExtra(e.target.value)}><option value="">Choisir un article…</option>{available.map(a => <option key={a.article_id} value={a.article_id}>{a.code} — {a.designation}</option>)}</select></label><button className="btn" type="button" disabled={!extra} onClick={() => { const article = available.find(a => a.article_id === extra); if (article) setRows(old => [...old, article]); setExtra(''); }}>Ajouter au comptage</button></div>
    <div className="business-table"><table><thead><tr><th>Article</th><th>Théorique</th><th>Compté</th><th>Écart quantité</th><th>CUMP (USD)</th><th>Écart estimé (USD)</th></tr></thead><tbody>{rows.map(r => { const value = counts[r.article_id] ?? '', valid = validCount(value), delta = Number(value) - r.qte; return <tr key={r.article_id}><td><b>{r.code}</b><br />{r.designation}<br /><small>{r.unite}</small></td><td>{quantity(r.qte)}</td><td><input className="form-input stock-count-input" aria-label={`Quantité comptée ${r.code}`} type="number" required min="0" step="0.001" value={value} onChange={e => setCounts(old => ({ ...old, [r.article_id]: e.target.value }))} /></td><td>{valid ? quantity(delta) : 'À compter'}</td><td>{cost(r.cump)}</td><td>{valid ? number(delta * r.cump) : '—'}{valid && delta !== 0 && r.cump === 0 && <small> · Coût nul à vérifier</small>}</td></tr>; })}</tbody></table></div>
    {!rows.length && <p>Aucun stock théorique. Ajoutez les articles physiquement présents avant de soumettre.</p>}
    <p role="status">{done} / {rows.length} articles comptés · Manquants estimés : {number(deltas.reduce((s, v) => s + Math.max(0, -v), 0))} USD · Excédents estimés : {number(deltas.reduce((s, v) => s + Math.max(0, v), 0))} USD</p>
    <Field label="Note du comptage" value={note} onChange={setNote} maxLength={255} /><ErrorNotice error={error} /></fieldset>
  </form>;
}

export function inventoryReport(i: Inventory): Report {
  return { title: `Inventaire ${i.numero}`, subtitle: `${i.date} · ${i.depot} · ${inventoryStatus[i.statut]}`, columns: ['Code', 'Article', 'Unité', 'Théorique', 'Compté', 'Écart quantité', 'CUMP USD', 'Écart USD'], rows: i.lignes.map(l => [l.code, l.designation, l.unite, quantity(l.qte_theorique), quantity(l.qte_reelle), quantity(l.ecart_qte), cost(l.cump), l.ecart_valeur]), note: `${i.statut === 'brouillon' ? 'COMPTAGE NON VALIDÉ — STOCK INCHANGÉ.' : i.statut === 'annule' ? 'COMPTAGE ANNULÉ — AUCUN AJUSTEMENT.' : `Inventaire validé. Pièce : ${i.ecriture || 'aucune écriture nécessaire'} (${i.statut_comptable ? accountingStatus(i.statut_comptable) : 'sans objet'}).`} Théorique : ${number(i.valeur_theorique)} USD. Réel : ${number(i.valeur_reelle)} USD. Écart : ${number(i.ecart_valeur)} USD. ${i.note || ''} · Comptage : __________________ · Vérification / validation : __________________` };
}
export function InventoryDetail({ bridge, state, inventory: i, onClose, onChanged }: ScreenProps & { inventory: Inventory; onClose: () => void; onChanged: (i: Inventory) => void }) {
  const [decision, setDecision] = useState<'valider' | 'annuler' | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(''), [preview, setPreview] = useState(false);
  const pending = useRef(false), roles = state.companies.find(c => c.id === state.companyId)?.roles || [];
  const approver = roles.some(r => ['DFI', 'COMPTABLE'].includes(r)), draft = i.statut === 'brouillon';
  const report = inventoryReport(i);
  const decide = async () => { if (!decision || pending.current) return; pending.current = true; setBusy(true); setError(''); try { const saved = await bridge.api<Inventory>(`/stock/inventaires/${i.id}/decision`, { method: 'POST', body: { action: decision } }); setDecision(null); onChanged(saved); } catch (cause) { setError(message(cause)); } finally { pending.current = false; setBusy(false); } };
  return <><Dialog bridge={bridge} title={`Inventaire ${i.numero}`} busy={busy} onClose={onClose} footer={close => <><button className="btn" disabled={busy} onClick={close}>Fermer</button><button className="btn" disabled={busy} onClick={() => setPreview(true)}>Rapport PDF / Excel</button>{draft && !decision && <>{(approver || i.created_by === state.user?.id) && <button className="btn" onClick={() => setDecision('annuler')}>Annuler le comptage</button>}{approver && <button className="btn btn-primary" onClick={() => setDecision('valider')}>Valider les écarts</button>}</>}</>}>
    <p>{i.date} · {i.depot} · <strong>{inventoryStatus[i.statut]}</strong></p><p className="banner">{draft ? 'Comptage préparé : le stock et la comptabilité ne sont pas encore ajustés.' : i.statut === 'annule' ? 'Comptage annulé, sans ajustement de stock.' : `Stock ajusté. Pièce comptable : ${i.ecriture || 'aucune écriture nécessaire'}${i.statut_comptable ? ` · ${accountingStatus(i.statut_comptable)}` : ''}.`}</p>
    <div className="business-table"><table><thead><tr>{report.columns.map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>{report.rows.map((r, n) => <tr key={n}>{r.map((v, j) => <td key={j}>{typeof v === 'number' ? number(v) : v}</td>)}</tr>)}</tbody></table></div>
    <p>Valeur théorique : {number(i.valeur_theorique)} USD · Valeur réelle : {number(i.valeur_reelle)} USD · Écart : <b>{number(i.ecart_valeur)} USD</b></p>{i.note && <p>{i.note}</p>}{i.lignes.some(l => !l.cump && l.ecart_qte !== 0) && <p className="banner">Un écart a un coût nul : vérifiez la valorisation avant validation.</p>}
    {decision && <section className="business-confirm"><h3>{decision === 'valider' ? 'Confirmer la validation' : 'Confirmer l’annulation'}</h3><p>{decision === 'valider' ? `Les écarts de ${i.numero} ajusteront le stock et produiront l’écriture d’écart nécessaire. Si le stock a changé depuis le comptage, le serveur refusera l’opération.` : `Le comptage ${i.numero} sera annulé. Le stock restera inchangé.`}</p><div className="business-toolbar"><button className="btn" disabled={busy} onClick={() => setDecision(null)}>Revenir</button><button className="btn btn-primary" disabled={busy} onClick={decide}>{busy ? 'Traitement…' : decision === 'valider' ? 'Confirmer et ajuster le stock' : 'Confirmer l’annulation'}</button></div></section>}
    <ErrorNotice error={error} />
  </Dialog>{preview && <ReportPreview bridge={bridge} state={state} report={report} onClose={() => setPreview(false)} />}</>;
}
