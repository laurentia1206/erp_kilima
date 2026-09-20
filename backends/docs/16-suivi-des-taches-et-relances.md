# Suivi des tâches, relances internes et supervision DFI

Version du 15 septembre 2026. Accès : **Pilotage → Suivi des tâches**.

## Fonctionnement livré

Le suivi rassemble les actions attendues sur les dossiers enregistrés de la société active. Il ne crée pas une seconde liste de tâches à tenir manuellement : la file est recalculée à partir des états métier. Une action terminée disparaît au prochain rafraîchissement.

Chaque utilisateur dispose de **Mes tâches**. Le DFI dispose aussi de **Équipe · supervision DFI**, dans les sociétés où il possède ce rôle. La société se choisit dans le sélecteur habituel. Cette version ne consolide pas les sociétés dans une seule liste.

Quatre compteurs distinguent les actions ouvertes, les remontées au DFI, les relances internes et les affectations ou circuits à clarifier. Les filtres par module, personne habilitée, priorité et texte se combinent. Les cartes de priorité servent également de filtres.

La répartition par utilisateur indique ses actions accessibles et alertes. Une tâche partagée figure dans plusieurs files individuelles : les totaux par personne ne doivent pas être additionnés comme des dossiers uniques. Le total d’actions peut également différer du total de dossiers lorsqu’il existe plusieurs validations conjointes.

**Examiner** explique l’action, les intervenants, la date retenue, les délais, l’échéance métier et l’étape qui attend ensuite. Un bouton ouvre le module concerné ; les réquisitions disposent également d’une ouverture de leur détail. Les validations et paiements continuent de se faire dans leur module, avec leurs contrôles existants.

## Responsabilités

- Une demande de précisions attend son initiateur.
- Une avance à justifier attend le bénéficiaire lié à un compte utilisateur actif dans la société.
- Une tâche de rôle attend l’équipe habilitée : le système ne désigne pas arbitrairement une personne parmi plusieurs comptables ou caissiers.
- L’absence d’utilisateur actif habilité, de circuit exploitable ou un conflit entre décisions et statut produit une alerte à clarifier.
- Les exclusions d’auto-validation sont prises en compte pour les réquisitions, les financements RH et la séparation contrôleur RH / DFI de la paie.
- Un bénéficiaire externe sans compte lié est signalé pour organiser le suivi ; cela ne signifie pas qu’un employé particulier est en faute.

Le suivi porte sur des tâches professionnelles enregistrées. Il ne mesure pas le temps de présence devant l’ordinateur et n’utilise ni surveillance de frappe, ni capture d’écran, ni classement disciplinaire.

## Délais et relances

Le fonctionnement a été approuvé par Laurent : délais réglables par société et type de tâche, relance puis remontée au DFI, sans nouveau blocage automatique.

Dans **Régler les délais**, le DFI coche les types à activer et enregistre deux durées en heures calendaires : seuil de relance et seuil de remontée au DFI. Le second doit être supérieur au premier. Les valeurs proposées 24 / 48 heures ne s’appliquent pas tant que la case n’est pas cochée et la configuration enregistrée. Les règles s’appliquent aussi aux dossiers déjà ouverts.

Aucun nouveau délai n’a été activé dans les données de test pendant le développement. La lecture de l’écran ne modifie aucun statut métier et ne déclenche aucune écriture comptable. Les modifications de délais sont auditées ; une configuration concurrente ne peut pas être écrasée silencieusement.

Les échéances métier déjà enregistrées restent prioritaires : lorsqu’une avance ou un document de flotte dépasse son échéance, il remonte au DFI même sans règle de suivi supplémentaire. Les dates sans heure sont considérées en fin de journée locale, pour éviter de déclarer une échéance journalière dépassée dès minuit.

Les dates d’entrée dans l’étape sont utilisées lorsqu’elles sont disponibles. Sinon, l’origine du calcul est explicitement affichée : création du dossier, confirmation de commande, dernière sauvegarde TVA, etc. Ces dates de repli ne constituent pas une preuve de temps perdu par une personne. Une validation partielle ne réinitialise pas les délais des autres validateurs.

Les relances livrées sont des **alertes internes persistantes tant que la tâche reste ouverte**, recalculées lorsque l’ERP est consulté. Le tableau s’actualise toutes les 30 secondes ; le compteur de la barre supérieure toutes les 2 minutes sur les autres écrans, ainsi qu’à la connexion et au changement de société. Les appels s’arrêtent lorsque l’onglet est masqué. Une panne d’actualisation est signalée.

