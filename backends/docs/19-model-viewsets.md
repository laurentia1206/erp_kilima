# Back-end : ModelViewSet, sérialiseurs et actions métier

Le back-end utilise maintenant 94 ViewSets pour les 214 routes métier
converties : 68 `ModelViewSet` pour les ressources persistantes et 26
`ViewSet` pour les rapports, calculs et commandes transversales.
La connexion, le profil connecté et l’état du serveur restent des `APIView`.
Les deux vues de fichiers HTML/statiques restent des vues Django ordinaires.

## Organisation

```text
Requête HTTP → urls.py → ModelViewSet / action
                       → contrôle des rôles et de la société
                       → validations et services métier → modèles Django
                       → sérialisation → réponse JSON
```

- `models.py` : données et relations, inchangées par ce chantier.
- `serializers.py` : schémas `ModelSerializer` explicites, sans `fields = '__all__'`.
- Les fichiers de vues regroupent les opérations par ressource dans un ViewSet.
- Les services existants conservent les calculs, les écritures et l’audit partagés.
- `urls.py` associe chaque méthode HTTP à l’action autorisée.

Par exemple, `apps/stocks/views.py` contient un `DepotViewSet` regroupant
`list`, `create` et `partial_update`. Il utilise `DepotSerializer` et un
`get_queryset()` qui contrôle les droits et filtre la société.
`apps/commercial/views.py` applique également ce découpage aux articles et
aux tiers, en conservant la visibilité des fiches partagées.

```python
path('stock/depots', DepotViewSet.as_view(
    {'get': 'list', 'post': 'create'},
    http_method_names=['get', 'post', 'options'],
    detail=False, basename='depot',
))
```

Les actions de workflow utilisent `@action`, par exemple
`PaieViewSet.preparer`, `PaieViewSet.decision`, `BulletinViewSet.payer` ou
`InventaireViewSet.decision`. Leurs transactions et contrôles existants
restent exécutés dans le traitement métier.

Les routes sont raccordées explicitement plutôt qu’enregistrées dans un
routeur CRUD automatique : cela préserve les chemins historiques, leurs
paramètres UUID nommés et les seules méthodes HTTP déjà autorisées.
Il n’y a pas de nouvelle API parallèle à adapter dans le front-end.

## Sérialisation et validations

Les sérialiseurs des dépôts, des articles, des tiers commerciaux et des
agents RH produisent effectivement les réponses existantes. Leurs
représentations conservent les montants numériques, les champs calculés
et, pour les agents, la distinction entre dossier public d’équipe et
informations privées autorisées par les contrôles RH.

Pour les autres ressources, les `ModelSerializer` définissent les schémas
de lecture et les actions conservent leurs représentations métier
spécifiques, notamment les documents et résultats composés. La conversion
ne prétend pas remplacer tous les formats existants par un CRUD brut.

Les champs de ces schémas de lecture sont non modifiables via le sérialiseur.
Les validations de saisie, détection de doublons, règles financières et
changements d’état restent dans les traitements existants, avant les écritures.
Une future extension pourra ajouter un sérialiseur de commande dédié et
l’appeler avec `is_valid()` sans remplacer les validations métier.
Les mots de passe hachés et les contenus binaires ne font pas partie des
schémas génériques.

## Garde-fous pour les prochaines évolutions

`core/viewsets.py` fournit `MetierModelViewSet` : ses opérations CRUD
héritées refusent les appels tant qu’une ressource ne les a pas explicitement
implémentées. Son queryset par défaut est fermé. Les actions spécialisées
continuent d’utiliser leurs requêtes et autorisations existantes ; les
ressources passant par `get_queryset()` définissent leur périmètre explicitement.

Cette base évite qu’un simple branchement de `destroy` supprime une pièce
comptable, ou qu’un `update` générique valide une paie. Pour ajouter une
opération, définir son autorisation, sa portée, ses validations et sa transaction,
puis la raccorder dans les routes et ajouter un test de comportement.

`OPTIONS` reste sans accès aux données métier. Les méthodes non autorisées,
dont `HEAD` lorsque le contrat l’exclut, restent refusées. Les anciens noms
de fonctions sont des alias vers les nouvelles actions pour les imports
existants ; les anciens handlers APIView métier ont été remplacés.

## Vérifications

- 120 tests Django passent, dont les cycles métier existants.
- Chaque route conserve ses méthodes HTTP et ses politiques d’authentification.
- Toutes les autres méthodes sont testées et refusées sans accès à la base.
- Tests des sérialiseurs, des actions sensibles, des tiers partagés et de
  l’isolation entre sociétés.
- Aucun changement de modèle ou de migration (`makemigrations --check --dry-run`).

```powershell
python manage.py test --settings=kilima.test_settings
```

Le guide `18-vues-en-classes.md` décrit l’étape historique précédente en
APIView ; le présent document décrit l’architecture actuelle.
