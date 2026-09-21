export interface MatchingLine { id: string; date: string; journal: string; piece: string; libelle: string; debit: number; credit: number; statut: string; tiers?: string | null; lettrage?: string | null }
export interface MatchingData { compte: string; intitule: string; solde: number; solde_non_lettre: number; lignes: MatchingLine[] }
export interface BankingData { compte: string; intitule: string; solde_comptable: number; solde_rapproche: number; lignes: MatchingLine[] }
export interface Reconciliation { id: string; compte: string; date_releve: string; solde_releve: number; solde_comptable: number; solde_rapproche: number; ecart: number; statut: string; date: string }
export function selectionTotals(lines: MatchingLine[]) {
  const debit = lines.reduce((sum, l) => sum + Math.round(l.debit * 100), 0), credit = lines.reduce((sum, l) => sum + Math.round(l.credit * 100), 0);
  return { debit: debit / 100, credit: credit / 100, difference: (debit - credit) / 100, balanced: lines.length >= 2 && debit === credit };
}
export function verifyMatchingSelection(selected: MatchingLine[], fresh: MatchingLine[]) {
  if (new Set(selected.map(l => l.id)).size !== selected.length) throw new Error('La sélection contient une ligne en double.');
  for (const old of selected) { const line = fresh.find(l => l.id === old.id); if (!line || line.lettrage || line.debit !== old.debit || line.credit !== old.credit || line.statut !== old.statut || line.tiers !== old.tiers) throw new Error('Les lignes ont changé depuis la sélection. Fermez cette fenêtre et actualisez le compte.'); }
  return selected.map(l => l.id);
}
export function statementAmount(input: string) {
  if (!/^-?\d+(\.\d{1,2})?$/.test(input.trim()) || !Number.isFinite(Number(input)) || !Number.isSafeInteger(Math.round(Number(input) * 100))) throw new Error('Saisissez le solde du relevé avec au maximum deux décimales. Zéro et les soldes négatifs sont acceptés.');
  return Number(input);
}
export const matchingColumns = ['Date', 'Journal', 'Pièce', 'Libellé', 'Tiers', 'Statut', 'Débit USD', 'Crédit USD', 'Lettrage'];
export const matchingRows = (lines: MatchingLine[]) => lines.map(l => [l.date, l.journal, l.piece, l.libelle, l.tiers || '', l.statut === 'valide' ? 'Validée' : l.statut === 'en_attente' ? 'En attente' : l.statut, l.debit, l.credit, l.lettrage || '']);