Il n’y a pas d’envoi automatique de courriels, SMS ou notifications téléphone dans cette version, ni de journal d’envoi ou d’accusé de lecture. Leur activation nécessitera les services de messagerie/mobile et des règles de fréquence. Un utilisateur absent de l’application ne reçoit donc pas encore de relance externe.

## Couverture actuelle — 26 types d’action

| Domaine | Actions détectées |
|---|---|
| Réquisitions | Validations restantes et réponses aux demandes de précisions |
| Trésorerie | Émission d’ordres, validation des sorties, paiements restant à exécuter, avances à justifier, transferts à confirmer |
| Comptabilité | Pièces en attente et dossiers TVA sauvegardés d’un mois passé sans référence complète de dépôt |
| Stocks | Comptages préparés attendant une validation |
| Achats | Réceptions enregistrées restant à rapprocher d’une facture fournisseur |
| RH | Pointages brouillons regroupés par jour, demandes d’avance à instruire, étapes de financement et versements autorisés |
| Paie | Préparation / contrôle, validation DFI, règlements restant à effectuer, clôture après règlement |
| Transport | Fiches de course brouillons à valider et courses livrées non facturées |
| Maintenance | Interventions en cours ou planifiées arrivées à leur date ; documents entrant dans la période de vigilance déjà utilisée par le module |
| Hôtel | Arrivées et départs prévus pour aujourd’hui ou une date passée, à vérifier avec la réception |
| Ventes | Quantités facturables sur commandes confirmées hors circuit intersociétés, selon la fonction de calcul déjà utilisée pour la facturation |

Une attente fournisseur ou une prestation encore en cours doit être examinée avant de conclure à un retard imputable. Le tableau n’effectue ni facturation, ni check-in/check-out, ni clôture d’intervention à la place des utilisateurs.

## Rapports

**Rapport PDF / imprimer** produit un état de la sélection avec société, date de situation, périmètre, filtres, tâches, intervenants et étapes dépendantes. Le moteur d’édition commun apporte l’en-tête, les références société et la pagination.

**Excel** conserve tous les résultats filtrés, au-delà de la page affichée, avec dates de départ, échéances, seuils de relance, seuils de remontée et observations. Les filtres et la date de situation sont inclus dans le contexte du classeur. L’écran est paginé par 50 actions.

Un rapport décrit une situation à un instant donné ; il ne prouve ni la lecture d’une relance, ni une faute individuelle. Il n’a pas vocation à additionner la charge d’équipes partagées ou à déclencher une sanction.

## Pour détecter les travaux jamais saisis

Le système ne peut pas déduire qu’une équipe devait saisir un inventaire, une paie ou un pointage précis si aucune obligation n’a été définie. Il faudra compléter le suivi par un calendrier des obligations : société, tâche attendue, fréquence, responsable, remplaçant éventuel et preuve d’achèvement. Les horaires différents des sociétés devront être pris en compte avant toute règle fondée sur des jours ouvrés.

Les congés, les déclarations sociales, la facturation périodique des engins, les étapes intersociétés non couvertes et les opérations non enregistrées ne sont pas présentés comme intégralement contrôlés. L’absence d’alerte ne certifie donc pas que tout l’ERP est à jour. Les automatismes supplémentaires et changements de circuit restent à faire valider par Laurent.

## Vérifications

La suite Django complète compte **107 tests réussis** ; les tests de l’interface en comptent **14 réussis**. Les téléchargements Excel et PDF ont été confirmés dans le navigateur sur le serveur local mis à jour.

- Tests d’accès entre sociétés et restriction de la supervision/configuration au DFI.
- Files personnelles, équipes partagées, rôle déjà validé, utilisateur inactif et absence de circuit.
- Délais, modification concurrente des règles, échéance d’avance et absence de blocage créé à la lecture.
- Séparation des étapes de paie, exclusions de validateurs RH et absence de montant de salaire dans la file de travail.
- Quantités réellement facturables, séjour futur exclu, échéances et disparition des actions traitées.
- Nombre de requêtes stable quand le nombre de réquisitions augmente : les règles et décisions ne sont pas relues dossier par dossier.
- Vérification dans le navigateur du DFI : tableau, filtres, explication d’une affectation manquante, aperçu de rapport et téléchargements.

La base historique `backend/kilima_dev.db` est restée inchangée. Le serveur de tests utilise toujours la copie de recette. Aucune migration de schéma n’est nécessaire pour ce suivi ; les délais utilisent les paramètres existants de chaque société.
