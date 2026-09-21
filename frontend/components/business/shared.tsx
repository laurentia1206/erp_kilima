'use client';
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import type { Bridge, Snapshot } from '../../lib/runtime';
import { serverTimestamp } from '../../lib/date-data';

export type ScreenProps = { bridge: Bridge; state: Snapshot };
export const message = (error: unknown) => error instanceof Error ? error.message : 'Opération impossible. Réessayez.';
export const number = (value: number | string | null | undefined) => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 }).format(Number(value ?? 0));
export const dateTime = (value?: string | null) => value ? new Date(serverTimestamp(value)).toLocaleString('fr-FR', { timeZone: 'Africa/Lubumbashi' }) : 'Non renseignée';
export const today = () => new Date().toLocaleDateString('fr-CA', { timeZone: 'Africa/Lubumbashi' });
export const normalize = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

// Une réponse ancienne ne peut pas remplacer celle du filtre ou de la société active.
export function useResource<T>(load: () => Promise<T>, interval = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision(n => n + 1), []);
  useEffect(() => {
    let alive = true;
    setBusy(true); setError('');
    load().then(value => { if (alive) setData(value); })
      .catch(cause => { if (alive) setError(message(cause)); })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [load, revision]);
  useEffect(() => {
    if (!interval) return;
    const update = () => { if (!document.hidden) refresh(); };
    const timer = setInterval(update, interval);
    document.addEventListener('visibilitychange', update);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', update); };
  }, [interval, refresh]);
  return { data, error, busy, refresh };
}
export function ErrorNotice({ error }: { error: string }) { return error ? <p role="alert" className="business-error">{error}</p> : null; }
export function Pages({ page, pages, change, disabled = false }: { page: number; pages: number; change: (page: number) => void; disabled?: boolean }) {
  return <div className="business-pages"><span>Page {page} / {pages}</span><button type="button" className="btn" disabled={disabled || page <= 1} onClick={() => change(page - 1)}>Précédent</button><button type="button" className="btn" disabled={disabled || page >= pages} onClick={() => change(page + 1)}>Suivant</button></div>;
}
export function Dialog({ bridge, title, children, onClose, footer, busy = false }: { bridge: Bridge; title: string; children: ReactNode; onClose: () => void; footer?: (close: () => void) => ReactNode; busy?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const release = useRef<(() => void) | null>(null);
  const id = useId();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    release.current = bridge.holdNavigation();
    const dialog = ref.current;
    dialog?.showModal();
    return () => { release.current?.(); release.current = null; dialog?.close(); previous?.focus(); };
  }, [bridge]);
  const close = () => { if (busy) return; release.current?.(); release.current = null; onClose(); };
  return createPortal(<dialog ref={ref} className="business-dialog" aria-labelledby={id} onCancel={event => { event.preventDefault(); close(); }}>
    <header><h2 id={id}>{title}</h2><button type="button" className="btn btn-sm" aria-label="Fermer la fenêtre" disabled={busy} onClick={close}>×</button></header>
    <div className="business-dialog-body">{children}</div>
    <footer>{footer ? footer(close) : <button type="button" className="btn" disabled={busy} onClick={close}>Fermer</button>}</footer>
  </dialog>, document.getElementById('react-modal-root')!);
}
export interface Report { title: string; subtitle: string; columns: string[]; rows: (string | number)[][]; note?: string }
export async function exportReport(bridge: Bridge, companyId: string | null, report: Report, format: 'pdf' | 'xlsx') {
  if (!companyId) throw new Error('Sélectionnez une société.');
  await bridge.download(`/editions/telecharger?societe_id=${encodeURIComponent(companyId)}`, report.title.replace(/[<>:"/\\|?*]/g, ' ') + '.' + format,
    { titre: report.title, sous_titre: report.subtitle, format, blocs: [{ type: 'table', colonnes: report.columns, lignes: report.rows }, ...(report.note ? [{ type: 'texte', texte: report.note }] : [])] });
}
export function ReportPreview({ bridge, state, report, onClose }: ScreenProps & { report: Report; onClose: () => void }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const download = async (format: 'pdf' | 'xlsx') => { setBusy(true); setError(''); try { await exportReport(bridge, state.companyId, report, format); } catch (e) { setError(message(e)); } finally { setBusy(false); } };
  return <Dialog bridge={bridge} title="Aperçu du rapport" busy={busy} onClose={onClose} footer={close => <><button type="button" className="btn" disabled={busy} onClick={close}>Fermer</button><button type="button" className="btn" disabled={busy} onClick={() => window.print()}>Imprimer</button>{!state.user?.super_administrateur && state.companyId && <><button type="button" className="btn" disabled={busy} onClick={() => download('xlsx')}><i className="ti ti-file-spreadsheet" aria-hidden="true" /> Excel</button><button type="button" className="btn btn-primary" disabled={busy} onClick={() => download('pdf')}>Télécharger le PDF</button></>}</>}>
    <ErrorNotice error={error} /><article className="business-print"><header><strong>{state.user?.super_administrateur ? 'KILIMA HOLDINGS · Administration du système' : state.companies.find(c => c.id === state.companyId)?.nom}</strong></header><h2>{report.title}</h2><p>{report.subtitle}</p><div className="business-table"><table><thead><tr>{report.columns.map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>{report.rows.map((row, i) => <tr key={i}>{row.map((v, j) => <td key={j} className={typeof v === 'number' ? 'right' : undefined}>{typeof v === 'number' ? number(v) : v}</td>)}</tr>)}</tbody></table></div><p>{report.note}</p></article>
  </Dialog>;
}
