'use client';
import { ScreenTitle } from './screen-presentation';
import { useCallback, useMemo, useState } from 'react';
import { fmtDec, fmtHM, minutesSaisies } from '../../lib/engine-recon-data';
import { OperationForm } from './operation-form';
import { ErrorNotice, ReportPreview, message, today, useResource, type Report, type ScreenProps } from './shared';

interface ReconJour { nous_jour: number; nous_nuit: number; client_jour: number | null; client_nuit: number | null; retenu_jour: number | null; retenu_nuit: number | null; note: string }
interface ReconEngin { engin_id: string; engin: string; jours: Record<string, ReconJour>; total_nous_min: number; total_retenu_min: number }
export interface Harmonisation { id: string; source: string; cible: string; engin_source_id: string; engin_cible_id: string; poste: string; minutes: number; hm: string; motif: string; statut: string; propose_par: string | null; decide_par: string | null; commentaire_decision: string | null }
interface ReconData { ym: string; jours: string[]; statut: string | null; revision: number; verrouille: boolean; valide_par: string | null; valide_at: string | null; reouverte_par: string | null; motif_reouverture: string | null; roles_validation: string[]; engins: ReconEngin[]; harmonisations: Harmonisation[]; facture: { numero: string } | null }

const CHAMPS = ['client_jour', 'client_nuit', 'retenu_jour', 'retenu_nuit', 'note'] as const;

export function EngineReconciliation(props: ScreenProps) {
  const { bridge, state } = props;
  const [month, setMonth] = useState(today().slice(0, 7)), [success, setSuccess] = useState('');
  const load = useCallback(() => bridge.api<ReconData>(`/engins/reconciliation?societe_id=${state.companyId}&ym=${month}`), [bridge, state.companyId, month]);
  const result = useResource(load), data = result.data, ready = data && !result.busy && !result.error;
  const roles = state.companies.find(c => c.id === state.companyId)?.roles || [];
  return <><div className="audit-head"><ScreenTitle>Réconciliation mensuelle</ScreenTitle><button className="btn" disabled={result.busy} onClick={result.refresh}><i className="ti ti-refresh" aria-hidden="true" /> Actualiser</button></div>
    <p className="banner">Comparez jour par jour nos fiches avec les heures du service planning du locataire, saisissez les valeurs retenues de la séance, puis faites valider par le responsable : le mois devient définitif et toute saisie est verrouillée (réouverture réservée à la direction, motivée et tracée).</p>
    <label className="business-field">Mois à réconcilier<input className="form-input" type="month" required value={month} onChange={e => { if (e.target.value) { setMonth(e.target.value); setSuccess(''); } }} /></label>
    <ErrorNotice error={result.error} />{success && <p className="business-success" role="status">{success}</p>}{result.busy && <p role="status">Lecture des fiches et de la réconciliation…</p>}
    {ready && <ReconEditor key={`${month}:${data!.revision}:${data!.statut}`} {...props} data={data!} roles={roles} onSaved={label => { setSuccess(label); result.refresh(); }} />}</>;
}

