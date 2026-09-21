export type CommercialRow = Record<string, string>;
// L’API conserve la remise effective, qui inclut déjà la remise globale.
export function lineDiscountForEdit(effective: number, global: number) {
  if (global >= 100) return 0;
  return Math.max(0, Math.min(100, Math.round((1 - (1 - effective / 100) / (1 - global / 100)) * 100000000) / 1000000));
}
export function commercialNumber(value: string | number, name: string, max = Infinity) {
  if (String(value).trim() === '' || !Number.isFinite(Number(value)) || Number(value) < 0 || Number(value) > max) throw new Error(`${name} : valeur invalide.`);
  return Number(value);
}
export function commercialLines(rows: CommercialRow[], discount = false) {
  if (!rows.length) throw new Error('Ajoutez au moins une ligne.');
  return rows.map((r, i) => {
    const qte = commercialNumber(r.qte, `Quantité, ligne ${i + 1}`);
    if (!qte || !r.designation.trim()) throw new Error(`Complétez la désignation et la quantité de la ligne ${i + 1}.`);
    return { article_id: r.article_id || null, designation: r.designation.trim(), qte, prix_unitaire: commercialNumber(r.prix_unitaire, 'Prix unitaire'), taux_tva: commercialNumber(r.taux_tva, 'TVA', 100), ...(discount ? { remise_pct: commercialNumber(r.remise_pct || '0', 'Remise', 100) } : {}) };
  });
}
export function commercialTotals(rows: CommercialRow[], globalDiscount = '0') {
  const g = commercialNumber(globalDiscount, 'Remise globale', 100), round = (n: number) => Math.round((n + Number.EPSILON) * 100) / 100;
  let brut = 0, ht = 0, tva = 0;
  for (const r of commercialLines(rows, true)) {
    const base = round(r.qte * r.prix_unitaire), net = round(base * (1 - (r.remise_pct || 0) / 100) * (1 - g / 100));
    brut += base; ht += net; tva += round(net * r.taux_tva / 100);
  }
  return { ht: round(ht), tva: round(tva), ttc: round(ht + tva), remise: round(brut - ht) };
}
