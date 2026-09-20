# Ressources humaines — recherche et décisions

Travail en cours, 14–15 septembre 2026. Cette note distingue les fonctions déjà codées des prochains travaux ; elle ne certifie pas une paie ni un dépôt fiscal.

## Décisions de Laurent

- Aucune convention collective actuellement fournie.
- Salaires contractuels nets. USD/CDF disponibles par contrat ; définition précise des composantes régulières à confirmer sur les contrats signés.
- RH prépare, DFI valide, caisse paie. Aucune opération financière directe sans validation.
- Pointages manuels par les RH ou responsables de leurs équipes ; intégration du dispositif électronique ultérieure.
- Sociétés ayant leurs propres horaires, primes et KPI. Le travail de nuit reste soumis aux prescriptions légales même si les pratiques internes ne distinguent pas encore la rémunération.
- Avances à justifier : examen pour recouvrement sur salaire après 30 jours depuis l’octroi, accord écrit, validations DFI puis DRH puis DG ou Administrateur. Le délai ne déclenche pas une retenue automatique et ne constitue pas une sanction.
- Avance sur salaire : plafond configurable par société (30 % proposé par défaut). Les demandes cumulées du mois dépassant le plafond sont des prêts au personnel avec accord et échéancier, soumis aux trois niveaux.
- Les plafonds d’octroi et les quotités de retenue légalement permises sont distincts.
- Le décompte final fait partie du périmètre, rappel explicite du 15 septembre.
- Précision du 15 septembre : un simulateur d’engagement sert à essayer brut, logement, transport et primes pour atteindre le net convenu, puis les composantes retenues sont reprises explicitement dans le contrat. Ne pas imposer un calcul inverse automatique comme seul mode de travail.
- Pas de pourcentage arbitraire de sous-déclaration. Les exclusions légalement admises doivent découler de la nature réelle des rémunérations et de justificatifs.

## Comparaison fonctionnelle

Sources consultées :

