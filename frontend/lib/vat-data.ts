export interface VatState {
  mois: string; du: string; au: string; devise: string; note: string;
  comptes: { collectee: string; deductible: string };
  totaux: { valide: { collectee: string; deductible: string }; en_attente: { collectee: string; deductible: string } };
  solde_mouvements_usd: string;
  ventilation_taux: { sens: string; taux: string; ht_usd: string; tva_usd: string }[];
  lignes: { date: string; piece: string; reference: string; compte: string; nature: string; sens: string; montant_usd: string; net_usd: string; statut: string; libelle: string }[];
  factures: { numero: string; date: string; type: string; tiers: string; statut: string; ht_usd: string; tva_usd: string }[];
}
export interface VatDraft { notes: string; credit_anterieur_cdf: string; montant_declare_cdf: string; reference_depot: string; date_depot: string }
export interface VatFile { revision: number; updated_at: string | null; donnees: Partial<VatDraft> & { etat?: VatState } }
export const vatColumns = ['Date', 'Pièce', 'Référence', 'Compte', 'Nature', 'Sens', 'Montant USD', 'TVA signée USD', 'Statut', 'Libellé'];
export function vatRows(state: VatState) { return state.lignes.map(l => [l.date, l.piece, l.reference, l.compte, l.nature === 'collectee' ? 'Collectée' : 'Déductible', l.sens, Number(l.montant_usd), Number(l.net_usd), l.statut === 'valide' ? 'Validée' : 'En attente', l.libelle]); }
export function vatDraft(file: VatFile): VatDraft { return { notes: file.donnees.notes || '', credit_anterieur_cdf: file.donnees.credit_anterieur_cdf || '', montant_declare_cdf: file.donnees.montant_declare_cdf || '', reference_depot: file.donnees.reference_depot || '', date_depot: file.donnees.date_depot || '' }; }
export function validateVatDraft(draft: VatDraft, today: string) {
  for (const value of [draft.credit_anterieur_cdf, draft.montant_declare_cdf]) if (value.trim() && (!/^\d+(\.\d{1,2})?$/.test(value.trim()) || !Number.isFinite(Number(value)))) throw new Error('Saisissez des montants CDF positifs ou nuls, avec deux décimales au maximum. Laissez vide si le montant n’est pas renseigné.');
  if (!!draft.reference_depot.trim() !== !!draft.date_depot) throw new Error('Renseignez ensemble la référence et la date du dépôt déjà effectué.');
  if (draft.date_depot && (!/^\d{4}-\d{2}-\d{2}$/.test(draft.date_depot) || !Number.isFinite(Date.parse(draft.date_depot)) || new Date(draft.date_depot).toISOString().slice(0, 10) !== draft.date_depot || draft.date_depot > today)) throw new Error('La date du dépôt doit être valide et ne peut pas être future.');
  return { ...draft, reference_depot: draft.reference_depot.trim(), notes: draft.notes.trim() };
}
