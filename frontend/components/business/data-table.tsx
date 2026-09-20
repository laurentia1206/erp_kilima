'use client';
import { useState, type ReactNode } from 'react';
import { selectTableRows, tableCSV, type Cell } from '../../lib/table-data';
import { Pages, ReportPreview, number, type ScreenProps } from './shared';

export function DataTable({ bridge, state, title, columns, rows, subtitle, disabled = false, actions }: ScreenProps & { title: string; columns: string[]; rows: Cell[][]; subtitle: string; disabled?: boolean; actions?: (row: Cell[]) => ReactNode }) {
  const [search, setSearch] = useState(''), [sort, setSort] = useState(-1), [direction, setDirection] = useState(1), [size, setSize] = useState(25), [page, setPage] = useState(1), [preview, setPreview] = useState(false);
  const selected = selectTableRows(rows, search, sort, direction), pages = Math.max(1, Math.ceil(selected.length / size)), current = Math.min(page, pages);
  const reset = () => { setSearch(''); setSort(-1); setDirection(1); setPage(1); };
  const csv = () => { const url = URL.createObjectURL(new Blob([tableCSV(columns, selected)], { type: 'text/csv;charset=utf-8' })); const a = document.createElement('a'); a.href = url; a.download = title + '.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 30000); };
  return <section className="business-grid" aria-label={title}>
    <div className="business-toolbar"><label>Rechercher · {title}<input className="form-input" type="search" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} placeholder="Plusieurs mots possibles…" /></label><label>Lignes par page<select className="form-select" value={size} onChange={e => { setSize(Number(e.target.value)); setPage(1); }}>{[25, 50, 100].map(n => <option key={n}>{n}</option>)}</select></label><button className="btn" onClick={reset}>Réinitialiser</button><button className="btn" disabled={disabled || !selected.length} onClick={() => setPreview(true)}>Rapport PDF / Excel</button><button className="btn" disabled={disabled || !selected.length} onClick={csv}>CSV</button></div>
    <p className="muted" role="status">{selected.length} résultats sur {rows.length} lignes chargées · {subtitle}</p>
    <div className="card business-table"><table><thead><tr>{columns.map((col, index) => <th key={col} aria-sort={sort === index ? direction === 1 ? 'ascending' : 'descending' : 'none'}><button className="list-sort" onClick={() => { setDirection(sort === index ? -direction : 1); setSort(index); setPage(1); }}>{col}{sort === index ? direction === 1 ? ' ↑' : ' ↓' : ''}</button></th>)}{actions && <th>Actions</th>}</tr></thead><tbody>{selected.slice((current - 1) * size, current * size).map((row, i) => <tr key={i}>{row.map((cell, index) => <td key={index} className={typeof cell === 'number' ? 'right' : undefined}>{typeof cell === 'number' ? number(cell) : cell}</td>)}{actions && <td>{actions(row)}</td>}</tr>)}{!selected.length && <tr><td colSpan={columns.length + (actions ? 1 : 0)} className="audit-empty">Aucune ligne pour cette recherche.</td></tr>}</tbody></table></div>
    <Pages page={current} pages={pages} change={setPage} />
    {preview && <ReportPreview bridge={bridge} state={state} onClose={() => setPreview(false)} report={{ title, subtitle: `${subtitle} · Recherche : ${search || 'aucune'} · ${selected.length} lignes`, columns, rows: selected.map(row => row.map(cell => cell ?? '')), note: 'Ce rapport reprend toute la sélection filtrée, y compris les autres pages. Les valeurs de stock sont au coût moyen pondéré et ne remplacent pas un inventaire physique validé.' }} />}
  </section>;
}
