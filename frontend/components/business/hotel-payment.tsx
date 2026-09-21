'use client';
import { useCallback, useRef, useState } from 'react';
import { paymentAmount, paymentPieces, samePayments, type Folio } from '../../lib/hotel-data';
import { Dialog, ErrorNotice, message, number, useResource, type ScreenProps } from './shared';

export function HotelPayment({ bridge, state, stayId, onClose, onSaved }: ScreenProps & { stayId: string; onClose: () => void; onSaved: () => void }) {
  const [mode, setMode] = useState('espece'), [currency, setCurrency] = useState('USD'), [cashId, setCashId] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [review, setReview] = useState(false);
  const pending = useRef(false);
  const load = useCallback(async () => { const [folio, cash] = await Promise.all([bridge.api<Folio>(`/hotel/sejours/${stayId}/folio?societe_id=${state.companyId}`), bridge.api<{ id: string; libelle: string }[]>(`/caisses?societe_id=${state.companyId}`)]); return { folio, cash }; }, [bridge, state.companyId, stayId]);
  const result = useResource(load);
  const loadRate = useCallback(() => currency === 'CDF' ? bridge.api<{ taux_cdf: number | null; date: string }>(`/commercial/pos/contexte?societe_id=${state.companyId}`) : Promise.resolve(null), [bridge, state.companyId, currency]);
  const rate = useResource(loadRate);
  const pieces = result.data ? paymentPieces(result.data.folio) : [], total = pieces.reduce((sum, p) => sum + p.amount, 0), chosenCash = cashId || result.data?.cash[0]?.id || '';
  const disabled = busy || review || result.busy || !!result.error || !pieces.length || (mode === 'espece' && !chosenCash) || (currency === 'CDF' && (rate.busy || !!rate.error || !rate.data?.taux_cdf));
  const pay = async () => {
    if (pending.current || disabled) return; pending.current = true; setBusy(true); setError(''); let completed = 0;
    try {
      const current = await bridge.api<Folio>(`/hotel/sejours/${stayId}/folio?societe_id=${state.companyId}`);
      if (!samePayments(pieces, paymentPieces(current))) throw new Error('Les soldes ont changé depuis l’ouverture. Rouvrez l’encaissement pour vérifier les nouveaux montants.');
      let currentRate = rate.data?.taux_cdf;
      if (currency === 'CDF') { const fresh = await bridge.api<{ taux_cdf: number | null; date: string }>(`/commercial/pos/contexte?societe_id=${state.companyId}`); if (fresh.taux_cdf !== currentRate || fresh.date !== rate.data?.date) throw new Error('Le taux du jour a changé. Rouvrez l’encaissement pour vérifier les montants.'); currentRate = fresh.taux_cdf; }
      const payments = pieces.map(p => ({ ...p, amountToPay: paymentAmount(p.amount, currency, currentRate) }));
      for (const p of payments) { await bridge.api(`/ventes/factures/${p.id}/regler?societe_id=${state.companyId}`, { method: 'POST', body: { mode, devise: currency, montant: p.amountToPay, caisse_id: mode === 'espece' ? chosenCash : null } }); completed++; }
      onSaved();
    } catch (cause) { setReview(true); setError(`${message(cause)} ${completed} pièce(s) confirmée(s) pendant cette tentative. Fermez puis rouvrez cette fenêtre pour relire les soldes avant tout nouvel envoi ; une réponse interrompue peut correspondre à un paiement enregistré.`); }
    finally { pending.current = false; setBusy(false); }
  };
  return <Dialog bridge={bridge} title="Encaisser le séjour" onClose={onClose} busy={busy} footer={close => <><button className="btn" disabled={busy} onClick={close}>Encaisser plus tard / fermer</button><button className="btn btn-primary" disabled={disabled} onClick={pay}>{busy ? 'Encaissement…' : 'Confirmer l’encaissement'}</button></>}>
    <ErrorNotice error={result.error || rate.error || error} />{result.busy && <p role="status">Lecture des soldes à encaisser…</p>}{result.error && <button className="btn" onClick={result.refresh}>Réessayer la lecture</button>}
    <div className="business-table"><table><thead><tr><th>Pièce</th><th>Solde USD</th></tr></thead><tbody>{pieces.map(p => <tr key={p.id}><td>{p.label}</td><td>{number(p.amount)}</td></tr>)}</tbody></table></div><p><strong>Total à encaisser : {result.busy || result.error ? '—' : number(total)} USD</strong></p>
    {result.data && !pieces.length && <p className="business-success">Aucun solde restant à encaisser.</p>}
    <fieldset className="business-fieldset" disabled={busy || review}><div className="business-form-grid"><label className="business-field">Mode d’encaissement<select className="form-select" value={mode} onChange={e => setMode(e.target.value)}><option value="espece">Espèces</option><option value="mobile_money">Mobile Money</option><option value="banque">Banque</option></select></label><label className="business-field">Devise<select className="form-select" value={currency} onChange={e => setCurrency(e.target.value)}><option>USD</option><option>CDF</option></select></label>{mode === 'espece' && <label className="business-field">Caisse d’encaissement<select className="form-select" value={chosenCash} onChange={e => setCashId(e.target.value)}>{!result.data?.cash.length && <option value="">Aucune caisse accessible</option>}{result.data?.cash.map(c => <option value={c.id} key={c.id}>{c.libelle}</option>)}</select></label>}</div></fieldset>
    {currency === 'CDF' && (rate.data?.taux_cdf ? <p>Taux du {rate.data.date} : 1 USD = {number(rate.data.taux_cdf)} CDF · Total à recevoir : <b>{number(pieces.reduce((sum, p) => sum + paymentAmount(p.amount, currency, rate.data?.taux_cdf), 0))} CDF</b>.</p> : <p className="banner">Le taux USD/CDF du jour est requis. L’encaissement en CDF reste indisponible tant qu’il n’est pas chargé.</p>)}
    <p className="banner">Chaque facture est réglée séparément. En espèces, la caisse doit être ouverte. « Encaisser plus tard » conserve la créance sur le compte du client.</p>
  </Dialog>;
}
