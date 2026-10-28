'use client';
import { useMemo, useRef, useState } from 'react';
import { normalize } from './shared';

export interface SearchableAccount { numero: string; intitule: string; actif?: boolean }

/** Sélecteur de compte avec recherche : on tape un numéro ou un mot de
 *  l'intitulé (accents ignorés), puis on choisit dans la liste filtrée. */
export function AccountSearchField({ label, value, accounts, onChange, required = false, placeholder = 'Numéro ou intitulé du compte…' }: { label: string; value: string; accounts: SearchableAccount[]; onChange: (numero: string) => void; required?: boolean; placeholder?: string }) {
  const [query, setQuery] = useState<string | null>(null), [open, setOpen] = useState(false), [cursor, setCursor] = useState(0);
  const anchor = useRef<HTMLLabelElement>(null);
  const selected = accounts.find(a => a.numero === value);
  const text = query ?? (selected ? `${selected.numero} — ${selected.intitule}` : value);
  const matches = useMemo(() => {
    const q = normalize((query ?? '').trim());
    return (q ? accounts.filter(a => normalize(`${a.numero} ${a.intitule}`).includes(q)) : accounts).slice(0, 40);
  }, [accounts, query]);
  const pick = (a: SearchableAccount) => { onChange(a.numero); setQuery(null); setOpen(false); };
  const close = () => {
    if (query !== null) {
      const exact = accounts.find(a => a.numero === query.trim());
      if (exact) onChange(exact.numero);
      else if (!query.trim()) onChange('');
    }
    setQuery(null); setOpen(false);
  };
  return <label className="business-field account-search" ref={anchor} onBlur={e => { if (!anchor.current?.contains(e.relatedTarget as Node)) close(); }}>{label}
    <input className="form-input" type="text" role="combobox" aria-expanded={open} aria-autocomplete="list" autoComplete="off" required={required} placeholder={placeholder} value={text}
      onFocus={() => { setOpen(true); setCursor(0); }}
      onChange={e => { setQuery(e.target.value); setOpen(true); setCursor(0); }}
      onKeyDown={e => {
        if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setCursor(c => Math.min(c + 1, matches.length - 1)); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor(c => Math.max(c - 1, 0)); }
        else if (e.key === 'Enter' && open) { if (matches[cursor]) { e.preventDefault(); pick(matches[cursor]); } }
        else if (e.key === 'Escape' && open) { e.stopPropagation(); setQuery(null); setOpen(false); }
      }} />
    {open && <ul className="account-search-list" role="listbox">
      {matches.map((a, i) => <li key={a.numero} role="option" aria-selected={i === cursor}><button type="button" tabIndex={-1} className={i === cursor ? 'active' : ''} onMouseDown={e => { e.preventDefault(); pick(a); }}><strong>{a.numero}</strong> — {a.intitule}{a.actif === false ? ' (inactif)' : ''}</button></li>)}
      {!matches.length && <li className="account-search-empty">Aucun compte ne correspond à cette recherche.</li>}
    </ul>}
  </label>;
}
