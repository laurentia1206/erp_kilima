# Plan de portage vers Django — ERP KILIMA HOLDINGS

> Document historique du portage. Depuis le 20 septembre 2026, seul Django
> est livré dans `backend/` ; les anciens scripts et lanceurs FastAPI ont été retirés.
> Pour installer et démarrer la version actuelle, suivre `LIRE-MOI.md` à la racine.

> Décision de Laurent (2026-07-24) : l'équipe informatique maîtrise Django, pas FastAPI.
> Le backend est porté vers **Django 5 + Django REST Framework** par Claude.

## Garanties du portage

1. **API identique** : mêmes URL (`/api/...`), mêmes paramètres, mêmes réponses JSON
   → le frontend (`static/`) n'est PAS modifié.
2. **Base de données inchangée** : les modèles Django pointent sur les MÊMES tables
   (`db_table`, `managed=False` pendant la transition) → les données de test de
   Laurent restent intactes ; les deux backends sont interchangeables pendant le portage.
3. **Jetons interchangeables** : même SECRET_KEY, même payload JWT → une session
   ouverte sur l'un fonctionne sur l'autre.
4. **Tests portés** : la suite pytest (89 tests) est convertie au fur et à mesure ;
   un module n'est « terminé » que quand ses tests passent sur Django.

## Architecture cible

```
backend/
  manage.py
  kilima/            # projet (settings, urls, wsgi)
  core/              # auth JWT custom (table utilisateur existante, bcrypt),
                     # contrôle d'accès par société/rôles (portage de deps.py),
                     # modèles partagés (Societe, Role, Utilisateur, ...)
  comptabilite/      # moteur d'écritures (portage de comptabilite.py) + compta/analytique
  decaissements/     # réquisitions, ordres, avances, approbations
  caisses/           # caisses, transferts, POS… (à découper au portage)
  commercial/        # articles, tiers, achats, ventes, devis
  intersociete/      # miroirs, réceptions, traçabilité
  transport/         # flotte, courses, contrats
  administration/    # config (portage de config.py)
```
DRF en vues fonctions (`@api_view`) : mapping 1-pour-1 avec les handlers FastAPI,
lisible pour l'équipe. À la fin : `makemigrations` + `migrate --fake-initial`
pour que Django devienne propriétaire du schéma (managed=True) et que l'équipe
utilise les migrations Django natives.

## Phases (dans l'ordre, chaque phase = tests verts avant la suivante)

