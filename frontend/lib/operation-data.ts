export function amount(value: string, label: string, minimum = 0) {
  const n = Number(value);
  if (!value.trim() || !Number.isFinite(n) || n < minimum) throw new Error(`${label} : montant invalide (minimum ${minimum}).`);
  return n;
}
export const denominations: Record<string, number[]> = { USD: [100, 50, 20, 10, 5, 2, 1], CDF: [20000, 10000, 5000, 2000, 1000, 500, 200, 100, 50] };
export function countedCash(currency: string, counts: Record<string, string>) {
  const billetage: Record<string, number> = {};
  let montant = 0;
  for (const d of denominations[currency] || []) {
    const n = amount(counts[String(d)] || '0', `Nombre de billets de ${d}`);
    if (!Number.isSafeInteger(n)) throw new Error('Le nombre de billets doit être un entier positif ou nul.');
    if (n) billetage[String(d)] = n;
    montant += n * d;
  }
  if (!Number.isFinite(montant)) throw new Error('Comptage trop élevé.');
  return { montant, billetage };
}
