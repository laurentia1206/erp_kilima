import type { Account, Entry } from './accounting-data';
import type { AnalyticAxis } from './analytic-data';
export interface ReviewEntry extends Entry { revision: string; provenance: string; source: string | null; nb_pj: number; lignes: (Entry['lignes'][number] & { id: string; tiers_id: string | null })[] }
export interface ReviewPart { key: number; compte_numero: string; montant: string; libelle: string }
export interface ReviewAllocation { axe_id: string; rows: { key: number; section_id: string; montant: string }[] }
export interface ReviewDraft { compte: string; parts: ReviewPart[] | null; allocation: ReviewAllocation | null }
const amount = (v: string) => { if (!/^\d+(\.\d{1,2})?$/.test(v.trim())) throw new Error('Montant positif requis, avec deux décimales au maximum.'); const c = Math.round(Number(v) * 100); if (!Number.isSafeInteger(c) || c <= 0) throw new Error('Montant invalide.'); return c; };
export function reviewPayload(entry: ReviewEntry, drafts: Record<string, ReviewDraft>, accounts: Account[], axes: AnalyticAxis[]) {
  const reclassements: { ligne_id: string; compte_numero: string }[] = [], splits: { ligne_id: string; repartition: { compte_numero: string; montant: number; libelle: string | null }[] }[] = [], ventilations: { ligne_id: string; axe_id: string; repartition: { section_id: string; montant: number }[] }[] = [];
  for (const line of entry.lignes) {
    const draft = drafts[line.id];
    if (!draft) throw new Error('Une ligne de la pièce manque. Rechargez la pièce.');
    if (draft.parts) {
      if (!draft.parts.length) throw new Error('L’éclatement doit contenir au moins une ligne.');
      if (draft.allocation) throw new Error('Pour une ligne éclatée, préparez l’analytique après validation depuis le menu Analytique.');
      const repartition = draft.parts.map(r => { if (!accounts.some(a => a.numero === r.compte_numero.trim())) throw new Error('Choisissez chaque compte d’éclatement dans le plan.'); return { compte_numero: r.compte_numero.trim(), montant: amount(r.montant) / 100, libelle: r.libelle.trim() || null }; });
      if (repartition.reduce((s, r) => s + Math.round(r.montant * 100), 0) !== Math.round(line.montant_usd * 100)) throw new Error('Le total de l’éclatement doit égaler exactement le montant de la ligne.');
      splits.push({ ligne_id: line.id, repartition });
    } else {
      const compte = draft.compte.trim();
      if (!accounts.some(a => a.numero === compte)) throw new Error(`Compte ${compte || 'vide'} absent du plan comptable.`);
      if (compte !== line.compte) reclassements.push({ ligne_id: line.id, compte_numero: compte });
      if (draft.allocation) {
        const axis = axes.find(a => a.id === draft.allocation!.axe_id);
        if (!axis || !'67'.includes(compte[0]) || !draft.allocation.rows.length) throw new Error('Ventilation incomplète : choisissez un axe et ses sections pour une charge ou un produit.');
        const repartition = draft.allocation.rows.map(r => { if (!axis.sections.some(s => s.id === r.section_id)) throw new Error('Choisissez une section de l’axe.'); return { section_id: r.section_id, montant: amount(r.montant) / 100 }; });
        if (repartition.reduce((s, r) => s + Math.round(r.montant * 100), 0) > Math.round(line.montant_usd * 100)) throw new Error('La ventilation analytique dépasse le montant de la ligne.');
        ventilations.push({ ligne_id: line.id, axe_id: axis.id, repartition });
      }
    }
  }
  return { body: { revision: entry.revision, reclassements, splits }, ventilations };
}
export function reviewRows(entries: ReviewEntry[]) { return entries.map(e => [e.date, e.numero, e.provenance || 'Divers', e.journal || '', e.libelle, e.piece || '', e.source || '', e.montant, e.nb_pj, e.lignes.map(l => `${l.compte} ${l.tiers || ''}`).join(' ; ')]); }
export const reviewColumns = ['Date', 'Pièce', 'Provenance', 'Journal', 'Libellé', 'Référence', 'Source', 'Montant USD', 'Justificatifs', 'Comptes et tiers'];
