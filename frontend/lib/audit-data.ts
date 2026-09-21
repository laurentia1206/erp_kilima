export const auditActions: Record<string, string> = {
  CONNEXION_REUSSIE: 'Connexion réussie', CONNEXION_ECHEC: 'Échec de connexion',
  DECONNEXION: 'Déconnexion volontaire', ACCES_REFUSE: 'Accès refusé',
  MOT_DE_PASSE_MODIFIE: 'Mot de passe modifié', MOT_DE_PASSE_ECHEC: 'Changement de mot de passe refusé',
  ERREUR_SERVEUR: 'Erreur du serveur', CONSULTATION_TRACE: 'Consultation d’une trace',
  EXPORT_AUDIT: 'Export du journal', INSERT: 'Création', UPDATE: 'Modification', DELETE: 'Suppression',
};
export const attentionActions = new Set(['CONNEXION_ECHEC', 'ACCES_REFUSE', 'MOT_DE_PASSE_ECHEC', 'ERREUR_SERVEUR']);
export function auditActionLabel(action: string) { return auditActions[action] || action; }
export function assertAuditCapabilities(value: unknown) {
  const data = value as { actions?: unknown; indicateurs?: Record<string, unknown> } | null;
  if (!data || !Array.isArray(data.actions) || !data.actions.every(a => typeof a === 'string') || !data.indicateurs ||
      !['connexions', 'echecs', 'refus', 'erreurs', 'habilitations'].every(k => typeof data.indicateurs?.[k] === 'number' && Number.isFinite(data.indicateurs[k]))) {
    throw new Error('Le service du journal doit être mis à jour. Faites redémarrer le serveur Django, puis cliquez sur Actualiser.');
  }
}
export function auditQuery(company: string | null, filters: Record<string, string>, page: number, bound: number) {
  const query = new URLSearchParams({ page: String(page) });
  if (company && filters.portee !== 'global') query.set('societe_id', company);
  Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); });
  if (bound) query.set('borne', String(bound));
  return query;
}
