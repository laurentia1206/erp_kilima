'use client';
import { useEffect, useState } from 'react';
import type { Bridge, Snapshot } from '../lib/runtime';
import { ReportPreview } from './business/shared';

interface Dashboard { requisitions_soumises: number; ordres_a_valider: number; avances_en_cours: number; avances_en_retard: number; avances_montant_usd: number; beneficiaires_bloques: number }
export function Home({ state, bridge }: { state: Snapshot; bridge: Bridge }) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [preview, setPreview] = useState(false);
  const allowed = new Set(state.groups.flatMap(group => group.items.map(item => item.view)));
  useEffect(() => {
    let alive = true;
    setError('');
    bridge.api<Dashboard>(`/dashboard?societe_id=${state.companyId}`).then(result => { if (alive) setData(result); })
      .catch(cause => { if (alive) setError(cause.message || 'Indicateurs indisponibles.'); });
    return () => { alive = false; };
  }, [bridge, state.companyId, retry]);
  const company = state.companies.find(item => item.id === state.companyId);
  const metrics = data ? [
    { label: 'Réquisitions soumises', count: data.requisitions_soumises, hint: 'En attente de validation', view: 'requisitions', tone: 'amber' },
    { label: 'Ordres à valider', count: data.ordres_a_valider, hint: 'Autorisations de sortie de fonds', view: 'ordres', tone: 'blue' },
    { label: 'Avances en cours', count: data.avances_en_cours, hint: new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(data.avances_montant_usd), view: 'avances', tone: 'green' },
    { label: 'Avances en retard', count: data.avances_en_retard, hint: 'À examiner et à justifier', view: 'avances', tone: data.avances_en_retard ? 'red' : 'green' },
    { label: 'Bénéficiaires bloqués', count: data.beneficiaires_bloques, hint: 'Blocage automatique — avances non justifiées', view: 'avances', tone: data.beneficiaires_bloques ? 'red' : 'green' },
  ] : [];
  const flows = [
    { title: 'De la demande au paiement', sub: 'Demander, autoriser, décaisser et justifier.', steps: [['requisitions', 'Réquisitions'], ['ordres', 'Ordres de dépense'], ['avances', 'Avances']] },
    { title: 'Du devis à l’encaissement', sub: 'Suivre vos ventes et les règlements clients.', steps: [['devis', 'Devis & commandes'], ['ventes', 'Factures de vente'], ['caisse', 'Caisse']] },
    { title: 'Des achats aux stocks', sub: 'Commander, réceptionner et suivre les quantités.', steps: [['commandes', 'Commandes'], ['receptions', 'Réceptions'], ['stock', 'Stock']] },
  ].filter(flow => flow.steps.some(([view]) => allowed.has(view)));
  return <>
    <section className="workspace-hero"><div><div className="workspace-eyebrow">VOTRE ESPACE DE TRAVAIL</div><h2>Bonjour, {state.user?.prenom || state.user?.nom}.</h2><p>Gardez le fil de vos opérations chez <strong>{company?.nom || 'Kilima Holdings'}</strong>.</p></div>
      {allowed.has('nouvelle-req') && <button className="btn btn-primary workspace-create" onClick={() => bridge.navigate('nouvelle-req')}>Nouvelle réquisition ↗</button>}</section>
    <div className="workspace-section-heading"><h3>Vos priorités</h3><span className="workspace-heading-tools"><button className="btn btn-sm" onClick={() => setRetry(value => value + 1)}><i className="ti ti-refresh" aria-hidden="true" /> Actualiser</button><button className="btn btn-sm" disabled={!data} onClick={() => setPreview(true)}><i className="ti ti-file-download" aria-hidden="true" /> Rapport PDF / Excel</button></span></div>
    <div className="workspace-metrics" aria-live="polite">{error ? <div className="workspace-metric metric-unavailable"><p>{error}</p><button className="btn btn-sm" onClick={() => setRetry(value => value + 1)}>Réessayer</button></div> : !data ? <div className="workspace-metric muted">Chargement des indicateurs…</div> : metrics.map(metric => <button key={metric.label} className={`workspace-metric ${metric.tone}`} disabled={!allowed.has(metric.view)} onClick={() => bridge.navigate(metric.view)}><span className="metric-label">{metric.label}<span aria-hidden="true">↗</span></span><strong>{metric.count ?? '—'}</strong><span className="metric-hint">{metric.hint}</span></button>)}</div>
    <div className="workspace-section-heading"><h3>Suivez vos circuits de gestion</h3><span>Les étapes liées, au même endroit</span></div>
    <section className="workspace-flows">{flows.map((flow, index) => <article className="workspace-flow" key={flow.title}><span className="flow-number">0{index + 1}</span><h4>{flow.title}</h4><p>{flow.sub}</p><div>{flow.steps.filter(([view]) => allowed.has(view)).map(([view, label]) => <button className="workspace-link" key={view} onClick={() => bridge.navigate(view)}>{label}<span aria-hidden="true">↗</span></button>)}</div></article>)}</section>
    <div className="workspace-section-heading"><h3>Tous vos modules</h3><span>{state.groups.length} espaces accessibles à votre compte</span></div>
    {state.groups.filter(group => group.name !== 'Pilotage').map((group, gi) => <section className="tile-section" key={group.name}>
      <h4 className="tile-section-title">{group.name}</h4>
      <div className="tile-grid">{group.items.map((item, ii) => <button key={item.view} className={`tile tile-c${(gi * 3 + ii) % 8}${ii === 0 && group.items.length > 2 ? ' tile-lg' : ''}`} onClick={() => bridge.navigate(item.view, group.name)}><i className={`ti ${item.icon}`} aria-hidden="true" /><span className="tile-label">{item.label}</span><span className="tile-arrow" aria-hidden="true">→</span></button>)}</div>
    </section>)}
    {preview && data && <ReportPreview bridge={bridge} state={state} onClose={() => setPreview(false)} report={{ title: 'Suivi des opérations', subtitle: 'Situation de la société active au moment de la consultation', columns: ['Indicateur', 'Nombre', 'Précision'], rows: metrics.map(metric => [metric.label, metric.count, metric.hint]), note: 'Ces indicateurs de suivi ne remplacent pas les états comptables.' }} />}
  </>;
}
