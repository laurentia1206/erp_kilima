export interface KitchenConfig { depot_id: string; depot: string; depot_est_central: boolean; seuil_food_cost_pct: number }
export interface Recipe { id: string; article_id: string; plat: string; code: string; prix_vente: number; portions: number; cout_portion: number; food_cost_pct: number | null; marge_portion: number; note: string; lignes: { article_id: string; code: string; designation: string; unite: string; qte: number; qte_par_portion: number; cump: number; cout_par_portion: number }[] }
export interface Consumption { id: string; numero: string; date: string; depot: string; cout_total: number; ca_total: number; nb_plats: number; food_cost_pct: number | null; alerte: boolean; alertes?: string[]; lignes: { code: string; designation: string; qte: number; valeur: number }[] }
export interface KitchenReport { du: string; au: string; depot_inventaire: string; inventaires_valides: number; manquants_inventaire: number; excedents_inventaire: number; jours_generes: number; cout_theorique: number; ca_plats: number; nb_plats: number; food_cost_pct: number | null; seuil_pct: number; alerte: boolean }
export function recipePayload(article: string, portions: string, lines: { article_id: string; qte: string }[]) {
  if (!article || !portions.trim() || !Number.isFinite(Number(portions)) || Number(portions) <= 0) throw new Error('Choisissez un plat et un nombre de portions strictement positif.');
  if (!lines.length || lines.some(l => !l.article_id || !l.qte.trim() || !Number.isFinite(Number(l.qte)) || Number(l.qte) <= 0)) throw new Error('Chaque ingrédient doit avoir une quantité positive.');
  if (lines.some(l => l.article_id === article)) throw new Error('Le plat ne peut pas être son propre ingrédient.');
  if (new Set(lines.map(l => l.article_id)).size !== lines.length) throw new Error('Regroupez chaque ingrédient sur une seule ligne.');
  return { article_id: article, portions: Number(portions), lignes: lines.map(l => ({ article_id: l.article_id, qte: Number(l.qte) })) };
}
