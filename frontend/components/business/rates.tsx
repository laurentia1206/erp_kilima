'use client';
import { useEffect, useRef, useState } from 'react';
import { ErrorNotice, message, today, type ScreenProps } from './shared';

export function Rates({ bridge, state }: ScreenProps) {
  const [day, setDay] = useState(today), [rate, setRate] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [saved, setSaved] = useState('');
  const sending = useRef(false);
  const allowed = !state.user?.super_administrateur && state.companies.some(c => c.roles.some(r => ['DFI', 'PRESIDENT'].includes(r)));
  useEffect(() => { if (rate || busy) return bridge.holdNavigation(); }, [bridge, rate, busy]);
  return <section className="card business-rate"><div className="card-body"><h2>Taux de change du jour</h2><p className="banner">Le taux USD / CDF est commun aux sociétés. Enregistrer une date déjà renseignée remplace son taux, selon le fonctionnement existant.</p>
    <form onSubmit={async e => { e.preventDefault(); if (sending.current || !allowed) return; sending.current = true; setBusy(true); setError(''); setSaved(''); try { const value = Number(rate); if (!Number.isFinite(value) || value <= 0) throw new Error('Le taux doit être un nombre strictement positif.'); await bridge.api('/taux', { method: 'POST', body: { date_taux: day, devise: 'CDF', taux_usd: value } }); setSaved(`Taux enregistré pour le ${day} : 1 USD = ${rate} CDF.`); setRate(''); } catch (e) { setError(message(e)); } finally { sending.current = false; setBusy(false); } }}>
      <label className="business-field">Date<input className="form-input" type="date" value={day} required disabled={!allowed || busy} onChange={e => { setDay(e.target.value); setSaved(''); }} /></label>
      <label className="business-field">1 USD = (CDF)<input className="form-input" type="number" min="0.000001" step="any" placeholder="Ex. 2800" value={rate} required disabled={!allowed || busy} onChange={e => { setRate(e.target.value); setSaved(''); }} /></label>
      <ErrorNotice error={error} />{saved && <p className="business-success" role="status">{saved}</p>}
      <div className="business-toolbar"><button className="btn btn-primary" disabled={!allowed || busy}>{busy ? 'Enregistrement…' : 'Enregistrer le taux'}</button><button type="button" className="btn" disabled={busy || !rate} onClick={() => { setRate(''); setError(''); }}>Annuler la saisie</button></div>
      {!allowed && <p>La définition du taux est réservée au DFI et au Président.</p>}{rate && <p className="muted">Enregistrez ou annulez la saisie avant de changer d’écran ou de société.</p>}
    </form></div></section>;
}
