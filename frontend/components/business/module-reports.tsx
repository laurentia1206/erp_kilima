'use client';
import { ScreenTitle } from './screen-presentation';
import type { ScreenProps } from './shared';

/* Un menu « Rapports » par module : la page regroupe les rapports et états
   du module et mène à l'écran qui les génère (PDF / Excel sur place). */
interface ReportCard { view: string; icon: string; title: string; desc: string }
const HUBS: Record<string, { intro: string; cards: ReportCard[] }> = {
  'rapports-tresorerie': {
    intro: 'Les journaux et rapports de trésorerie de la société active.',
    cards: [
      { view: 'caisse', icon: 'ti-book-2', title: 'Journal de caisse & rapport Z', desc: 'Les mouvements de chaque caisse, bons imprimables et rapport Z à la clôture de session.' },
      { view: 'transferts', icon: 'ti-arrows-exchange', title: 'Transferts de trésorerie', desc: 'Historique des transferts entre caisses et comptes bancaires — double validation.' },
      { view: 'avances', icon: 'ti-cash', title: 'Avances à justifier', desc: 'Suivi des avances décaissées, justification et retards.' }],
  },
  'rapports-stock': {
    intro: 'Les états de stock et les comptages, regroupés.',
    cards: [
      { view: 'stock', icon: 'ti-packages', title: 'État du stock & valorisation', desc: 'Quantités disponibles et valeur au coût moyen pondéré. Export PDF / Excel.' },
      { view: 'inventaires', icon: 'ti-clipboard-check', title: 'Inventaires & écarts', desc: 'Comptages physiques par dépôt : théorique vs réel, écarts valorisés et ajustements.' },
      { view: 'rapports-commercial', icon: 'ti-history', title: 'Historique des entrées', desc: 'Toutes les entrées en stock : achats, transferts, inventaires et autres origines.' }],
  },
  'rapports-transport': {
    intro: 'Les rapports d’exploitation du transport.',
    cards: [
      { view: 'courses', icon: 'ti-steering-wheel', title: 'Rentabilité du transport', desc: 'Le rapport de rentabilité se génère depuis les fiches de course (PDF / Excel).' },
      { view: 'carburant', icon: 'ti-gas-station', title: 'Suivi carburant', desc: 'Consommation réelle vs théorique et coût au kilomètre.' },
      { view: 'flotte-documents', icon: 'ti-license', title: 'Documents & échéances', desc: 'Assurances, contrôles techniques, permis — alertes avant expiration.' }],
  },
  'rapports-hotel': {
    intro: 'Les rapports de l’hébergement et de la restauration.',
    cards: [
      { view: 'hotel-chambres', icon: 'ti-door', title: 'État des chambres', desc: 'Occupation, ménage et disponibilité du parc. Export PDF / Excel.' },
      { view: 'cuisine', icon: 'ti-chef-hat', title: 'Rapport cuisine & food cost', desc: 'Consommation théorique journalière, ratio coût / chiffre d’affaires et bons de consommation.' },
      { view: 'inventaires', icon: 'ti-clipboard-check', title: 'Inventaires de dépôt', desc: 'Bar et cuisine : comptages, écarts valorisés et suivi des ajustements.' }],
  },
  'rapports-maintenance': {
    intro: 'Les rapports du parc et des interventions.',
    cards: [
      { view: 'maintenance-interventions', icon: 'ti-tool', title: 'Interventions & bons de pièces', desc: 'Historique des pannes et entretiens, bons de consommation de pièces imprimables.' },
      { view: 'flotte-documents', icon: 'ti-license', title: 'Documents & échéances', desc: 'Assurances, contrôles techniques, permis — alertes avant expiration.' }],
  },
  'rapports-rh': {
    intro: 'Les états et documents du personnel.',
    cards: [
      { view: 'rh-mensuel', icon: 'ti-calendar-dollar', title: 'État de paie & bulletins', desc: 'État mensuel, bulletins de paie et préparation des déclarations sociales et fiscales.' },
      { view: 'rh', icon: 'ti-users-group', title: 'Dossiers agents', desc: 'Le dossier individuel de chaque agent s’imprime depuis sa fiche.' },
      { view: 'rh-finances', icon: 'ti-file-check', title: 'Avances & prêts', desc: 'Dossiers d’avances et de prêts, mensualités et versements.' }],
  },
  'rapports-compta': {
    intro: 'Les états comptables et fiscaux, regroupés au même endroit.',
    cards: [
      { view: 'balance', icon: 'ti-scale', title: 'Balance générale', desc: 'Soldes par compte — SYSCOHADA (exercice N / N-1). Export PDF / Excel.' },
      { view: 'grand-livre', icon: 'ti-list-details', title: 'Grand livre', desc: 'Le détail des mouvements par compte, filtrable et exportable.' },
      { view: 'etats', icon: 'ti-report-money', title: 'États financiers OHADA', desc: 'Compte de résultat et bilan — SYSCOHADA révisé.' },
      { view: 'analytique', icon: 'ti-chart-pie', title: 'Comptabilité analytique', desc: 'Charges et produits ventilés par centre / activité.' },
      { view: 'tva', icon: 'ti-receipt-tax', title: 'Déclarations TVA', desc: 'Dossier mensuel par société : préparation, états courant et enregistré.' }],
  },
};
export function ModuleReports({ bridge, state }: ScreenProps) {
  const hub = HUBS[state.view];
  if (!hub) return null;
  return <>
    <div className="audit-head"><div><ScreenTitle>Rapports du module</ScreenTitle><p className="muted">{hub.intro}</p></div></div>
    <div className="room-grid">{hub.cards.map(card => <article className="room-card" key={card.view + card.title}>
      <div className="room-head"><i className={`ti ${card.icon}`} aria-hidden="true" /><b>{card.title}</b></div>
      <p className="muted">{card.desc}</p>
      <div className="room-actions"><button className="btn btn-sm btn-primary" onClick={() => bridge.navigate(card.view)}><i className="ti ti-external-link" aria-hidden="true" /> Ouvrir</button></div>
    </article>)}</div>
    <p className="muted">Chaque rapport s’imprime ou s’exporte (PDF / Excel) depuis l’écran ouvert, avec ses filtres.</p>
  </>;
}
