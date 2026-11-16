'use client';
import { ScreenTitle } from './screen-presentation';
import { useCallback, useState } from 'react';
import { DataTable } from './data-table';
import { ErrorNotice, number, today, useResource, type ScreenProps } from './shared';

interface TargetRow { engin: string; cumul_hm: string; cumul_dec: number; target_dec: number; ecart_dec: number; ecart_jours: number; pct: number; cumul_prec_dec: number; ecart_vs_prec_dec: number }
interface TargetData { ym: string; mois_precedent: string; nb_jours: number; jusqu_au_jour: number; target_jour_dec: number; target_cumule_dec: number; rows: TargetRow[]; parc: { cumul_dec: number; target_dec: number; ecart_dec: number; ecart_jours: number } }
interface DispoRow { engin: string; cells: string[]; dispo: number; panne: number; entretien: number; s: number; demi: number; ns: number; heures_hm: string; taux_dispo: number; taux_sollicitation: number }
interface DispoData { ym: string; jours: string[]; rows: DispoRow[] }
interface EvolutionMois { ym: string; total_dec: number; supp_dec: number; reconciliation: string | null; facture: { numero: string; total_ttc: number } | null }

const CELLULE: Record<string, [string, string]> = { '1': ['1', 'Sollicité, deux postes'], '05': ['½', 'Sollicité, un poste'], ns: ['NS', 'Disponible non sollicité'], p: ['P', 'En panne'], e: ['E', 'En entretien'] };

