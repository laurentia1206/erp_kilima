export interface Tariff { trajet: string; mode: string; prix: string }
export function contractPayload(values: { libelle: string; client: string; debut: string; fin: string; note: string }, tariffs: Tariff[]) {
  if (values.libelle.trim().length < 2 || !values.client || !values.debut) throw new Error('Renseignez le libellé, le client et la date de début.');
  if (values.fin && values.fin < values.debut) throw new Error('La fin doit être postérieure ou égale au début.');
  const routes = new Set<string>();
  const tarifs = tariffs.map(t => {
    const trajet = t.trajet.trim();
    if (!trajet || !t.prix.trim() || !Number.isFinite(Number(t.prix)) || Number(t.prix) <= 0 || !['tonne', 'voyage'].includes(t.mode)) throw new Error('Complétez chaque trajet avec un tarif positif, ou retirez la ligne.');
    const key = trajet.toLocaleLowerCase('fr') + ':' + t.mode;
    if (routes.has(key)) throw new Error('Ce trajet comporte déjà un tarif pour ce mode.');
    routes.add(key);
    return { trajet, mode: t.mode, prix: Number(t.prix) };
  });
  return { libelle: values.libelle.trim(), client_tiers_id: values.client, date_debut: values.debut, date_fin: values.fin || null, note: values.note.trim() || null, tarifs };
}
export const documentTypes: Record<string, string> = { assurance: 'Assurance', controle_technique: 'Contrôle technique', carte_rose: 'Carte rose', vignette: 'Vignette', permis: 'Permis de conduire', certificat: 'Certificat', autre: 'Autre' };
export const documentStatuses: Record<string, string> = { echu: 'Échu', bientot: 'Expire bientôt', valide: 'Valide', permanent: 'Sans échéance' };
export function documentPayload(values: Record<string, string>, existing: boolean) {
  if (!values.libelle.trim() || !documentTypes[values.type_document]) throw new Error('Renseignez le libellé et le type de document.');
  if (values.date_emission && values.date_expiration && values.date_expiration < values.date_emission) throw new Error('L’expiration ne peut pas précéder l’émission.');
  const body: Record<string, string | null> = { type_document: values.type_document, libelle: values.libelle.trim(), numero: values.numero.trim() || null, date_emission: values.date_emission || null, date_expiration: values.date_expiration || null, note: values.note.trim() || null };
  if (!existing) { const [key, id] = values.porteur.split(':'); if (!['camion_id', 'engin_id', 'chauffeur_id'].includes(key) || !id) throw new Error('Choisissez le véhicule ou le chauffeur.'); body[key] = id; }
  return body;
}
