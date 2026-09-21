export interface User { id: string; nom: string; prenom?: string; email: string; super_administrateur: boolean; changer_mot_de_passe?: boolean }
export interface Company { id: string; nom: string; roles: string[] }
export interface MenuItem { view: string; label: string; icon: string; badge?: string }
export interface MenuGroup { name: string; items: MenuItem[] }
export interface Snapshot { user: User | null; companies: Company[]; companyId: string | null; view: string; title: string; subtitle: string; groups: MenuGroup[]; preferredGroup?: string; navigated?: boolean }
export interface Bridge {
  clearTask(): void;
  snapshot(): Snapshot;
  start(): Promise<void>;
  restore(): Promise<void>;
  login(email: string, password: string): Promise<void>;
  logout(): void;
  changePassword(oldPassword: string, newPassword: string): Promise<void>;
  navigate(view: string, group?: string): Promise<void>;
  selectCompany(id: string): Promise<void>;
  api<T = unknown>(path: string, options?: { method?: string; body?: unknown; form?: boolean }): Promise<T>;
  download(path: string, filename: string, body?: unknown): Promise<void>;
  holdNavigation(): () => void;
  openTask(view: string, type: string, documentId: string): Promise<void>;
  closeModal(): void;
  refreshAccountingBadge(): Promise<void>;
}
declare global {
  interface Window {
    KilimaNext?: { publish: (extra?: object) => void; initialView: () => string | null; owns?: (view: string) => boolean; canLeave?: () => boolean };
    KilimaERP?: Bridge;
    kilimaLoading?: Promise<Bridge>;
  }
}

const scripts = ['editions', 'navigation', 'workspace', 'module-ux', 'catalogue', 'clotures', 'rh', 'rh-paie', 'rh-finances', 'rh-mensuel', 'pilotage', 'audit', 'systeme', 'app', 'next-adapter'];
export function loadRuntime(): Promise<Bridge> {
  // Un seul chargement, y compris avec le double effet de React Strict Mode.
  if (window.kilimaLoading) return window.kilimaLoading;
  window.KilimaNext = { publish: () => {}, initialView: () => null, owns: view => ['accueil', 'pilotage', 'audit', 'stock', 'taux', 'articles', 'hotel-chambres', 'depots', 'inventaires', 'hotel-reception', 'cuisine', 'balance', 'grand-livre', 'saisie-od', 'plan-comptable', 'lettrage', 'rapprochement', 'cockpit', 'etats', 'analytique', 'tva', 'compta', 'rapports-commercial', 'dashboard', 'config-hotel', 'config-engins', 'config-transport', 'config-maintenance', 'contrats-transport', 'flotte-documents', 'engins-rpe', 'flotte', 'engins-parc', 'engins-heures', 'maintenance-parc', 'maintenance-interventions', 'carburant', 'tarifs-pos', 'transferts', 'caisse-exec', 'intersociete', 'nouvelle-req', 'requisitions', 'approbation', 'ordres', 'avances', 'caisse', 'courses', 'config', 'administration', 'systeme', 'rh', 'rh-simulateur', 'rh-decomptes', 'rh-finances', 'rh-paiements', 'rh-mensuel', 'achats', 'ventes', 'commandes', 'receptions', 'devis', 'pos'].includes(view) };
  window.kilimaLoading = (async () => {
    for (const name of scripts) {
      await new Promise<void>((resolve, reject) => {
        const script = document.createElement('script');
        script.src = `/legacy/${name}.js?v=next-2`;
        script.async = false;
        script.onload = () => resolve();
        script.onerror = () => reject(new Error('Un module n’a pas pu être chargé. Rechargez la page.'));
        document.body.appendChild(script);
      });
    }
    if (!window.KilimaERP) throw new Error('L’espace de travail n’a pas pu démarrer.');
    // Une session expirée ramène à la connexion et ne bloque pas le formulaire.
    await window.KilimaERP.start().catch(() => {});
    return window.KilimaERP;
  })();
  return window.kilimaLoading;
}
