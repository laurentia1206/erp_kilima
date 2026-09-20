# Super administration et permissions

## Espace de gestion

Le super administrateur arrive directement sur son tableau de gestion après
connexion. Il peut aussi ouvrir **Administration & réglages → Super administration**.
Cet espace donne accès uniquement aux comptes utilisateurs, aux rôles,
aux affectations, aux permissions et au journal des utilisateurs. Il ne donne
aucun accès aux opérations métier ni au paramétrage des sociétés. Les noms et
codes des sociétés sont consultables exclusivement pour affecter les utilisateurs.
Le sélecteur de société et les menus métier ne sont pas affichés.

Les comptes ordinaires conservent leurs affectations et leurs responsabilités.
Un rôle `ADMIN_SYS` affecté à une société ne confère pas le statut global de
super administrateur. Aucun compte existant n'est promu par les migrations.

## Gérer les droits d'un utilisateur

1. **Rôles / sociétés** définit les sociétés accessibles et les responsabilités
   métier. Un rôle personnalisé peut hériter d'un rôle de base.
2. **Permissions** permet d'ajouter des limites par module : consulter, créer,
   modifier, supprimer, actions métier et exporter.
3. Enregistrer applique la modification dès la requête suivante. Pour mettre à
   jour les menus d'une session déjà ouverte, l'utilisateur recharge la page.

Les limites par module s'appliquent à **toutes les sociétés de cet utilisateur**.
Elles sont complémentaires aux rôles : cocher une case n'accorde pas un droit
que les rôles ou les circuits métier ne permettent pas. Désactiver « Consulter »
bloque les autres actions de ce module. Les raccourcis « Lecture seule »,
« Tout restreindre » et « Droits des rôles » facilitent le paramétrage.

« Actions métier » couvre les opérations spécifiques telles que valider,
confirmer, payer, préparer, clôturer et certaines saisies groupées. Les cases
Créer/Modifier/Supprimer portent sur les actions CRUD déclarées par les ViewSets.
« Exporter » couvre les routes serveur d'export et téléchargement du module.
Les exports généraux ont leur propre module « Documents et exports généraux ».
Ces permissions ne peuvent pas empêcher la copie ou l'impression par le navigateur
de données déjà consultées. Les écrans transversaux, tels que Pilotage ou le
journal, disposent de leurs propres permissions et présentent leurs synthèses.

Le statut de super administrateur bloque les opérations métier, même si des
rôles tels que DFI ou COMPTABLE ont été affectés au compte. Il ne peut créer,
modifier, archiver ou supprimer une société, intervenir dans la comptabilité,
la caisse, le stock ou les RH, ni modifier les circuits de validation. Utiliser
un compte métier distinct pour ces responsabilités. Les opérations des autres
utilisateurs restent soumises à leurs rôles et circuits habituels.

Son journal contient uniquement les comptes, rôles, affectations, permissions,
statuts de super administration et événements d'authentification. Les traces
d'opérations des sociétés sont exclues des listes, détails et exports.

## Protection des comptes globaux

- Seul un super administrateur peut nommer ou révoquer un autre super administrateur.
- Un compte désactivé ne peut pas être promu.
- Un super administrateur ne peut pas retirer son propre statut.
- Il faut retirer le statut global avant de désactiver son compte.
- Les anciens écrans d'administration refusent aussi à un administrateur ordinaire
  la modification d'identité ou de mot de passe d'un compte global, même inactif.
- Les mises à jour concurrentes des permissions sont détectées par une révision.
- Les droits sont relus côté serveur ; ils ne sont pas figés dans le jeton de session.

Le compte initial demandé, `admin@kilimaholdings.com`, a été créé dans la base
de tests. Son mot de passe provisoire est fourni dans un fichier confidentiel
séparé du ZIP et doit être remplacé à la première connexion. Le système bloque
les autres opérations tant que ce changement n'a pas été effectué.

Les nouvelles sessions sont liées à une empreinte du mot de passe : remplacer
celui-ci invalide ces sessions précédentes. Les anciens jetons dépourvus de cette
empreinte restent acceptés pour les comptes ordinaires jusqu'à expiration ;
un super administrateur doit se reconnecter avec un nouveau jeton.
Le mot de passe n'est pas stocké dans le jeton ni dans le journal.

## Architecture et exploitation

Deux modèles du socle Django sont ajoutés : `SuperAdministrateur` et
`PermissionModule`. Les routes `/api/systeme/...` utilisent un ModelViewSet.
`PermissionsModules`, appliquée globalement par DRF, complète les autorisations
existantes ; l'interface ne constitue jamais le seul contrôle.

Les migrations `0024_permissions_systeme` et `0025_audit_permissions` créent les
tables et leurs déclencheurs d'audit. Le rôle système `ADMIN_SYS` est créé s'il
manque, sans affectation automatique. La couverture passe à 99 tables et 300
déclencheurs sous SQLite. Les promotions, révocations et changements de limites
sont des événements globaux, consultables dans le périmètre global du journal.

Pour une installation sans aucun super administrateur, créer d'abord le compte
utilisateur voulu puis exécuter, sur la bonne base :

```powershell
python manage.py initialiser_super_admin adresse@entreprise.com
```

Cette commande refuse de remplacer une administration globale existante et ne
change pas les mots de passe. Les nominations suivantes passent par l'espace
de gestion. Conserver plusieurs administrateurs de confiance pour assurer la
continuité ; ne pas partager un compte nominatif entre plusieurs personnes.

## Vérifications

145 tests Django passent, dont 13 cas sur les permissions : administration des
utilisateurs, refus aux comptes ordinaires, sessions déjà ouvertes, périmètre société,
droits séparés, modifications concurrentes, journalisation, retrait du statut,
mot de passe initial, invalidation des sessions et protection d'un compte inactif.
Les tests JavaScript couvrent aussi le masquage des modules et l'accès à l'espace.

La migration a été testée sur une copie avant application : 98 tables métier
comparées sont inchangées et tous les rôles existants sont conservés. Le nouveau
rôle système et les types de contenu techniques sont les seuls ajouts aux tables
préexistantes, hors journal et historique de migration. Une sauvegarde de la base
de tests a précédé l'installation. La base historique n'a pas été modifiée.
La recette PostgreSQL reste à effectuer avant utilisation sur ce moteur.

La correction du périmètre vérifie également le refus sur toutes les routes des
applications métier, ainsi que l'exclusion des événements métier du journal du
super administrateur. Elle ne modifie aucun mot de passe ni aucune donnée métier.