- [Odoo — Employés](https://www.odoo.com/documentation/18.0/applications/hr/employees.html) : dossiers, contrats, départements, parcours et documents.
- [Odoo — Présences](https://www.odoo.com/documentation/19.0/applications/hr/attendances.html) : saisie, contrôle des présences, responsables limités aux agents qui leur sont attribués.
- [Frappe HR — structures salariales](https://docs.frappe.io/hr/salary-structure) et [paie](https://docs.frappe.io/hr/payroll-setup) : rubriques, structures affectées aux agents, préparation par période.
- [Frappe HR — congés en paie](https://docs.frappe.io/hr/leave-management/help-articles/leave-calculation-in-salary-slip) : articulation entre absences, congés et jours rémunérés.

Choix retenus : dossier unique par employeur/matricule, lien explicite au compte agent et éventuellement au compte de connexion ; aucun rapprochement financier par simple similitude de nom. Un chef d’équipe voit le temps de son équipe, pas les contrats, salaires ou pièces disciplinaires.

## Textes vérifiés

| Sujet | Texte / source | Conséquence et limites |
|---|---|---|
| Durée du travail | [Loi 16/010 du 15 juillet 2016, DGRAD](https://dgrad.gouv.cd/wp-content/uploads/2022/01/Loi-16-010-du-15-juillet-2016-modifiant-et-completant-Loi-015-2002-Code-du-Travail.pdf), art.119 et 121 | 8 h/jour, 45 h/semaine, au moins 24 h de repos hebdomadaire. Examiner les dérogations et heures supplémentaires. |
| Nuit | [Code du travail et arrêté 68/14, document hébergé par CNSS](https://cnss.cd/wp-content/uploads/2020/12/Les-Codes-Larcier-t.IV-Droit-du-Travail-et-de-la-Securite-sociale.pdf), art.124 et arrêté p.98 du PDF | Nuit 19 h–5 h ; arrêté 68/14 art.5 mentionne l’hôtellerie parmi les établissements fonctionnant jour et nuit, majoration 25 %. Art.4 10 % pour emplois exclusivement nocturnes, art.6 30 % autres cas ; vérifier qualification exacte. Ne pas confondre avec le régime protecteur art.125 modifié (18 h–6 h). |
| Retenues | Même compilation, art.111–114 p.31 du PDF | Pas d’amendes ni de réductions à titre de dommages-intérêts décidées librement. Prêts/avances autorisés sous conditions ; art.114 : 1/5 jusqu’à cinq fois le minimum mensuel de catégorie, 1/3 au-delà ; assiette après retenues fiscales/sociales et logement forfaitaire. Ne pas substituer le plafond d’avance à cette protection. |
| Départ | Même compilation, art.64, 66, 69, 70, 100, 103–104 | Préavis selon contrat, catégorie et cause ; salaire restant à payer rapidement ; un reçu de solde n’emporte pas renonciation aux droits. Le module ne prend pas de décision de licenciement. Vérifier arrêté 70/0015 avant automation des catégories. |
| SMIG 2026 | [Décret 25/22 du 30 mai 2025](https://www.annuairetravail-rdc.cd/detail?slug=decret-n-25-22-du-30-mai-2025-portant-fixation-du-salaire-minimum-interprofessionnel-garanti-des-allocations-familiales-minima-et-de-la-contre--valeur-du-logement), art.2–7 | Manœuvre ordinaire : 21 500 CDF/jour à partir de janvier 2026 ; tension par catégorie ; conversion mensuelle ×26. Allocations familiales minimales par enfant : journalier SMIG ordinaire /27. |
| IRPP 2026 | [DGI, loi 23/053 du 30 novembre 2023](https://dgi.gouv.cd/wp-content/uploads/2025/09/loi-is-et-Irpp.pdf), pages PDF27–29, 38–40 examinées visuellement | Art.68 revenus et primes ; art.69 immunités documentées ; art.70–71 retenues admises ; art.118 barème progressif annuel et plafond 30 %, arrondi du revenu annuel au millier inférieur ; art.123–125 charges de famille selon conditions. |
| Retenue mensuelle IRPP | [Arrêté 011 du 19 février 2025, copie ONEC](https://www.onecrdc.com/wp-content/uploads/Arretes-ministeriels/AM-011-modal-perc-et-revers-retenue-IRPP-dans-la-categ-rev-sal-et-rev-assim.pdf), 2 pages examinées visuellement | En vigueur au 1er janvier 2026. Calcul mensuel selon art.118, retenue au paiement ou mise à disposition, reversement au plus tard le 15 du mois suivant. La période déclarative ne peut être choisie uniquement d’après le mois du bulletin sans examiner sa mise à disposition. |
| CNSS | [CNSS, taux](https://cnss.cd/?page_id=1388) et [recueil officiel](https://cnss.cd/wp-content/uploads/2024/04/Recueil-de-textes-legal-reglementaires-et-mesures-dexecution-de-la-loi-16-009-du-15-juillet-2016-1.pdf), art.17 p.123 examinée visuellement | 5 % salarié, 13 % employeur. Pour le salarié : salaire et primes inclus ; véritables indemnités logement/transport exclues. L'assiette sociale diffère de l'assiette fiscale ; le dépassement fiscal du logement n'est pas automatiquement une assiette CNSS. Les assimilés ont leur régime distinct. |
| ONEM | [ONEM — contribution](https://www.app.onem.cd/employeurs/contribution-patronale) | 0,5 %, modification de septembre 2025 ; échéances déclaratives/paiement distinctes. |
| INPP | [Annonce Sage](https://communityhub.sage.com/za/sage-payroll-professional/f/announcements/263505/democratic-republic-of-congo-drc-increase-in-national-institute-of-professional-preparation-inpp-contribution-rates) ; arrêté interministériel 002/MET,158/FINANCES,003/BUD du 24 septembre 2025 repéré | Annonce d’application janvier 2026 : privé 1–50 salariés 3,5 %,51–300 3 %,>300 2 %, public 4 %. Original intégral pas encore vérifié ; ne pas présenter l’ancien 3/2/1 % comme actuel. |

Le document CNSS est une compilation de 2003 : pour chaque disposition modifiée, la loi de 2016 prime. Les régimes et barèmes doivent être datés. Un fichier de paie existant n’établit pas à lui seul la conformité d’un traitement fiscal.

## Analyse du classeur fourni — sans modification ni import de personnes

Fichier : `Payroll - Master-PLANET DRC-04_26-ok.xlsx`, période SETTINGS!C8 = avril 2026. Lecture des formules et valeurs enregistrées, pas de recalcul Excel exécuté. Les avertissements de lecture concernant des extensions ne concernent aucun enregistrement du fichier : l’original n’a pas été réécrit.

18 feuilles : paramètres, simulation, liste agents, présences, heures supplémentaires, avances, paie, synthèses, bulletins et déclarations, SMIG et barème. Sept lignes de paie actives, dont une catégorie « Associés Actifs » et six « Nationaux Imposables ». Ne pas importer les identités/rémunérations réelles dans la base de démonstration sans demande.

Rubriques réutilisables : salaire de base, ancienneté, logement, transport, primes/commissions, heures supplémentaires, maladie, absences, rappels, cotisations salarié/employeur, avances et autres dettes, net, bulletin individuel. Les particularités des mandataires/associés actifs nécessitent un régime explicitement qualifié ; ne pas les assimiler automatiquement à tous les salariés.

Points constatés :

- SETTINGS!C13 et C21 contiennent des taux de conversion distinctement paramétrables. Conserver la source et la date des conversions.
- SETTINGS!C18 emploie l’ancien INPP 3/2/1 %. SETTINGS!C19 vaut 0,5 % ONEM, mais SIMUL. SAL!D40 applique encore 0,2 %.
- SMIG!B11:R11 contient le barème 2026, tandis que des recherches de MAST.LIST pointent sur la ligne 8 (ancien barème) et un classeur externe. Seize formules utilisent une liaison `[1]`.
- PAYROLL!I9 prorate déjà la base par G9/26 ; K9 applique de nouveau G9/26 sur I9 pour le logement. Pour un demi-mois, cela ramène le logement à un quart du montant mensuel.
- Le test initial du calcul fiscal en AQ10:AQ15 utilise des références mobiles H4,H5,H6,… du barème, contrairement aux autres références absolues. Risque de résultat erroné à certaines tranches.
- MAST.LIST!P6 et lignes suivantes utilisent TODAY() pour l’ancienneté. Une paie ancienne doit utiliser une date de référence figée.
- SIMUL. SAL!N21 utilise MIN(revenu,M21), alors que M21 est vide : quatrième tranche à vérifier ; les débuts 162001 et 1800001 créent aussi une différence d’une unité sur les limites.
- PAYROLL!BD (prime spéciale) et AA alimentent le net BC hors de la base fiscale AL dans les formules observées. Qualifier leur nature légale avant de reprendre ce traitement.
- SETTINGS!C23 est le taux de déclaration (valeur enregistrée 1). Les formules de déclarations l’utilisent. Ce multiplicateur arbitraire ne sera pas reproduit dans les déclarations du logiciel.
- Les absences laissées vides dans ATTD sont assimilées à des présences. Le nouveau pointage distingue explicitement « non renseigné » de présent/absent.

## État du développement

Codé et tests initiaux : dossiers agents, contrats sans chevauchement, événements, documents privés avec détection de copies identiques, horaires par société, pointages avec pause et franchissement de minuit, validation/réouverture motivée ; registre des demandes de congés/avances. Neuf tests initiaux passent.

Livré sur la page locale le 15 septembre : simulateur d’engagement, variantes conservées par société, comparaison au net visé, détail des assiettes/tranches et reprise explicite des composantes au contrat. La date et les hypothèses restent figées. Le calcul utilise le régime salarié général 2026, les seules indemnités réellement qualifiées et un coût de trajet documenté. Le net précède les dettes. Les charges INPP/ONEM ne sont pas incluses dans le coût partiel affiché (mention explicite).

Accords de recouvrement/prêt : plafond cumulé mensuel, accord écrit au dossier, échéancier totalisé, DFI puis DRH puis DG/Administrateur pour prêt/recouvrement ; personnes distinctes. Versement des avances/prêts par un caissier distinct, avec session ouverte, solde suffisant, bénéficiaire financier unique, reçu et écriture équilibrée. Le versement est atomique et ne peut être répété. Aucun nouveau décaissement pour le recouvrement d’une avance à justifier. Les mensualités ne sont pas encore prélevées sur une paie.

Décompte final : première étape disponible, préparation et aperçu imprimable des droits bruts. Le préparateur renseigne les références des congés, de la moyenne des variables et du préavis ; le logiciel calcule et conserve le détail. Art.140–145 et arrêté 70/0015 examinés : congés compensés à la rupture, moyenne des variables, préavis distinct selon catégorie. La préparation ne décide pas du départ, ne modifie pas le contrat et ne déduit aucune dette. Le calcul du net final et sa validation pour paiement restent à réaliser.

Validation : 77 tests Django et 10 tests JavaScript existants passent. Vérification dans le navigateur sur une copie indépendante : simulation fictive (1 000 brut + 100 primes + 300 logement + 50 transport, change 2 300), net obtenu 1 207,34 USD ; sauvegarde et reprise au contrat ; droits bruts fictifs de départ 4 780 USD ; prêt de 500 USD passant de DFI à DRH. Aucune donnée du classeur réel importée et aucun paiement réel effectué. Aperçus vérifiés dans le navigateur ; dialogue système d’impression non contrôlé.

Migrations 0015–0019 appliquées à `.build/qa/kilima_qa.db` après sauvegarde `avant_rh_20260915_004630.db`. Les essais fictifs restent uniquement dans `.build/qa/rh_ui_validation.db`. Base historique `backend/kilima_dev.db` vérifiée inchangée par empreinte SHA-256. Aucune attribution automatique de rôle aux utilisateurs existants.

À réaliser : paie mensuelle définitive et régularisations garantissant le net contractuel, congés/droits et calendriers, KPI/primes, remboursements avec contrôle des quotités et rapprochement des avances ensuite justifiées, net du décompte final et validations de départ, états mensuels IPR/IRPP/CNSS/ONEM/INPP avec suivi du dépôt. Aucun bulletin définitif ni déclaration officiellement déposée à ce stade. Original INPP 2025 et règles d'application de l'annualisation/arrondi mensuel à corroborer avant activation de la paie définitive.


## Livraison complémentaire : paie mensuelle

Le 15 septembre 2026, ajout du cycle mensuel par société : préparation, contrôle RH, validation DFI distincte, comptabilisation, règlement caisse ou virement confirmé et clôture. Maintien du net contractuel proratisé, variables documentées, remboursement des avances et prêts versés selon accord/échéance/quotité, solde suivi. Migration 0020 appliquée après sauvegarde de la base de test habituelle. Le descriptif de développement ci-dessus constitue l’état antérieur ; voir `13-paie-mensuelle-mode-emploi.md` pour le périmètre livré, les vérifications (87 tests Django, 10 JavaScript) et les limites actuelles.

Les recouvrements d’avances à justifier sur paie attendent la confirmation du circuit de rapprochement DFI ; le circuit existant n’est pas modifié. Les états sociaux/fiscaux sont préparatoires, sans dépôt. Le net du décompte final, les régularisations et les congés automatiques restent à réaliser. Les vérifications réglementaires IRPP/INPP indiquées plus haut restent nécessaires avant usage réel.
