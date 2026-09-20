'use client';
import { useCallback, useRef, useState } from 'react';
import { DataTable } from './data-table';
import { Field } from './field';
import { Dialog, ErrorNotice, message, normalize, useResource, type ScreenProps } from './shared';

interface Article { id: string; code: string; designation: string; nature: string; unite: string; categorie: string; code_barres: string; prix_achat: number; prix_vente: number; assujetti_tva: boolean; taux_tva: number; taux_commission: number; points_fidelite: number; gere_stock: boolean; stock_qte: number; actif: boolean }
const natures: Record<string, string> = { marchandise: 'Marchandise / produit vendu', matiere_premiere: 'Matière première', consommable: 'Consommable' };
export function Articles({ bridge, state }: ScreenProps) {
  const load = useCallback(() => bridge.api<Article[]>(`/commercial/articles?societe_id=${state.companyId}`), [bridge, state.companyId]);
  const { data, error, busy, refresh } = useResource(load);
  const [editing, setEditing] = useState<Article | 'new' | null>(null), [success, setSuccess] = useState('');
  return <>
    <div className="audit-head"><div><h2>Catalogue des articles</h2><p className="muted">Articles propres à {state.companies.find(c => c.id === state.companyId)?.nom}. Les autres sociétés conservent leur propre catalogue.</p></div><div className="audit-actions"><button className="btn" disabled={busy} onClick={refresh}>Actualiser</button><button className="btn btn-primary" disabled={busy || !!error} onClick={() => setEditing('new')}>Nouvel article</button></div></div>
    <ErrorNotice error={error} />{success && <p role="status" className="business-success">{success}</p>}{busy && <p role="status">Chargement des articles…</p>}
    {data && <DataTable bridge={bridge} state={state} title="Catalogue des articles" subtitle="Prix en USD · société active" disabled={busy || !!error} columns={['Code', 'Désignation', 'Nature', 'Catégorie', 'Prix achat', 'Prix vente', 'TVA', 'Stock', 'Unité']} rows={data.map(a => [a.code, a.designation, natures[a.nature] || a.nature, a.categorie || '', a.prix_achat, a.prix_vente, a.assujetti_tva ? `${a.taux_tva} %` : 'Exonéré', a.gere_stock ? a.stock_qte : 'Non géré', a.unite])} actions={row => <button className="btn btn-sm" disabled={busy || !!error} onClick={() => setEditing(data.find(a => a.code === row[0])!)} aria-label={`Modifier l’article ${row[0]}`}>Modifier</button>} />}
    {editing && <ArticleEditor key={editing === 'new' ? 'new' : editing.id} bridge={bridge} state={state} article={editing === 'new' ? null : editing} articles={data || []} onClose={() => setEditing(null)} onExisting={setEditing} onSaved={() => { setEditing(null); setSuccess('Article enregistré dans la société active.'); refresh(); }} />}
  </>;
}
function ArticleEditor({ bridge, state, article, articles, onClose, onSaved, onExisting }: ScreenProps & { article: Article | null; articles: Article[]; onClose: () => void; onSaved: () => void; onExisting: (a: Article) => void }) {
  const load = useCallback(async () => article ? { rate: article.taux_tva, warning: '' } : bridge.api<{ tva_taux_defaut: number }>(`/comptabilite/comptes-config?societe_id=${state.companyId}`).then(d => ({ rate: d.tva_taux_defaut, warning: '' })).catch(() => ({ rate: 16, warning: 'Le taux par défaut de la société n’a pas pu être chargé. Vérifiez le taux proposé avant de créer cet article.' })), [bridge, state.companyId, article]);
  const { data, busy } = useResource(load);
  const [saving, setSaving] = useState(false);
  return <Dialog bridge={bridge} title={article ? `Article ${article.code}` : 'Nouvel article'} busy={saving} onClose={onClose} footer={close => <><button className="btn" disabled={saving} onClick={close}>Annuler</button><button className="btn btn-primary" type="submit" form="article-form" disabled={!data || busy || saving}>{saving ? 'Enregistrement…' : article ? 'Enregistrer' : 'Créer'}</button></>}>
    {busy ? <p role="status">Préparation du formulaire…</p> : data && <ArticleForm bridge={bridge} state={state} article={article} articles={articles} defaultRate={data.rate} warning={data.warning} saving={saving} setSaving={setSaving} onSaved={onSaved} onExisting={onExisting} />}
  </Dialog>;
}
function ArticleForm({ bridge, article, articles, defaultRate, warning, saving, setSaving, onSaved, onExisting, state }: ScreenProps & { article: Article | null; articles: Article[]; defaultRate: number; warning: string; saving: boolean; setSaving: (v: boolean) => void; onSaved: () => void; onExisting: (a: Article) => void }) {
  const [values, setValues] = useState({ code: article?.code || '', designation: article?.designation || '', unite: article?.unite || 'unité', categorie: article?.categorie || '', code_barres: article?.code_barres || '', nature: article?.nature || 'marchandise', prix_achat: String(article?.prix_achat ?? 0), prix_vente: String(article?.prix_vente ?? 0), taux_tva: String(article?.taux_tva ?? defaultRate), taux_commission: String(article?.taux_commission ?? 0), points_fidelite: String(article?.points_fidelite ?? 0), compte_achat: '601', compte_vente: '701', compte_stock: '31' });
  const [vat, setVat] = useState(article?.assujetti_tva ?? true), [stock, setStock] = useState(article?.gere_stock ?? true), [error, setError] = useState(''), [canConfirm, setCanConfirm] = useState(false), [confirmed, setConfirmed] = useState(false);
  const pending = useRef(false);
  const update = (key: keyof typeof values, value: string) => { setValues(previous => ({ ...previous, [key]: value })); if (['code', 'designation', 'code_barres'].includes(key)) { setCanConfirm(false); setConfirmed(false); } };
  const matches = articles.filter(a => a.id !== article?.id && ((values.code && normalize(a.code) === normalize(values.code)) || (values.code_barres && a.code_barres === values.code_barres) || (values.designation.trim().length >= 2 && normalize(a.designation).includes(normalize(values.designation.trim()))))).slice(0, 8);
  return <form id="article-form" onSubmit={async e => {
    e.preventDefault(); if (pending.current) return;
    pending.current = true; setSaving(true); setError('');
    const common = { designation: values.designation.trim(), nature: values.nature, categorie: values.categorie.trim(), code_barres: values.code_barres.trim(), prix_achat: Number(values.prix_achat), prix_vente: Number(values.prix_vente), assujetti_tva: vat, taux_tva: vat ? Number(values.taux_tva) : 0, taux_commission: Number(values.taux_commission), points_fidelite: Number(values.points_fidelite), gere_stock: stock, confirmer_homonyme: canConfirm && confirmed };
    try {
      await bridge.api(article ? `/commercial/articles/${article.id}` : `/commercial/articles?societe_id=${state.companyId}`, { method: article ? 'PATCH' : 'POST', body: article ? common : { ...common, code: values.code.trim(), unite: values.unite.trim(), compte_achat: values.compte_achat.trim(), compte_vente: values.compte_vente.trim(), compte_stock: values.compte_stock.trim() } });
      onSaved();
    } catch (cause) { setError(message(cause)); const data = (cause as { data?: { can_confirm_similar?: boolean | string } }).data; setCanConfirm(data?.can_confirm_similar === true || data?.can_confirm_similar === 'True'); }
    finally { pending.current = false; setSaving(false); }
  }}>
    <p className="catalogue-scope">Fiche propre à <b>{state.companies.find(c => c.id === state.companyId)?.nom}</b></p>{warning && <p className="banner">{warning}</p>}
    <fieldset disabled={saving} className="business-fieldset">
      <label className="business-field">Nature<select className="form-select" value={values.nature} onChange={e => update('nature', e.target.value)}>{Object.entries(natures).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <div className="business-form-grid"><Field label="Code" required maxLength={32} readOnly={!!article} value={values.code} onChange={v => update('code', v)} /><Field label="Unité" required readOnly={!!article} value={values.unite} onChange={v => update('unite', v)} /><Field label="Catégorie" value={values.categorie} onChange={v => update('categorie', v)} /><Field label="Désignation" required maxLength={255} value={values.designation} onChange={v => update('designation', v)} /><Field label="Code-barres" value={values.code_barres} onChange={v => update('code_barres', v)} /></div>
      {matches.length > 0 && <div className="business-matches"><p>Fiches déjà présentes dans cette société :</p>{matches.map(a => <button className="btn" type="button" key={a.id} onClick={() => onExisting(a)}>Ouvrir {a.code} — {a.designation}</button>)}</div>}
      <div className="business-form-grid">{([['prix_achat', 'Prix d’achat (USD)'], ['prix_vente', 'Prix de vente (USD)'], ['taux_tva', 'TVA (%)'], ['taux_commission', 'Commission vendeur (%)'], ['points_fidelite', 'Points de fidélité / unité']] as const).map(([key, label]) => <Field key={key} label={label} type="number" required min={0} step="any" disabled={key === 'taux_tva' && !vat} value={values[key]} onChange={v => update(key, v)} />)}</div>
      <label className="business-check"><input type="checkbox" checked={vat} onChange={e => { setVat(e.target.checked); if (!e.target.checked) update('taux_tva', '0'); else if (Number(values.taux_tva) === 0) update('taux_tva', String(defaultRate)); }} /> Assujetti à la TVA</label>
      {!article && <div className="business-form-grid">{([['compte_achat', 'Compte achat'], ['compte_vente', 'Compte vente'], ['compte_stock', 'Compte stock']] as const).map(([key, label]) => <Field key={key} label={label} required value={values[key]} onChange={v => update(key, v)} />)}</div>}
      <label className="business-check"><input type="checkbox" checked={stock} onChange={e => setStock(e.target.checked)} /> Article géré en stock</label><p className="muted">Décochez pour un plat préparé à la demande ou un service. Les ingrédients d’un plat sont consommés via sa fiche technique. Un article ayant encore du stock ne peut pas passer en « sans stock ».</p>
      <ErrorNotice error={error} />{canConfirm && <label className="business-check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> J’ai vérifié : il s’agit d’un article distinct, malgré la même désignation.</label>}
    </fieldset>
  </form>;
}