export function EngineAnalytics(props: ScreenProps) {
  const { bridge, state } = props;
  const [month, setMonth] = useState(today().slice(0, 7)), [tab, setTab] = useState('target');
  const load = useCallback(async () => {
    const [target, dispo, evolution] = await Promise.all([
      bridge.api<TargetData>(`/engins/rapport-technique?societe_id=${state.companyId}&ym=${month}`),
      bridge.api<DispoData>(`/engins/disponibilite?societe_id=${state.companyId}&ym=${month}`),
      bridge.api<{ serie: EvolutionMois[] }>(`/engins/evolution?societe_id=${state.companyId}`)]);
    return { target, dispo, evolution: evolution.serie };
  }, [bridge, state.companyId, month]);
  const result = useResource(load), data = result.data, ready = data && !result.busy && !result.error;
  const signe = (v: number) => `${v >= 0 ? '+' : ''}${number(v)}`;
  return <><div className="audit-head"><ScreenTitle>Rapports d&rsquo;exploitation des engins</ScreenTitle><button className="btn" disabled={result.busy} onClick={result.refresh}><i className="ti ti-refresh" aria-hidden="true" /> Actualiser</button></div>
    <label className="business-field">Mois analysé<input className="form-input" type="month" required value={month} onChange={e => { if (e.target.value) setMonth(e.target.value); }} /></label>
    <div className="business-toolbar" role="group" aria-label="Rapports">{[['target', 'Rapport technique (target)'], ['dispo', 'Disponibilité & sollicitation'], ['evolution', 'Évolution 12 mois']].map(([key, label]) => <button key={key} className={`btn ${tab === key ? 'btn-primary' : ''}`} aria-pressed={tab === key} onClick={() => setTab(key)}>{label}</button>)}</div>
    <ErrorNotice error={result.error} />{result.busy && <p role="status">Calcul des rapports…</p>}
    {ready && tab === 'target' && <>
      <p className="banner">Target journalier minimum : <b>{number(data!.target.target_jour_dec)} h</b> par engin (forfait réparti sur {data!.target.nb_jours} jours) · situation au jour {data!.target.jusqu_au_jour} · target cumulé : <b>{number(data!.target.target_cumule_dec)} h</b>. Comparaison avec {data!.target.mois_precedent} à la même période, sur les valeurs retenues de la réconciliation.</p>
      <div className="kpi-row">{[['Cumul parc (h)', number(data!.target.parc.cumul_dec)], ['Target parc (h)', number(data!.target.parc.target_dec)], ['Écart parc (h)', signe(data!.target.parc.ecart_dec)], ['Écart en jours-engin', signe(data!.target.parc.ecart_jours)]].map(([label, value]) => <article className="kpi-card" key={label}><div className="kpi-label">{label}</div><div className="kpi-val">{value}</div></article>)}</div>
      <DataTable {...props} key={`t${month}`} title={`Rapport technique ${month}`} subtitle={`Target ${number(data!.target.target_jour_dec)} h/jour · cumul au jour ${data!.target.jusqu_au_jour} · heures décimales`} columns={['Engin', 'Cumul h:min', 'Cumul (nombre)', 'Target cumulé', 'Écart (h)', 'Écart (jours)', '% du target', `Cumul ${data!.target.mois_precedent}`, 'Écart vs mois préc.']} rows={data!.target.rows.map(r => [r.engin, r.cumul_hm, r.cumul_dec, r.target_dec, signe(r.ecart_dec), signe(r.ecart_jours), `${number(r.pct)} %`, r.cumul_prec_dec, signe(r.ecart_vs_prec_dec)])} reportNote={`Target journalier = forfait mensuel ÷ ${data!.target.nb_jours} jours. Écart en jours = retard ou avance exprimé en jours de target. Données : valeurs retenues après réconciliation lorsque disponibles.`} /></>}
    {ready && tab === 'dispo' && <>
      <p className="banner">{Object.entries(CELLULE).map(([code, [txt, label]]) => <span key={code} className="dispo-legende"><span className={`dcell d-${code}`}>{txt}</span> {label}&nbsp;&nbsp;</span>)}</p>
      <div className="business-table dispo-grid"><table><thead><tr><th>Engin</th>{data!.dispo.jours.map(j => <th key={j} className="right">{parseInt(j.slice(8), 10)}</th>)}</tr></thead><tbody>
        {data!.dispo.rows.map(r => <tr key={r.engin}><td>{r.engin}</td>{r.cells.map((c, i) => <td key={i} className={`dcell d-${c}`} title={`${data!.dispo.jours[i]} — ${CELLULE[c]?.[1] || c}`}>{CELLULE[c]?.[0] || c}</td>)}</tr>)}
      </tbody></table></div>
      <DataTable {...props} key={`d${month}`} title={`Disponibilité & sollicitation ${month}`} subtitle="Jours écoulés du mois · sollicitation déduite des fiches, pannes et entretiens des interventions de maintenance" columns={['Engin', 'Disponibles', 'Pannes', 'Entretiens', 'Sollicité (2 postes)', 'Sollicité (1 poste)', 'Non sollicité', 'Heures prestées', 'Taux dispo', 'Taux sollicitation']} rows={data!.dispo.rows.map(r => [r.engin, r.dispo, r.panne || '—', r.entretien || '—', r.s || '—', r.demi || '—', r.ns || '—', r.heures_hm, `${r.taux_dispo} %`, `${r.taux_sollicitation} %`])} reportNote="Taux de sollicitation = moyenne des valeurs journalières (1 = deux postes, ½ = un poste) sur les jours disponibles écoulés. Un engin immobilisé par une intervention de maintenance est compté en panne (P) ou en entretien (E)." /></>}
    {ready && tab === 'evolution' && <DataTable {...props} key="evo" title="Évolution des prestations — 12 derniers mois" subtitle="Heures retenues, heures supplémentaires, réconciliation et facturation" columns={['Mois', 'Heures prestées', 'Heures supp.', 'Réconciliation', 'Facture', 'Montant TTC USD']} rows={data!.evolution.map(m => [m.ym, m.total_dec, m.supp_dec, m.reconciliation === 'validee' ? 'Validée' : m.reconciliation === 'en_cours' ? 'En cours' : '—', m.facture?.numero || '—', m.facture ? m.facture.total_ttc : '—'])} reportNote="Heures en valeur décimale (base de facturation). Les mois sans réconciliation validée restent provisoires." />}
  </>;
}