function ReconEditor({ bridge, state, data, roles, onSaved }: ScreenProps & { data: ReconData; roles: string[]; onSaved: (label: string) => void }) {
  const [engin, setEngin] = useState(data.engins[0]?.engin_id || '');
  const initial = useMemo(() => {
    const out: Record<string, Record<string, Record<string, string>>> = {};
    for (const e of data.engins) { out[e.engin_id] = {}; for (const [date, d] of Object.entries(e.jours)) out[e.engin_id][date] = { client_jour: d.client_jour != null ? fmtHM(d.client_jour) : '', client_nuit: d.client_nuit != null ? fmtHM(d.client_nuit) : '', retenu_jour: d.retenu_jour != null ? fmtHM(d.retenu_jour) : '', retenu_nuit: d.retenu_nuit != null ? fmtHM(d.retenu_nuit) : '', note: d.note || '' }; }
    return out;
  }, [data]);
  const [edits, setEdits] = useState(initial), [busy, setBusy] = useState(false), [error, setError] = useState(''), [action, setAction] = useState<'valider' | 'rouvrir' | 'proposer' | ''>(''), [decide, setDecide] = useState<Harmonisation | null>(null), [preview, setPreview] = useState<Report | null>(null);
  const courant = data.engins.find(e => e.engin_id === engin), verrou = data.verrouille;
  const peutValider = roles.some(r => data.roles_validation.includes(r)), peutRouvrir = roles.some(r => ['PRESIDENT', 'DG', 'ADMIN_SYS'].includes(r));
  const champ = (date: string, cle: string) => edits[engin]?.[date]?.[cle] ?? '';
  const setChamp = (date: string, cle: string, valeur: string) => setEdits(old => ({ ...old, [engin]: { ...old[engin], [date]: { ...old[engin]?.[date], [cle]: valeur } } }));

  const effectif = (e: ReconEngin, date: string, poste: 'jour' | 'nuit') => {
    try { const v = minutesSaisies(edits[e.engin_id]?.[date]?.[`retenu_${poste}`] ?? '', ''); return v == null ? e.jours[date][`nous_${poste}`] : v; } catch { return e.jours[date][`nous_${poste}`]; }
  };
  const totalRetenu = (e: ReconEngin) => data.jours.reduce((s, date) => s + effectif(e, date, 'jour') + effectif(e, date, 'nuit'), 0);

  const payloadDonnees = () => {
    const donnees: Record<string, Record<string, Record<string, unknown>>> = {};
    for (const e of data.engins) for (const date of data.jours) {
      const t = edits[e.engin_id]?.[date]; if (!t) continue;
      const entree: Record<string, unknown> = {};
      for (const cle of CHAMPS) {
        if (cle === 'note') { const note = (t.note || '').trim(); if (note) entree.note = note; continue; }
        const v = minutesSaisies(t[cle] || '', `${e.engin}, ${date.slice(8)} ${cle.replace('_', ' ')}`);
        if (v != null) entree[cle] = v;
      }
      if (Object.keys(entree).length) (donnees[e.engin_id] ??= {})[date] = entree;
    }
    return donnees;
  };

  const enregistrer = async () => {
    if (busy) return; setBusy(true); setError('');
    try { const donnees = payloadDonnees(); await bridge.api(`/engins/reconciliation?societe_id=${state.companyId}`, { method: 'POST', body: { ym: data.ym, revision: data.revision, donnees } }); onSaved('Réconciliation enregistrée.'); }
    catch (cause) { setError(message(cause)); } finally { setBusy(false); }
  };

  const rapport = (): Report => {
    const e = courant!;
    return { title: `Réconciliation ${data.ym} — ${e.engin}`, subtitle: `Nos fiches vs planning du locataire · valeurs retenues de la séance · minutes arrondies à 5`, infos: [{ titre: 'Statut', lignes: [verrou ? `DÉFINITIF — validé par ${data.valide_par || ''}` : 'EN COURS (provisoire)'] }, { titre: 'Totaux', lignes: [`Nos fiches : ${fmtHM(e.total_nous_min)}`, `Retenu : ${fmtHM(totalRetenu(e))}`] }], columns: ['Date', 'Nous jour', 'Nous nuit', 'Client jour', 'Client nuit', 'Retenu jour', 'Retenu nuit', 'Écart', 'Note'], rows: data.jours.map(date => { const d = e.jours[date]; const ecart = effectif(e, date, 'jour') + effectif(e, date, 'nuit') - d.nous_jour - d.nous_nuit; return [date.slice(8) + '/' + date.slice(5, 7), fmtHM(d.nous_jour), fmtHM(d.nous_nuit), champ(date, 'client_jour') || '—', champ(date, 'client_nuit') || '—', fmtHM(effectif(e, date, 'jour')), fmtHM(effectif(e, date, 'nuit')), ecart ? fmtHM(ecart) : '=', champ(date, 'note')]; }), signatures: 'Pour ETS HORIZON | Pour le locataire (planning)' };
  };

  return <>
    {verrou ? <p className="business-success" role="status"><i className="ti ti-lock" aria-hidden="true" /> Mois validé {data.valide_par ? `par ${data.valide_par}` : ''} {data.valide_at ? `le ${data.valide_at.slice(0, 10)}` : ''} — saisies verrouillées.{data.facture && ` Facturé : ${data.facture.numero}.`}</p>
      : data.statut ? <p className="banner">Réconciliation en cours (révision {data.revision}).{data.motif_reouverture && ` Rouverte par ${data.reouverte_par || 'la direction'} : ${data.motif_reouverture}`}</p>
        : <p className="banner">Aucune réconciliation enregistrée pour ce mois : saisissez les valeurs du client et les valeurs retenues, puis enregistrez.</p>}
    <div className="business-toolbar">
      <label className="business-field">Engin<select className="form-select" value={engin} onChange={e => setEngin(e.target.value)}>{data.engins.map(e => <option key={e.engin_id} value={e.engin_id}>{e.engin}</option>)}</select></label>
      <div className="spacer" />
      <button className="btn" disabled={!courant} onClick={() => setPreview(rapport())}><i className="ti ti-printer" aria-hidden="true" /> Rapport d&rsquo;écarts</button>
      {!verrou && <button className="btn" disabled={busy || !courant} onClick={() => { setEdits(old => ({ ...old, [engin]: Object.fromEntries(data.jours.map(date => [date, { ...old[engin]?.[date], retenu_jour: '', retenu_nuit: '' }])) })); }}>Retenir nos valeurs</button>}
      {!verrou && <button className="btn" disabled={busy || !courant} onClick={() => { setEdits(old => ({ ...old, [engin]: Object.fromEntries(data.jours.map(date => { const t = old[engin]?.[date] || {}; return [date, { ...t, retenu_jour: t.client_jour || t.retenu_jour || '', retenu_nuit: t.client_nuit || t.retenu_nuit || '' }]; })) })); }}>Retenir valeurs client</button>}
      {!verrou && <button className="btn btn-primary" disabled={busy} onClick={enregistrer}>{busy ? 'Enregistrement…' : 'Enregistrer'}</button>}
      {!verrou && peutValider && <button className="btn btn-primary" disabled={busy || !data.statut} title={data.statut ? '' : 'Enregistrez d’abord la réconciliation.'} onClick={() => setAction('valider')}><i className="ti ti-lock" aria-hidden="true" /> Valider et verrouiller</button>}
      {verrou && peutRouvrir && !data.facture && <button className="btn" onClick={() => setAction('rouvrir')}>Rouvrir (direction)</button>}
    </div>
    <ErrorNotice error={error} />
    {courant && <div className="business-table recon-grid"><table><thead><tr><th>Date</th><th className="right">Nous — jour</th><th className="right">Nous — nuit</th><th>Client — jour</th><th>Client — nuit</th><th>Retenu — jour</th><th>Retenu — nuit</th><th className="right">Écart</th><th>Note</th></tr></thead><tbody>
      {data.jours.map(date => { const d = courant.jours[date]; const ecart = effectif(courant, date, 'jour') + effectif(courant, date, 'nuit') - d.nous_jour - d.nous_nuit; return <tr key={date}>
        <td>{date.slice(8)}/{date.slice(5, 7)}</td>
        <td className="right">{d.nous_jour ? <>{fmtHM(d.nous_jour)}<span className="recon-dec">{fmtDec(d.nous_jour)}</span></> : '—'}</td>
        <td className="right">{d.nous_nuit ? <>{fmtHM(d.nous_nuit)}<span className="recon-dec">{fmtDec(d.nous_nuit)}</span></> : '—'}</td>
        {(['client_jour', 'client_nuit', 'retenu_jour', 'retenu_nuit'] as const).map(cle => <td key={cle}><input className="form-input recon-input" disabled={verrou} placeholder={cle.startsWith('retenu') ? fmtHM(d[`nous_${cle.endsWith('jour') ? 'jour' : 'nuit'}`]) : '—'} value={champ(date, cle)} onChange={e => setChamp(date, cle, e.target.value)} /></td>)}
        <td className={`right ${ecart ? 'recon-ecart' : 'recon-egal'}`}>{ecart ? fmtHM(ecart) : '='}</td>
        <td><input className="form-input recon-note" disabled={verrou} value={champ(date, 'note')} onChange={e => setChamp(date, 'note', e.target.value)} maxLength={200} /></td>
      </tr>; })}
    </tbody><tfoot><tr><td><b>TOTAL</b></td><td className="right" colSpan={2}><b>{fmtHM(courant.total_nous_min)}</b> <span className="recon-dec">{fmtDec(courant.total_nous_min)}</span></td><td colSpan={2} /><td className="right" colSpan={2}><b>{fmtHM(totalRetenu(courant))}</b> <span className="recon-dec">{fmtDec(totalRetenu(courant))}</span></td><td colSpan={2} /></tr></tfoot></table>
      <p className="muted">Saisie libre : « 8h30 », « 8:30 » ou « 8,5 ». Laissez « Retenu » vide pour reprendre nos valeurs ; toute valeur est ramenée aux multiples de 5 minutes.</p></div>}
    <Harmonisations data={data} peutDecider={peutValider} onAsk={h => setDecide(h)} onPropose={() => setAction('proposer')} />
    {action === 'valider' && <OperationForm bridge={bridge} title={`Valider la réconciliation ${data.ym}`} note={`La validation fige les valeurs retenues et verrouille toutes les saisies du mois ${data.ym}. Seule la direction (PRESIDENT/DG) pourra rouvrir, avec un motif tracé. Pensez à enregistrer vos dernières modifications avant de valider.`} initial={{ confirmation: '' }} fields={[{ key: 'confirmation', label: 'Confirmation', required: true, options: [['', 'Vérifier avant de confirmer'], ['oui', 'Je valide et verrouille ce mois']] }]} submitLabel="Valider définitivement" onClose={() => setAction('')} save={async v => { if (v.confirmation !== 'oui') throw new Error('Confirmez la validation.'); await bridge.api(`/engins/reconciliation/valider?societe_id=${state.companyId}`, { method: 'POST', body: { ym: data.ym, revision: data.revision } }); setAction(''); onSaved(`Réconciliation ${data.ym} validée : mois verrouillé.`); }} />}
    {action === 'rouvrir' && <OperationForm bridge={bridge} title={`Rouvrir le mois ${data.ym}`} note="Réouverture de très haut niveau : le motif est obligatoire et inscrit au journal d'audit. Les saisies redeviennent possibles jusqu'à une nouvelle validation." initial={{ motif: '' }} fields={[{ key: 'motif', label: 'Motif de la réouverture', type: 'textarea', required: true }]} submitLabel="Rouvrir le mois" onClose={() => setAction('')} save={async v => { await bridge.api(`/engins/reconciliation/rouvrir?societe_id=${state.companyId}`, { method: 'POST', body: { ym: data.ym, motif: v.motif.trim() } }); setAction(''); onSaved(`Mois ${data.ym} rouvert.`); }} />}
    {action === 'proposer' && <OperationForm bridge={bridge} title={`Proposer un arrangement d'heures — ${data.ym}`} note="Transfert d'heures d'un engin vers un autre (ex. céder des heures d'une chargeuse à une autre), dans la limite des heures retenues de la source. L'arrangement ne s'applique qu'après approbation de la hiérarchie ; la facturation attend les décisions." initial={{ engin_source_id: '', engin_cible_id: '', poste: 'jour', heures: '', motif: '' }} fields={[{ key: 'engin_source_id', label: 'Engin qui cède', required: true, options: [['', 'Choisir…'], ...data.engins.map(e => [e.engin_id, e.engin] as [string, string])] }, { key: 'engin_cible_id', label: 'Engin qui reçoit', required: true, options: [['', 'Choisir…'], ...data.engins.map(e => [e.engin_id, e.engin] as [string, string])] }, { key: 'poste', label: 'Poste', options: [['jour', 'Jour'], ['nuit', 'Nuit']] }, { key: 'heures', label: 'Heures à transférer (ex. 2h30)', required: true }, { key: 'motif', label: 'Motif de l’arrangement', type: 'textarea', required: true }]} submitLabel="Proposer à la hiérarchie" onClose={() => setAction('')} save={async v => { const minutes = minutesSaisies(v.heures, 'Heures à transférer'); if (!minutes) throw new Error('Heures à transférer requises.'); await bridge.api(`/engins/harmonisations?societe_id=${state.companyId}`, { method: 'POST', body: { ym: data.ym, engin_source_id: v.engin_source_id, engin_cible_id: v.engin_cible_id, poste: v.poste, minutes, motif: v.motif.trim() } }); setAction(''); onSaved('Arrangement proposé : en attente de décision.'); }} />}
    {decide && <OperationForm bridge={bridge} title={`Décider : ${decide.source} → ${decide.cible} (${decide.hm})`} note={`Motif de la proposition : ${decide.motif}. L'approbation applique le transfert au RPE et à la facturation du mois.`} initial={{ decision: '', commentaire: '' }} fields={[{ key: 'decision', label: 'Décision', required: true, options: [['', 'Choisir…'], ['approuvee', 'Approuver le transfert'], ['rejetee', 'Rejeter la proposition']] }, { key: 'commentaire', label: 'Commentaire (facultatif)' }]} submitLabel="Enregistrer la décision" onClose={() => setDecide(null)} save={async v => { if (!v.decision) throw new Error('Choisissez la décision.'); await bridge.api(`/engins/harmonisations/${decide.id}/decider`, { method: 'POST', body: { decision: v.decision, commentaire: v.commentaire.trim() || null } }); setDecide(null); onSaved(v.decision === 'approuvee' ? 'Transfert approuvé.' : 'Proposition rejetée.'); }} />}
    {preview && <ReportPreview bridge={bridge} state={state} report={preview} onClose={() => setPreview(null)} />}
  </>;
}

