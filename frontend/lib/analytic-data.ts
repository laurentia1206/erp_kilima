export interface AnalyticSection { id: string; code: string; libelle: string; actif: boolean }
export interface AnalyticAxis { id: string; code: string; libelle: string; actif: boolean; sections: AnalyticSection[] }
export interface AnalyticLine { id: string; date: string; piece: string; journal: string; compte: string; libelle: string; type: string; montant: number; ventile: number; reste: number; ventilation: { section_id: string; section: string; montant: number }[] }
export interface AnalyticReport { axe: string; lignes: { section: string; code: string; charges: number; produits: number; resultat: number }[]; non_ventile: { charges: number; produits: number }; total_charges: number; total_produits: number; resultat: number }
export interface AllocationDraft { key: number; section_id: string; montant: string }
export function allocationPayload(rows: AllocationDraft[], line: AnalyticLine, axis: AnalyticAxis, confirmEmpty: boolean) {
  if (!rows.length && !confirmEmpty) throw new Error('Confirmez explicitement l’effacement de la ventilation.');
  let total = 0;
  const result = rows.map((row, i) => {
    if (!axis.sections.some(s => s.id === row.section_id)) throw new Error(`Ligne ${i + 1} : choisissez une section de cet axe.`);
    if (!/^\d+(\.\d{1,2})?$/.test(row.montant.trim())) throw new Error(`Ligne ${i + 1} : montant positif requis, avec deux décimales au maximum.`);
    const [whole, fraction = ''] = row.montant.trim().split('.');
    const cents = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
    if (!Number.isSafeInteger(cents) || cents <= 0) throw new Error(`Ligne ${i + 1} : montant invalide.`);
    total += cents;
    return { section_id: row.section_id, montant: cents / 100 };
  });
  if (total > Math.round(line.montant * 100) + 1) throw new Error('La ventilation dépasse le montant de la ligne.');
  return result;
}
export function sameAllocation(a: AnalyticLine, b: AnalyticLine) {
  const signature = (line: AnalyticLine) => JSON.stringify(line.ventilation.map(v => `${v.section_id}:${v.montant}`).sort());
  return a.id === b.id && a.montant === b.montant && signature(a) === signature(b);
}
export const analyticColumns = ['Date', 'Pièce', 'Journal', 'Compte', 'Libellé', 'Type', 'Montant USD', 'Ventilé USD', 'Reste USD', 'Sections'];
export const analyticNote = 'Tout l’historique de la société, écritures validées et en attente. Les montants suivent le calcul analytique existant : valeurs des lignes sans compensation débit/crédit. Ce rapport de ventilation ne remplace pas le compte de résultat.';
export function analyticRows(lines: AnalyticLine[]) {
  return lines.map(l => [l.date, l.piece, l.journal, l.compte, l.libelle, l.type === 'charge' ? 'Charge' : 'Produit', l.montant, l.ventile, l.reste, l.ventilation.map(v => `${v.section} : ${new Intl.NumberFormat('fr-FR').format(v.montant)} USD`).join(' ; ')]);
}
export function analyticReportRows(report: AnalyticReport) {
  return [...report.lignes.map(l => [l.code, l.section, l.charges, l.produits, l.resultat]), ['', 'Non ventilé', report.non_ventile.charges, report.non_ventile.produits, Math.round((report.non_ventile.produits - report.non_ventile.charges) * 100) / 100], ['', 'TOTAL', report.total_charges, report.total_produits, report.resultat]];
}
