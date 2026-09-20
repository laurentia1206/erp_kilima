# Vues Django en classes

> Étape historique : les ressources métier sont désormais des ModelViewSet.
> Voir [l’architecture actuelle](19-model-viewsets.md).

Les 219 vues API sont maintenant des classes explicites qui héritent de
`rest_framework.views.APIView`. Les applications métier et les modèles
introduits lors du découpage précédent sont conservés.

## Organisation

Le flux d’une requête est :

```text
Interface → urls.py → XxxView.as_view() → get/post/patch/put/delete
                                      → contrôles d’accès et services métier
                                      → modèles Django → base de données
```

- `models.py` décrit les données et leurs relations.
- Les classes de vues traitent les requêtes et produisent les réponses.
- Les services portent les opérations partagées : comptabilité, stocks,
  calculs RH, numérotation et audit.
- `urls.py` associe chaque adresse à la classe de vue correspondante.

Exemple réel, dans `apps/rh/paie_views.py` :

```python
class SimulerView(APIView):
    http_method_names = ['post', 'options']

    def post(self, request):
        contexte(request)
        parametres, resultat = simulation(request.data)
        return Response({'parametres': parametres, 'resultat': resultat})
```

Sa route dans `apps/rh/urls.py` :

```python
path('rh/simuler', rh_paie_views.SimulerView.as_view()),
```

Le vocabulaire Django est habituellement **Model–Template–View (MVT)**.
Ici, l’interface JavaScript consomme une API : les modèles, les vues en classes
et les services constituent le back-end, sans imposer de templates HTML aux
réponses JSON. Les deux fonctions qui servent la page et les fichiers
statiques restent de simples fonctions Django ; ce ne sont pas des vues API.

## Règles conservées

Les méthodes HTTP autorisées sont déclarées explicitement. Une requête
`HEAD` n’est pas ajoutée implicitement aux anciennes routes `GET` ; `OPTIONS`
reste disponible. L’authentification JWT et les permissions par défaut
s’appliquent toujours. Seuls la connexion et l’état du serveur restent publics.
Les contrôles de rôle et de société restent dans les traitements métier.

Les vues qui partagent un traitement entre plusieurs méthodes exposent des
méthodes `get`, `post`, etc., qui appellent `_traiter`. Cela conserve la portée
des contrôles et transactions sans dupliquer les opérations communes.
Les décorateurs `transaction.atomic` restent sur le traitement concerné,
après l’authentification ; ils n’ont pas été retirés ou déplacés autour des
réponses d’erreur de Django REST Framework.

Les anciens noms de fonctions sont des alias `XxxView.as_view()` pour garder
les imports existants. Les routes et le nouveau code utilisent directement
les classes. Aucun second moteur métier n’a été ajouté.

La conversion n’ajoute pas de migration, ne change pas les modèles ou les
tables, et conserve les circuits de validation. Les actions sensibles comme
valider une paie ou payer un bulletin restent des opérations explicites ;
elles ne sont pas exposées comme des modifications génériques sans contrôle.

## Vérification

Les 111 tests existants passent. Quatre tests supplémentaires vérifient :

- les classes raccordées à chaque route et les politiques de sécurité ;
- les réponses `OPTIONS`, `TRACE` et `HEAD`, sans accès à la base ;
- le refus des requêtes anonymes sur toutes les routes protégées ;
- l’accès public à la connexion et à l’état du serveur.

Le contrat HTTP précédent est enregistré dans `core/tests/api_contract.json`.
Les scénarios métier existants continuent de vérifier les écritures,
les validations, l’atomicité et l’isolation entre sociétés.

Depuis `backend_django/` :

```powershell
python manage.py test --settings=kilima.test_settings
```
