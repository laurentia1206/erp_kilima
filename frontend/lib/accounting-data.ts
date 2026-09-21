export interface Account { id: string; numero: string; intitule: string; classe: string; actif: boolean; auxiliaire: boolean }
export interface Journal { id: string; code: string; libelle: string; type: string; actif: boolean }
export interface Party { id: string; code: string; nom: string; type: string; actif: boolean; societe_id: string | null }
export const partyLabel = (p: Party) => `${p.code} — ${p.nom} · ${p.type} · ${p.societe_id ? 'Société active' : 'Fiche partagée'}`;
export const accountingStatuses: Record<string, string> = { '': 'Toutes les écritures', valide: 'Écritures validées', en_attente: 'Écritures en attente' };
export interface BalanceData { annee: number; total_debit: number; total_credit: number; equilibre: boolean; lignes: { compte: string; intitule: string; debit: number; credit: number; solde_debiteur: number; solde_crediteur: number; solde_n1: number }[] }
export interface LedgerMovement { date: string; piece: string; journal: string; libelle: string; tiers: string | null; lettrage: string | null; debit: number; credit: number; solde: number; statut: string }
export interface LedgerAccount { compte: string; intitule: string; solde: number; mouvements: LedgerMovement[] }
export interface EntryLine { key: number; sens: 'D' | 'C'; compte: string; tiers_id: string; libelle: string; montant: string }
export interface Entry { id: string; numero: string; date: string; libelle: string; journal: string; statut: string; piece: string | null; montant: number; lignes: { sens: string; compte: string; intitule: string; tiers: string | null; montant_usd: number; libelle: string | null }[] }
export function cents(value: string): number {
  if (!/^\d+(\.\d{1,2})?$/.test(value.trim())) throw new Error('Utilisez un montant positif avec au maximum deux décimales.');
  const [whole, fraction = ''] = value.trim().split('.');
  const amount = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
  if (!Number.isSafeInteger(amount) || amount <= 0) throw new Error('Le montant doit être positif et valide.');
  return amount;
}
export function entryTotals(lines: EntryLine[]) {
  let debit = 0, credit = 0, valid = true;
  for (const line of lines) { try { const amount = cents(line.montant); if (line.sens === 'D') debit += amount; else credit += amount; } catch { valid = false; } }
  return { debit: debit / 100, credit: credit / 100, difference: (debit - credit) / 100, balanced: valid && debit > 0 && debit === credit };
}
export function entryPayload(lines: EntryLine[], accounts: Account[], parties: Party[], companyId: string, journal: string, day: string, label: string, reference: string) {
  if (!label.trim() || !journal || !/^\d{4}-\d{2}-\d{2}$/.test(day) || new Date(`${day}T00:00:00Z`).toISOString().slice(0, 10) !== day) throw new Error('Journal, date valide et libellé requis.');
  if (lines.length < 2) throw new Error('Saisissez au moins deux lignes.');
  const lignes = lines.map((line, index) => {
    const prefix = `Ligne ${index + 1} : `;
    if (!['D', 'C'].includes(line.sens) || !accounts.some(a => a.numero === line.compte)) throw new Error(prefix + 'choisissez un compte du plan de la société.');
    if (line.tiers_id && !parties.some(p => p.id === line.tiers_id && p.actif && (!p.societe_id || p.societe_id === companyId))) throw new Error(prefix + 'tiers indisponible dans cette société.');
    let amount; try { amount = cents(line.montant); } catch (error) { throw new Error(prefix + (error as Error).message); }
    return { sens: line.sens, compte: line.compte, montant: amount / 100, tiers_id: line.tiers_id || null, libelle: line.libelle.trim() || null };
  });
  if (!entryTotals(lines).balanced) throw new Error('Le total débit doit être égal au total crédit, au centime près.');
  return { journal_code: journal, date_ecriture: day, libelle: label.trim(), numero_piece: reference.trim() || null, lignes };
}
export function ledgerRows(accounts: LedgerAccount[]) {
  return accounts.flatMap(a => a.mouvements.map(m => [a.compte, a.intitule, m.date, m.journal, m.piece, m.libelle, m.tiers || '', m.lettrage || '', m.statut === 'valide' ? 'Validée' : m.statut === 'en_attente' ? 'En attente' : m.statut, m.debit, m.credit, m.solde]));
}
export const ledgerColumns = ['Compte', 'Intitulé', 'Date', 'Journal', 'Pièce', 'Libellé', 'Tiers', 'Lettrage', 'Statut', 'Débit USD', 'Crédit USD', 'Solde progressif USD'];
export const ledgerNote = 'Solde progressif calculé par compte dans l’ordre comptable, sur tout l’historique du périmètre demandé. Un tri ou une recherche dans le tableau ne recalcule pas ce solde. Un solde positif est débiteur ; un solde négatif est créditeur.';