| # | Phase | Contenu | État |
|---|---|---|---|
| 0 | Fondation | projet, settings sur la même DB, auth JWT compatible, /api/auth/login, /api/auth/me, /api/societes | ✅ fait (preuve de parité exécutée) |
| 1 | Socle lecture + services | numérotation, paramètres, taux, audit, /api/caisses, /api/tiers, /api/comptes-bancaires, /api/ordres-depense (liste), POST /api/taux | ✅ fait (parité 6/6 + écriture croisée vérifiée ; bon-sortie reporté en phase 3 avec BonReception) |
| 2 | Moteur comptable | post_ecriture, plan comptable, balance/grand livre/lettrage/rapprochement/états, saisie OD, validation des pièces, comptes-config, analytique | ✅ fait — lectures : parité 90/90 (5 sociétés × 18 comparaisons) ; écritures : banc croisé 32/32 sur copies de base (FastAPI et Django exécutent la même séquence, réponses et état final identiques). Les `comptabiliser_*` appelés par les autres modules seront portés avec leurs appelants (phases 3+). |
| 3 | Décaissements | réquisitions → ordres → avances → justifications + approbations | ✅ fait (2026-08-07) — domain (money/workflow/avances), paliers de validation, G01→G04 complet + bon-sortie + centre d'approbation + dashboard. Lectures : 35/35 ; écritures : banc croisé 25/25 (cycle complet avance + cycle paiement direct rejoués sur copies). Au passage : bug FastAPI corrigé (import HTTPException manquant dans lecture.py → bon-sortie renvoyait 500 au lieu de 404). |
| 4 | Caisses & transferts | sessions, mouvements, billetage, rapport Z, transferts | ✅ fait (2026-08-07) — ouverture/clôture avec comptage et écart, mouvements avec billetage, opérations multi-devises atomiques (pièce 471 en attente), bons de caisse, journal société, transferts caisse↔banque à double validation avec constat d'écart (658/758) et rejet avec retour des fonds. Lectures 22/22 ; banc croisé écritures 25/25. |
| 5 | Commercial & POS | articles, tiers, achats, réceptions, POS complet | ✅ fait (2026-08-07) — articles/stock CUMP, factures achat/vente avec frais annexes (crédit/banque/caisse), commandes → réceptions partielles 3 voies → facture fournisseur, listes de prix/tarifs, points de vente, POS complet (ventes fractionnées USD/CDF, crédit avec plafond, fidélité, tickets, retours/avoirs, rapport X), miroirs intersociétés (facture miroir, devis PO, demande de course). Lectures 75/75 ; banc croisé écritures 44/45 (le 45ᵉ = artefact de tri à la seconde, contenu identique prouvé). Correctif majeur au passage : rollback des transactions sur réponse d'erreur (helper refus() dans core/erreurs.py, appliqué à toutes les vues). |
| 6 | Ventes | devis → commande → BL → facture → règlements, encours | ✅ fait (2026-08-07) — devis/commande client (création, modification, envoi, confirmation avec associations d'articles et n° producteur, annulation), livraisons partielles (sortie stock CUMP, en attente comptable pour les PO), facturation des quantités livrées avec marge au coût livré, règlements clients espèces/banque/mobile money (garde-fous : dépassement, déjà réglée), encours clients, gates PO intersociété (chargement obligatoire, facturation bloquée par la réception acheteur). Lectures 19/19 ; banc croisé écritures 37/37 du premier coup. |
| 7 | Intersociétés | liaisons, miroirs, réceptions PO, confirmations, traçabilité, badges | ✅ fait (2026-08-09) — réception physique PO bon/mauvais/manquant (stock au reçu, manquants au transporteur au prix d'achat avec écritures croisées 401/758 et 658/411 en attente), annulation avec contre-passation complète, confirmation transporteur, liste réceptions + bon imprimable, liaisons lier/délier, positions groupe réconciliées, factures intra-groupe, règlement réel double-face (2 pièces TR en attente), traçabilité par n° producteur, badges. Lectures 22/22 ; banc croisé écritures 34/37 (les 3 = artefact d'ordre à la seconde, contenu trié prouvé identique). |
| 8 | Transport | flotte, courses, contrats, sous-traitance, maintenance, rentabilité | ✅ fait (2026-08-09) — config validateur, flotte propre/sous-traitée, chauffeurs (tiers personnel auto), contrats + grilles, fiches de course PROC-KL-01→04 (validation par rôle configurable, départ bloqué si camion indisponible ou avance carburant non décaissée, retour avec sous-traitance figée → dette 401 auto, facturation 706 des courses livrées avec miroir groupe), demandes de course PO (prise en charge bloquée jusqu'à confirmation vendeur, facturation sur le reçu confirmé), réquisitions liées à tout moment, maintenance immobilisante PROC-KL-05/06, rapport de rentabilité par camion/contrat. Lectures 35/35 ; banc croisé écritures 53/53 du premier coup. |
| 9 | Administration | sociétés, agents, rôles (héritage), paliers, paramètres | ✅ fait (2026-08-10) — rôles personnalisés avec héritage (rôles système protégés), sociétés (création complète : plan SYSCOHADA + caisse principale + affectations du créateur ; archivage ; suppression avec purge générique de toutes les tables si sans activité), paliers de validation avec approbateurs, paramètres, agents (création/modification/reset mdp/désactivation avec garde-fou), affectations (PK composite utilisateur_societe gérée en SQL brut — l'ORM Django ne sait pas l'écrire), pièces jointes (upload 10 Mo max/liste/téléchargement, même dossier backend/uploads). Lectures 20/20 ; banc croisé écritures 41/41 (y compris connexion réelle du nouvel agent et après reset de mot de passe). Piège trouvé : ville NOT NULL en base avec défaut SQLAlchemy « Likasi » invisible dans le schéma. |
| 10 | Bascule | migrations Django (--fake-initial), suppression backend FastAPI, doc équipe | ✅ fait (2026-08-14) — git init + commit (le projet est enfin versionné), frontend servi par Django (/, /static/*, /api/health, no-cache, sauvegarde quotidienne au démarrage), modèles managed=True (sauf utilisateur_societe, PK composite en SQL brut) + migration 0001_initial appliquée en --fake-initial (testée d'abord sur copie : 64 tables métier intactes à l'octet), lanceur basculé sur Django port 8000 (FastAPI archivé, démarrable port 8010), doc de passation docs/07-passation-django.md, vérification navigateur de bout en bout (connexion + cockpit financier sur données réelles). La suppression physique de backend/app/ est laissée à l'équipe après sa période d'essai (l'historique git la garde). |

## Règles pour le porteur (Claude ou l'équipe)

- Ne jamais modifier le comportement en portant : le test porté doit passer SANS
  adaptation du résultat attendu.
- Chaque endpoint garde son chemin et sa casse JSON exacts (le frontend fait foi).
- La logique métier pure (calculs, règles) se copie quasi telle quelle ; seules
  les requêtes ORM changent (SQLAlchemy select → QuerySet Django).
- `backend/` (FastAPI) reste intact et fonctionnel jusqu'à la phase 10.