function Harmonisations({ data, peutDecider, onAsk, onPropose }: { data: ReconData; peutDecider: boolean; onAsk: (h: Harmonisation) => void; onPropose: () => void }) {
  const libelle: Record<string, string> = { proposee: 'En attente de décision', approuvee: 'Approuvée', rejetee: 'Rejetée' };
  return <section aria-label="Harmonisations"><h3>Arrangements d&rsquo;heures entre engins</h3>
    {!data.facture && <button className="btn" onClick={onPropose}><i className="ti ti-arrows-exchange" aria-hidden="true" /> Proposer un arrangement</button>}
    {data.harmonisations.length ? <div className="business-table"><table><thead><tr><th>De</th><th>Vers</th><th>Poste</th><th className="right">Heures</th><th>Motif</th><th>Proposé par</th><th>Statut</th><th>Décision</th><th /></tr></thead><tbody>
      {data.harmonisations.map(h => <tr key={h.id}><td>{h.source}</td><td>{h.cible}</td><td>{h.poste}</td><td className="right">{h.hm}</td><td>{h.motif}</td><td>{h.propose_par || '—'}</td><td>{libelle[h.statut] || h.statut}</td><td>{h.decide_par ? `${h.decide_par}${h.commentaire_decision ? ` — ${h.commentaire_decision}` : ''}` : '—'}</td><td>{h.statut === 'proposee' && peutDecider && !data.facture && <button className="btn btn-sm" onClick={() => onAsk(h)}>Décider</button>}</td></tr>)}
    </tbody></table></div> : <p className="muted">Aucun arrangement proposé sur ce mois.</p>}
  </section>;
}
