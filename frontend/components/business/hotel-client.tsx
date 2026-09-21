'use client';
import { useRef, useState } from 'react';
import { clientLabel, type HotelClient } from '../../lib/hotel-data';
import { Dialog, ErrorNotice, message, normalize, type ScreenProps } from './shared';
import { Field } from './field';

export function HotelClientPicker({ bridge, state, clients, onClose, onSelected }: ScreenProps & { clients: HotelClient[]; onClose: () => void; onSelected: (c: HotelClient) => void }) {
  const [search, setSearch] = useState(''), [creating, setCreating] = useState(false), [code, setCode] = useState(''), [name, setName] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [confirmable, setConfirmable] = useState(false), [confirmed, setConfirmed] = useState(false);
  const pending = useRef(false);
  const matches = clients.filter(c => creating ? (code && normalize(c.code) === normalize(code)) || (name.length >= 2 && normalize(c.nom).includes(normalize(name))) : normalize(clientLabel(c)).includes(normalize(search)));
  const resetConfirmation = () => { setConfirmable(false); setConfirmed(false); };
  return <Dialog bridge={bridge} title={creating ? 'Créer une fiche client' : 'Rechercher un client'} busy={busy} onClose={onClose} footer={close => <><button className="btn" disabled={busy} onClick={close}><i className="ti ti-x" aria-hidden="true" /> Annuler</button>{creating ? <button className="btn btn-primary" type="submit" form="hotel-client-form" disabled={busy}>Créer et sélectionner</button> : <button className="btn btn-primary" onClick={() => setCreating(true)}>Créer une fiche client</button>}</>}>
    <p className="catalogue-scope">{state.companies.find(c => c.id === state.companyId)?.nom} · Les fiches partagées sont identifiées dans la liste. Une création depuis la réception est propre à cette société.</p>
    <form id="hotel-client-form" onSubmit={async e => { e.preventDefault(); if (!creating || pending.current) return; setError(''); if (!code.trim() || name.trim().length < 2) { setError('Code et nom complet requis.'); return; } pending.current = true; setBusy(true); try { const client = await bridge.api<HotelClient>(`/hotel/clients?societe_id=${state.companyId}`, { method: 'POST', body: { code: code.trim(), nom: name.trim(), confirmer_homonyme: confirmable && confirmed } }); onSelected(client); } catch (cause) { setError(message(cause)); const flag = (cause as { data?: { can_confirm_similar?: boolean | string } }).data?.can_confirm_similar; setConfirmable(flag === true || flag === 'True'); } finally { pending.current = false; setBusy(false); } }}>
      <fieldset className="business-fieldset" disabled={busy}>{creating ? <div className="business-form-grid"><Field label="Code client" value={code} onChange={v => { setCode(v); resetConfirmation(); }} required maxLength={32} /><Field label="Nom du nouveau client" value={name} onChange={v => { setName(v); resetConfirmation(); }} required minLength={2} maxLength={255} /></div> : <Field label="Rechercher un client par nom ou code" type="search" value={search} onChange={setSearch} />}
      <div className="business-matches">{matches.slice(0, 40).map(c => <button type="button" className="btn" key={c.id} disabled={!c.actif} onClick={() => onSelected(c)}>{clientLabel(c)}</button>)}{!matches.length && <p>Aucune fiche correspondante.</p>}{matches.length > 40 && <p>Affinez votre recherche pour retrouver les autres fiches.</p>}</div>
      <ErrorNotice error={error} />{confirmable && <label className="business-check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> J’ai vérifié : il s’agit d’un client distinct malgré le même nom.</label>}</fieldset>
    </form>
  </Dialog>;
}
