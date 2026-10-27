'use client';
import { ScreenTitle } from './screen-presentation';
import { useCallback, useState } from 'react';
import { DataTable } from './data-table';
import { Dialog, ErrorNotice, number, useResource, type ScreenProps } from './shared';

interface PartySituation { id: string; code: string; nom: string; type: string; compte: string | null; debit_usd: number; credit_usd: number; solde_usd: number; factures_ouvertes: number; reste_du_usd: number }
interface LedgerAccount { compte: string; intitule: string; solde: number; mouvements: { date: string; piece: string; journal: string; libelle: string; debit: number; credit: number; solde: number; statut: string }[] }

export function PartiesSituation({ kind, ...props }: ScreenProps & { kind: 'fournisseur' | 'client' }) {
  const load = useCallback(() => props.bridge.api<PartySituation[]>(`/commercial/tiers-situation?societe_id=${props.state.companyId}&type=${kind}`), [props.bridge, props.state.companyId, kind]);
  const result = useResource(load), [detail, setDetail] = useState<PartySituation | null>(null);
  const supplier = kind === 'fournisseur', title = supplier ? 'Situation des fournisseurs' : 'Situation des clients';
  const owed = (p: PartySituation) => supplier ? p.credit_usd - p.debit_usd : p.debit_usd - p.credit_usd;
  return <><div className="audit-head"><ScreenTitle>{title}</ScreenTitle><button className="btn" disabled={result.busy} onClick={result.refresh}><i className="ti ti-refresh" aria-hidden="true" /> Actualiser</button></div>
    <p className="banner">Chaque fiche cumule ses mouvements comptables de classe 4 (compte collectif ou compte dédié de la fiche). Ouvrez le grand livre d&rsquo;un tiers pour l&rsquo;historique détaillé ; donnez-lui un compte dédié dans sa fiche (Administration ou création du tiers) pour isoler totalement son suivi.</p>
    <ErrorNotice error={result.error} />{result.busy && <p>Calcul des situations…</p>}
    {result.data && !result.busy && !result.error && <DataTable {...props} title={title} subtitle={`${supplier ? 'Dettes fournisseurs' : 'Créances clients'} — montants USD`} columns={['Code', 'Nom', 'Compte dédié', 'Débit', 'Crédit', supplier ? 'Dû au fournisseur' : 'Dû par le client', 'Factures ouvertes', 'Reste dû factures']} rows={result.data.map(p => [p.code, p.nom, p.compte || 'Collectif', number(p.debit_usd), number(p.credit_usd), number(owed(p)), p.factures_ouvertes, number(p.reste_du_usd)])} actions={(_, i) => <button className="btn" onClick={() => setDetail(result.data![i])}><i className="ti ti-book" aria-hidden="true" /> Grand livre</button>} />}
    {detail && <PartyLedger {...props} party={detail} onClose={() => setDetail(null)} />}</>;
}

function PartyLedger({ party, onClose, ...props }: ScreenProps & { party: PartySituation; onClose: () => void }) {
  const load = useCallback(() => props.bridge.api<LedgerAccount[]>(`/comptabilite/grand-livre?societe_id=${props.state.companyId}&compte=4&tiers_id=${party.id}`), [props.bridge, props.state.companyId, party.id]);
  const result = useResource(load);
  return <Dialog bridge={props.bridge} title={`Grand livre · ${party.nom}`} onClose={onClose}>
    <ErrorNotice error={result.error} />{result.busy && <p>Lecture du grand livre…</p>}
    {result.data && !result.busy && !result.error && (result.data.length ? result.data.map(c => <DataTable key={c.compte} {...props} title={`${c.compte} · ${c.intitule || 'Compte de tiers'}`} subtitle={`Solde ${number(c.solde)} USD`} columns={['Date', 'Pièce', 'Journal', 'Libellé', 'Débit', 'Crédit', 'Solde', 'Statut']} rows={c.mouvements.map(m => [m.date, m.piece, m.journal, m.libelle, number(m.debit), number(m.credit), number(m.solde), m.statut])} />) : <p>Aucun mouvement comptable pour ce tiers.</p>)}
  </Dialog>;
}
