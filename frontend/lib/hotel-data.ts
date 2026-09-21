export interface HotelRoom { id: string; numero: string; categorie: string; tarif_nuit_usd: number; capacite: number; etat: string; actif: boolean; sejour?: { id: string; client: string } }
export interface HotelClient { id: string; code: string; nom: string; actif: boolean; societe_id: string | null }
export interface Stay { id: string; numero: string; chambre_id: string; chambre: string; tiers_id: string | null; client_nom: string; client_telephone: string | null; nb_personnes: number; date_arrivee: string; date_depart_prevue: string; date_depart: string | null; tarif_nuit_usd: number; statut: string; source: string; note: string | null; facture: string | null; facture_id: string | null }
export interface Extra { id: string; date: string; designation: string; qte: number; prix_unitaire: number; montant_usd: number; origine: string }
export interface Ticket { id: string; date: string; designation: string; montant_usd: number; origine: string; facture_pos_id: string; solde_du_usd: number }
export interface Folio { sejour: Stay; nuits: number; montant_nuitees: number; extras: Extra[]; tickets_pos: Ticket[]; total_extras: number; total_tickets_pos: number; total_a_facturer: number; total_note: number; solde_du_usd: number; facture_sejour: { id: string; numero: string; total_ht: number; total_tva: number; total_ttc: number; paye_usd: number; solde_du_usd: number } | null }
export interface HotelPlanning { du: string; jours: number; chambres: (HotelRoom & { occupations: { sejour_id: string; client: string; statut: string; du: string; au: string }[] })[] }
export interface HotelReport { du: string; au: string; taux_occupation_pct: number; revenu_hebergement_usd: number; adr_usd: number; revpar_usd: number; nuitees_vendues: number }
export const stayStatuses: Record<string, string> = { reservee: 'Réservé', arrivee: 'En séjour', terminee: 'Terminé', annulee: 'Annulé', no_show: 'Non présenté' };
export const roomStatuses: Record<string, string> = { libre: 'Libre', occupee: 'Occupée', sale: 'À nettoyer', nettoyage: 'En nettoyage', maintenance: 'Hors service' };
export const staySources: Record<string, string> = { directe: 'Directe', telephone: 'Téléphone', entreprise: 'Entreprise', en_ligne: 'En ligne' };
export const clientLabel = (c: HotelClient) => `${c.code} — ${c.nom} · ${c.societe_id === null ? 'Fiche partagée' : 'Société active'}${c.actif ? '' : ' · Inactif'}`;
export function shiftDay(day: string, days: number) { const date = new Date(day + 'T12:00:00Z'); date.setUTCDate(date.getUTCDate() + days); return date.toISOString().slice(0, 10); }
export function validateStay(arrival: string, departure: string, people: string, rate: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(arrival) || !/^\d{4}-\d{2}-\d{2}$/.test(departure) || departure <= arrival) throw new Error('Le départ doit être après l’arrivée (une nuit minimum).');
  if (!Number.isInteger(Number(people)) || Number(people) < 1) throw new Error('Renseignez un nombre entier de personnes, au moins égal à 1.');
  if (!rate.trim() || !Number.isFinite(Number(rate)) || Number(rate) < 0) throw new Error('Le tarif doit être un nombre positif ou nul.');
}
export interface PaymentPiece { id: string; label: string; amount: number }
export function paymentPieces(folio: Folio): PaymentPiece[] {
  const pieces: PaymentPiece[] = [], seen = new Set<string>();
  const invoice = folio.facture_sejour;
  if (invoice && invoice.solde_du_usd > 0.009) { pieces.push({ id: invoice.id, label: `Hébergement ${invoice.numero}`, amount: invoice.solde_du_usd }); seen.add(invoice.id); }
  for (const t of folio.tickets_pos) if (t.solde_du_usd > 0.009 && !seen.has(t.facture_pos_id)) { seen.add(t.facture_pos_id); pieces.push({ id: t.facture_pos_id, label: t.designation, amount: t.solde_du_usd }); }
  return pieces;
}
export function paymentAmount(amountUSD: number, currency: string, rate?: number | null) {
  if (!Number.isFinite(amountUSD) || amountUSD <= 0) throw new Error('Montant à encaisser invalide.');
  if (currency === 'USD') return Math.round(amountUSD * 100) / 100;
  if (currency !== 'CDF' || !rate || !Number.isFinite(rate) || rate <= 0) throw new Error('Le taux USD/CDF du jour doit être défini avant cet encaissement.');
  return Math.round(amountUSD * rate);
}
export function samePayments(a: PaymentPiece[], b: PaymentPiece[]) { return a.length === b.length && a.every(p => b.some(q => p.id === q.id && Math.abs(p.amount - q.amount) < 0.005)); }
