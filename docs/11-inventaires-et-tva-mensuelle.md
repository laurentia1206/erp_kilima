# Inventaires et TVA mensuelle — 14 septembre 2026

## Décisions de Laurent

- Un comptage doit être préparé puis validé par un comptable ou le DFI avant
  l’ajustement du stock et la génération de la pièce comptable.
- Toutes les sociétés relèvent de la RDC et sont assujetties à la TVA. Les
  articles peuvent être exonérés ou relever de taux différents.
- Les Ressources humaines seront traitées après ces deux points ; aucun module
  RH ni aucune règle de paie n’a été ajouté dans cette livraison.

## Inventaires

Le module existait dans « Dépôts & transferts ». Son ancienne validation faisait
immédiatement les mouvements de stock et l’écriture d’écart. Il est désormais
accessible directement dans **Stock → Inventaires & écarts**, avec filtre par
mois et dépôt, consultation du comptage, impression et suivi de la pièce.

1. Le compteur renseigne les quantités réelles. Un champ vide ne vaut jamais
   zéro ; tous les articles affichés doivent être renseignés. Il peut ajouter
   un article trouvé physiquement alors que son solde théorique est nul.
2. L’enregistrement crée un **brouillon**, avec les quantités théoriques, réelles,
   écarts et coûts observés. Aucun mouvement ni écriture à ce stade.
3. Un utilisateur disposant du rôle COMPTABLE ou DFI dans cette société consulte
   les écarts et valide. Le contrôle refuse un stock ou un coût modifié depuis
   le comptage. Dans ce cas, annuler le brouillon et refaire le comptage.
4. La validation ajuste les articles comptés et génère une pièce équilibrée
   selon les comptes d’écarts déjà configurés (par défaut 658 / 758 contre le
   compte de stock). La pièce conserve le circuit existant : elle peut être
   « en_attente » de validation comptable. L’écran distingue cette situation de
   la validation de l’inventaire lui-même.

Une seconde validation du même inventaire est refusée. Une erreur comptable
annule toute la transaction, y compris les mouvements de stock. Un brouillon
peut être annulé par son créateur ou par le comptable/DFI. Il est conservé dans
l’historique, sans effet sur les quantités.

Les inventaires historiques sont conservés comme **validés** par la migration
0014. Le module ne les rejoue pas et ne génère aucune écriture rétroactive.
Un inventaire porte sur ses articles effectivement comptés. Il ne constitue
pas automatiquement un inventaire exhaustif de tous les articles du catalogue.
Les comptages sont datés du jour : aucune reconstruction rétroactive des stocks
de fin de mois n’est simulée.

### Cuisine

Les recettes, coûts par portion et consommations théoriques existent déjà.
Il faut générer les consommations de la période avant le comptage physique.
Le tableau de cuisine présente maintenant, séparément, les manquants et les
excédents des inventaires validés du mois dans le dépôt cuisine actuellement
configuré, avec un accès direct aux inventaires. Les ratios de coût restent
explicitement théoriques. Un inventaire partiel, ou un changement de dépôt
cuisine, ne doit pas être présenté comme un coût réel exhaustif de la période.

## Déclarations TVA

Le nouveau menu **Comptabilité → Déclarations TVA** ouvre un dossier par société
et mois. Il fournit :

- les mouvements nets des comptes de TVA collectée et déductible configurés,
  avec leurs subdivisions ; seuls les mouvements d’écritures validées entrent
  dans les indicateurs ; les pièces non validées sont affichées séparément ;
- les lignes comptables permettant de retrouver les pièces et références ;
- une ventilation des factures commerciales et frais selon les taux enregistrés
  sur leurs lignes, avec déduction des avoirs ; aucun recalcul uniforme à 16 % ;
- des notes de contrôle, le crédit antérieur vérifié en CDF, le montant déclaré
  à payer en CDF, et la référence/date d’un dépôt déjà effectué ;
- l’enregistrement du dernier état préparatoire et de ses notes, une version
  empêchant deux utilisateurs de s’écraser mutuellement, l’impression de l’état
  courant ou enregistré et l’export CSV des lignes comptables.

Ce dossier constitue une **préparation et un suivi**, pas une télédéclaration
automatique à la DGI. Les montants CDF sont saisis par le comptable après
vérification ; ils ne sont pas calculés avec un taux de change mensuel inventé.
Le solde des comptes TVA n’est pas présenté comme un montant fiscal à payer.
La sauvegarde ne génère ni écriture de liquidation de TVA ni paiement.

La ventilation par taux couvre les factures commerciales et leurs frais.
Les écritures d’autres modules ou régularisations restent visibles dans le
détail comptable mais ne sont pas artificiellement ventilées à un taux supposé.
Le modèle historique ne mémorise pas le motif juridique d’une exonération sur
chaque ligne de facture : une ligne à 0 % est donc signalée « sans TVA — à
qualifier ». La qualification fiscale, les justificatifs de déduction et le
remplissage du formulaire officiel restent nécessaires.

Références officielles consultées : [formulaires de déclarations sécurisées de
la DGI](https://desec.dgi.gouv.cd/), [communiqué relatif aux déclarations de
janvier 2026](https://dgi.gouv.cd/wp-content/uploads/2026/02/Communique%CC%81-du-15-fe%CC%81vrier-2026.pdf)
et [communiqué sur les justificatifs de TVA et la facture
normalisée](https://dgi.gouv.cd/wp-content/uploads/2025/12/COMMUNIQUE-OFFICIEL-05-MODALITES-PRATIQUES-RELATIVES-A-LEFFECTIVITE-DE-LOBLIGATION-DEXIGENCE-ET-DE-.pdf).

## Vérifications et mise à disposition

- **56 tests Django réussis**, dont 11 tests ajoutés pour cette livraison :
  séparation comptage/validation, droits, manquants/excédents, double validation,
  stock devenu périmé, annulation, rollback en cas de panne comptable, cuisine,
  périmètre société/mois, taux multiples et avoirs, sauvegarde concurrente TVA.
- **10 tests JavaScript réussis** ; scripts vérifiés et migrations synchronisées.
- Recette navigateur sur une copie isolée : comptage fictif 10 → 8, écart de
  20 USD, brouillon puis validation, pièce en attente visible ; préparation TVA
  juillet 2026, sauvegarde et relecture des notes et du crédit antérieur.
- Migration appliquée à la copie de test utilisateur après sauvegarde dans
  `.build/qa/avant_migration_clotures.db`. Les données fictives restent dans
  `.build/qa/clotures_ui.db`, séparément de `.build/qa/kilima_qa.db`.
- L’empreinte de la base originale `backend/kilima_dev.db` reste inchangée.

Les réserves de mise en production des documents précédents continuent à
s’appliquer. Les exports comptables ne constituent pas une certification de
conformité du formulaire fiscal officiel et la recette mobile complète reste
à réaliser.
