export interface Depot { id: string; libelle: string; type: string; actif: boolean; point_vente?: string; valeur_stock_usd: number; nb_references: number }
export interface StockLine { article_id: string; code: string; designation: string; unite: string; qte: number; cump: number; valeur?: number }
export interface DepotState { depot: Depot; articles: StockLine[]; catalogue: StockLine[]; valeur_totale: number }
export interface InventoryLine { code: string; designation: string; unite: string; qte_theorique: number; qte_reelle: number; ecart_qte: number; cump: number; ecart_valeur: number }
export interface Inventory { id: string; numero: string; date: string; depot_id: string; depot: string; statut: 'brouillon' | 'valide' | 'annule'; created_by: string; note: string; lignes: InventoryLine[]; valeur_theorique: number; valeur_reelle: number; ecart_valeur: number; ecriture?: string; statut_comptable?: string }
export interface Transfer { id: string; numero: string; date: string; source: string; cible: string; note: string; valeur_totale: number; lignes: { code: string; designation: string; qte: number; valeur: number }[] }
export const inventoryStatus = { brouillon: 'En attente de validation', valide: 'Validé', annule: 'Annulé' };
export const quantity = (value: number) => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 3 }).format(value);
export const cost = (value: number) => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 4 }).format(value);
export function validCount(value: string) { return value.trim() !== '' && Number.isFinite(Number(value)) && Number(value) >= 0; }
export function countPayload(rows: StockLine[], counts: Record<string, string>) {
  if (!rows.length || rows.some(r => !validCount(counts[r.article_id] ?? ''))) throw new Error('Renseignez toutes les quantités comptées ; saisissez 0 pour un article absent.');
  if (new Set(rows.map(r => r.article_id)).size !== rows.length) throw new Error('Un article ne peut apparaître deux fois.');
  return rows.map(r => ({ article_id: r.article_id, qte_reelle: Number(counts[r.article_id]), qte_theorique: r.qte }));
}
export function transferPayload(source: string, target: string, lines: { article_id: string; qte: string }[]) {
  if (!source || !target || source === target) throw new Error('Choisissez deux dépôts différents.');
  if (!lines.length || lines.some(l => !l.article_id || !validCount(l.qte) || Number(l.qte) < 0.001)) throw new Error('Choisissez un article et une quantité positive pour chaque ligne.');
  if (new Set(lines.map(l => l.article_id)).size !== lines.length) throw new Error('Regroupez les quantités d’un même article sur une seule ligne.');
  return lines.map(l => ({ article_id: l.article_id, qte: Number(l.qte) }));
}

export const accountingStatus = (status?: string) => status ? ({ en_attente: 'En attente', validee: 'Validée', valide: 'Validée', brouillon: 'Brouillon', annulee: 'Annulée', annule: 'Annulée' } as Record<string, string>)[status] || status : '—';
