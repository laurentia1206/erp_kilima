# Journal de traçabilité

## Utilisation

Ouvrir **Pilotage → Journal de traçabilité** avec un compte DFI ou ADMIN_SYS
autorisé dans la société active. Actualiser recharge la situation ; cet écran
n'est pas un flux actualisé en permanence. Filtrer par période, utilisateur,
module, catégorie, action/référence ou identifiant de requête.

**Examiner** affiche les valeurs avant/après et les champs modifiés.
**Voir les traces liées** regroupe les événements d'une même requête dans le
périmètre et les filtres sélectionnés. Une validation peut ainsi produire une
trace métier et plusieurs modifications de données.

Les exports Excel et PDF utilisent les filtres appliqués au tableau et sa borne
de lecture, toutes pages confondues. Ils sont limités respectivement à 2 000 et
500 événements ; réduire la période au-delà. Excel contient les détails avant/après,
PDF présente une synthèse. Chaque export réussi produit sa propre trace.
Les réponses du journal et ses exports portent `Cache-Control: no-store`.

## Périmètres et confidentialité

- **Société active** : événements rattachés à cette société ; les droits sont
  contrôlés côté serveur pour la liste, les détails et les exports.
- **Clients / fournisseurs partagés** : modifications automatiques des fiches
  tiers communes, distinguées des opérations propres à chaque société.
- **Sécurité et réglages globaux** : réservé à ADMIN_SYS ; contient notamment
  les événements sans société identifiable et les anciennes traces non attribuables.

Les mots de passe, jetons, secrets, valeurs de paramètres et champs RH sensibles
sont masqués. Le journal signale la modification de ces champs sans révéler leurs
valeurs. Il ne remplace donc pas les dossiers RH et leurs autorisations spécifiques.
Le nom affiché de l'utilisateur vient de sa fiche actuelle ; son identifiant est
conservé dans la trace. Une fiche supprimée reste identifiable par cet identifiant.

## Couverture technique

Le dispositif est une implémentation locale autour du modèle `AuditLog`, et non
une installation du paquet tiers `django-auditlog`.

Les migrations `core.0022_journal_audit` et `core.0023_audit_protection` ajoutent
les métadonnées et des déclencheurs sur 97 tables métier. Les insertions,
modifications effectives et suppressions sont couvertes, y compris les opérations
en lot et le SQL exécuté par une connexion Django. Les tables techniques de
séquences, les types de contenu et le journal lui-même ne s'auto-journalisent pas.
Les anciennes traces sont étiquetées `historique` : aucun événement manquant ni
rattachement société absent ne peut être reconstitué rétrospectivement.

Chaque nouvelle trace contient, lorsque disponible : utilisateur, société,
horodatage UTC, action, document, module, catégorie, valeurs avant/après,
champs modifiés, adresse IP, méthode, chemin de route, origine et UUID de requête.
L'interface présente les heures de Lubumbashi. Hors requête HTTP, l'origine est
`systeme` et l'utilisateur peut être absent. Le journal ne consigne pas toutes
les consultations ordinaires ni les téléchargements de tous les autres modules.

Les connexions réussies/échouées et réponses API 401/403 sont consignées. Un
identifiant de connexion inconnu est pseudonymisé, sans enregistrer le mot de
passe essayé. Pour un utilisateur connu, l'événement de connexion est visible
dans ses sociétés d'affectation. Les événements anonymes restent globaux.

Le middleware génère lui-même l'identifiant de requête et utilise `REMOTE_ADDR`.
Il ignore les en-têtes IP fournis librement par le client. Derrière un proxy,
l'adresse enregistrée peut donc être celle du proxy ; configurer et tester une
chaîne de confiance explicite avant de chercher à restituer l'IP publique réelle.

Les écritures des requêtes API POST/PUT/PATCH/DELETE sont transactionnelles :
une réponse d'erreur annule leurs modifications de données et traces associées.
Les événements de sécurité sont écrits ensuite pour conserver la tentative.
Une panne de journalisation automatique fait échouer l'écriture concernée.

## Protection et exploitation

Le modèle refuse la modification/suppression de traces. La base les bloque
également par déclencheurs, y compris le remplacement d'une trace SQLite par
`INSERT OR REPLACE`. Sous PostgreSQL, le garde-fou couvre aussi `TRUNCATE`.
L'indicateur de l'écran contrôle la présence et les définitions attendues des
protections ; une alerte nécessite l'intervention de l'informaticien.

Cette protection n'est pas une signature cryptographique ni une garantie contre
un administrateur disposant de droits complets sur le disque ou la base. Un tel
administrateur peut retirer les déclencheurs ou remplacer les fichiers. Prévoir
des sauvegardes hors serveur avec accès restreint et tester leur restauration.
Aucune purge automatique du journal n'est activée ; surveiller sa croissance
et l'espace disque. Les sauvegardes contiennent des données confidentielles.

**SQLite** : les déclencheurs utilisent la fonction `kilima_audit`, enregistrée
par Django à l'ouverture de ses connexions. Les outils SQL externes qui ne
l'enregistrent pas peuvent lire/sauvegarder la base, mais leurs écritures sur les
tables auditées échouent. Utiliser Django pour les imports et opérations métier.
Ne pas relancer les anciens scripts FastAPI sur cette base migrée.

**Évolution du schéma** : une migration qui renomme/supprime une table ou un
champ audité doit retirer puis reconstruire les déclencheurs concernés dans la
même migration. Les nouvelles tables doivent être intégrées au plan. Le plan et
le générateur utilisés par 0023 sont figés dans les migrations ; ne pas modifier
une migration déjà appliquée. Ajouter une nouvelle migration et vérifier la
restauration, la couverture et l'indicateur de protection sur une copie.

**PostgreSQL** : le générateur contient une branche dédiée, mais cette livraison
a été testée sur SQLite. Une recette PostgreSQL réelle (migrations, transactions,
contexte utilisateur, regroupement, droits et blocage des altérations) demeure
nécessaire avant tout déploiement sur ce moteur.

## Validation de cette livraison

132 tests Django et 14 tests JavaScript ont réussi. Douze tests Django ciblent
l'audit : contexte, lots/SQL, annulation transactionnelle, panne de journal,
affectation société, immutabilité, authentification, masquage RH/secrets,
autorisations, filtres/pagination, exports et détection d'un déclencheur altéré.

Une migration préalable sur une copie cohérente de la base de tests a conservé
à l'identique les lignes des 99 tables hors audit comparées, avec intégrité SQLite
valide et 294 déclencheurs installés. La base de tests active a ensuite été
sauvegardée et migrée ; la base historique `backend/kilima_dev.db` est inchangée.

La consultation du journal et d'un détail de connexion a aussi été vérifiée dans
le navigateur. Ces vérifications ne constituent pas une certification de sécurité
ou de production.
