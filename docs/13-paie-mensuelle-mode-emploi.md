# Paie mensuelle — version de test du 15 septembre 2026

Accès : **Ressources humaines → Paie mensuelle**, sur la société active.

## Préparer le mois

Les RH, le DRH ou le DFI ouvrent un mois, renseignent le taux CDF/USD et sa référence, l’effectif total, le secteur de l’employeur, les heures normales mensuelles et les références fiscales/sociales examinées. Les paramètres restent corrigibles en préparation ; après correction, les bulletins doivent être recalculés.

Chaque agent doit avoir un contrat net applicable, une composition issue du simulateur et un lien vers son bénéficiaire financier. Un ancien contrat sans composition peut recevoir explicitement une simulation conservée donnant exactement le même net, sans modifier le salaire contractuel. Les transitions entre plusieurs contrats dans un même mois demandent un traitement particulier et sont bloquées dans cette version.

Préparer chaque bulletin : jours rémunérés sur base 26, catégorie SMIG, rapprochement des présences/congés/absences, primes variables, heures supplémentaires et régime du travail de nuit. Les heures normales mensuelles sont paramétrables pour adapter le taux horaire. Les heures de nuit déjà pointées ne peuvent pas être ignorées sans qualification documentée d’une exclusion légale. Un jour sans pointage n’est jamais une absence automatique.

Le calcul prorate les composantes régulières et ajuste le brut du mois afin de maintenir le net contractuel proratisé avant variables et dettes. L’ajustement est visible et ne modifie pas le contrat. Les variables approuvées sont ajoutées ensuite. Le contrat et les sources du mois sont conservés avec le bulletin.

## Contrôler, valider, payer

1. **RH/DRH : terminer le contrôle.** Les pointages existants doivent être validés. Chaque agent éligible non préparé doit être exclu avec un motif individuel. Les droits à congés ne sont pas encore calculés automatiquement : le rapprochement humain reste nécessaire.
2. **DFI distinct du contrôleur : valider.** Il confirme le rapprochement réglementaire, fige les bulletins et crée les écritures équilibrées : rémunérations/charges, dettes sociales et fiscales, net dû et remboursements autorisés. Un changement de dossier ou de pointage intervenu depuis le calcul impose une réouverture et un recalcul avant validation.
3. **Caissier : versement en espèces**, session ouverte et solde suffisant dans la devise. **Caissier ou comptable : enregistrement d’un virement bancaire déjà confirmé**, compte de la société dans la même devise, référence obligatoire. Le logiciel n’envoie aucun virement bancaire. L’exécutant est distinct du contrôleur et du validateur ; il ne peut pas se payer lui-même.
4. **DFI : clôturer** lorsque tous les nets ont été réglés. Paiement intégral par bulletin dans cette version, sans paiements partiels. Les paiements répétés sont refusés. Les écarts de change sont comptabilisés et le compte 422 est apuré à son cours historique.

La préparation peut être corrigée. Le contrôle peut être rouvert avec un motif avant validation DFI. Aucune annulation d’écriture ni régularisation d’un mois validé n’est implémentée ici ; ne valider une paie réelle qu’après rapprochement complet.

## Prêts, avances et documents

Les avances sur salaire et prêts réellement versés peuvent être retenus, sur sélection explicite, selon l’échéance signée et le solde. Le plafond légal de retenue est distinct du plafond d’octroi de l’avance. Les remboursements validés et le solde apparaissent dans **Avances & prêts**. Une échéance non prélevée n’est pas reportée automatiquement.

Les recouvrements d’avances à justifier restent bloqués sur bulletin en attendant la décision de l’utilisateur sur le rapprochement DFI lorsqu’une avance retenue est ensuite présentée à justification. Le circuit existant de justification n’a pas été modifié.

Impressions : bulletin individuel, état du mois, préparation des bases et montants CNSS/IRPP/INPP/ONEM en CDF. La préparation des déclarations est un état de rapprochement ; elle n’est pas un formulaire officiel, un dépôt ou une preuve de paiement aux organismes. Les mois de service et de versement doivent être distingués. Aucun coefficient de minoration arbitraire n’est proposé.

## Références et limites réglementaires

Voir `12-rh-recherche-et-decisions.md` pour les textes consultés. Régime général salarié 2026 uniquement ; associés actifs et autres régimes particuliers exclus. Les indemnités de logement et transport doivent être réelles et documentées. Le SMIG utilisé est celui de 2026, selon la catégorie sélectionnée.

La méthode d’annualisation/arrondi IRPP mensuel et le texte original INPP du 24 septembre 2025 restent à corroborer avec les références de l’entreprise avant usage réel. Les taux INPP affichés s’appuient notamment sur l’annonce Sage de janvier 2026 ; ils ne constituent pas à eux seuls une certification juridique. Le DFI doit confirmer les assiettes et barèmes avant comptabilisation. Le dépôt des déclarations et les éventuelles régularisations ne sont pas automatisés.

Le décompte final conserve sa préparation des droits bruts ; son net définitif et son circuit de paiement ne font pas encore partie de cette livraison.

## Vérifications de livraison

87 tests Django et 10 tests JavaScript passent. Ils couvrent notamment séparation des rôles, cloisonnement société, maintien du net, proratisation, variables, pointages modifiés, échéances et quotités, double paiement, trésorerie insuffisante, rollback comptable, règlement bancaire CDF et apurement du compte 422.

Sur une copie indépendante : ouverture du mois dans le navigateur, bulletin fictif à 603,67 USD pour 13 jours sur un net mensuel de 1 207,34 USD, aperçu imprimable et contrôle RH vérifiés. La reprise du navigateur pour les dernières étapes a été empêchée par l’expiration du contrôle automatique d’autorisation. Validation/paiement/clôture vérifiés par les tests serveur, pas intégralement dans le navigateur. Aucun paiement réel ni import du classeur nominatif.

Migration 0020 appliquée à la base de test habituelle après sauvegarde `avant_paie_mensuelle_20260915_103526.db`. Les comptes/agents fictifs de vérification sont uniquement dans la copie `paie_ui_validation.db`. Aucun rôle supplémentaire attribué sur la base habituelle. Base historique inchangée, vérifiée par SHA-256.
