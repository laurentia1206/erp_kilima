'use client';
import { useCallback } from 'react';
import { DataTable } from './data-table';
import { ErrorNotice, number, useResource, type ScreenProps } from './shared';

interface StockLine { article_id: string; code: string; designation: string; unite: string; stock_qte: number; cump: number; stock_valeur: number }
interface Movement { id: string; date: string; article: string; sens: string; reference: string; qte: number; cout_unitaire: number; valeur: number }
export function Stock({ bridge, state }: ScreenProps) {
  const load = useCallback(async () => {
    const [stock, movements] = await Promise.all([bridge.api<{ lignes: StockLine[]; valeur_totale: number }>(`/commercial/stock?societe_id=${state.companyId}`), bridge.api<Movement[]>(`/commercial/stock/mouvements?societe_id=${state.companyId}`)]);
    return { stock, movements, at: new Date().toLocaleString('fr-FR', { timeZone: 'Africa/Lubumbashi' }) };
  }, [bridge, state.companyId]);
  const { data, busy, error, refresh } = useResource(load);
  return <>
    <div className="audit-head"><div><h2>État du stock</h2><p className="muted">Quantités et valorisation au coût moyen pondéré · société active</p></div><div className="audit-actions"><button className="btn" disabled={busy} onClick={refresh}>Actualiser</button></div></div>
    <ErrorNotice error={error ? `Le stock n’a pas pu être actualisé : ${error} Les valeurs déjà affichées peuvent être anciennes.` : ''} />
    {busy && <p role="status">Actualisation du stock…</p>}
    {data && <>
      <div className="kpi-row"><div className="kpi-card"><div className="kpi-label">Valeur totale du stock</div><div className="kpi-val">{number(data.stock.valeur_totale)} <small>USD</small></div><div className="kpi-sub">Tous les articles de la société</div></div><div className="kpi-card"><div className="kpi-label">Articles en stock</div><div className="kpi-val">{data.stock.lignes.filter(r => r.stock_qte > 0).length}</div><div className="kpi-sub">Références avec une quantité positive</div></div></div>
      <DataTable bridge={bridge} state={state} title="État du stock" subtitle={`Situation chargée le ${data.at} (Lubumbashi)`} disabled={busy || !!error} columns={['Code', 'Désignation', 'Unité', 'Quantité', 'CUMP (USD)', 'Valeur (USD)']} rows={data.stock.lignes.map(r => [r.code, r.designation, r.unite, r.stock_qte, r.cump, r.stock_valeur])} />
      <h3>Derniers mouvements</h3><p className="muted">Les 40 derniers mouvements enregistrés.</p>
      <DataTable bridge={bridge} state={state} title="Mouvements de stock" subtitle={`Situation chargée le ${data.at} (Lubumbashi) · 40 derniers mouvements au maximum`} disabled={busy || !!error} columns={['Date', 'Article', 'Sens', 'Référence', 'Quantité', 'Coût unitaire (USD)', 'Valeur (USD)']} rows={data.movements.slice(0, 40).map(m => [m.date, m.article, m.sens === 'entree' ? 'Entrée' : 'Sortie', m.reference, m.qte, m.cout_unitaire, m.valeur])} />
    </>}
  </>;
}
