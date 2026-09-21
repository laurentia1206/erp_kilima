# Journal de sécurité du super administrateur

Dans **Super administration → Journal de sécurité**, le journal est directement
accessible à côté de **Comptes et permissions**. Le menu **Journal de sécurité**
ouvre également la même vue. Aucun accès aux opérations des sociétés n’est ajouté.

## Événements consultables

- Connexions réussies et refusées, comptes désactivés et accès HTTP refusés.
- Déconnexions volontaires envoyées depuis la nouvelle interface.
- Changements du mot de passe du super administrateur et refus de vérification
  du mot de passe actuel ; changements de mots de passe des comptes dans les
  traces de modification utilisateur, avec les valeurs masquées.
- Créations et modifications de comptes, affectations, rôles, permissions et
  statut super administrateur, avec les valeurs avant/après autorisées.
- Réponses API en erreur serveur : code HTTP et route uniquement, sans contenu
  métier, corps de requête, paramètres URL ni trace Python.
- Consultation d’une trace et export du journal par le super administrateur.

La surveillance conserve les protections existantes : journal en lecture seule,
masquage des secrets, filtrage côté Django, exports Excel/PDF et pagination stable.
Le super administrateur ne voit pas les traces des factures, salaires ou autres
opérations métier, ni les exports d’audit métier du DFI.

## Recherche et lecture

Les filtres combinent période, utilisateur, module, action, catégorie, adresse IP
exacte, recherche textuelle et identifiant de requête. Le bouton **Afficher les
événements à examiner** retient échecs de connexion/mot de passe, accès refusés et
erreurs serveur. Ces événements ne constituent pas à eux seuls la preuve d’une
intrusion. Les indicateurs portent sur la totalité de la sélection filtrée,
pas uniquement les 50 lignes affichées. Les copies d’une même connexion pour
plusieurs sociétés sont regroupées uniquement dans la vue super administrateur.

L’actualisation optionnelle toutes les 30 secondes respecte les filtres appliqués.
Elle se suspend pendant une consultation détaillée, un export, lorsque l’onglet
est masqué ou au-delà de la première page. Les exports utilisent le dernier
instantané chargé, pas des filtres saisis mais non appliqués.

## Portée technique

La déconnexion supprime immédiatement le jeton du navigateur ; sa trace serveur
nécessite une connexion réseau. Elle ne révoque pas toutes les copies d’un jeton
JWT existant. Cette évolution n’introduit pas de gestion centrale des sessions,
de blocage automatique d’adresses IP, ni de nouvelle politique de verrouillage.
Les comptes et permissions restent administrés dans le circuit existant.

L’adresse IP est celle reçue directement par Django. Derrière Next.js ou un
reverse proxy, elle peut être celle du relais : les en-têtes client arbitraires
ne sont pas considérés comme une source fiable. La fermeture du navigateur, les
requêtes qui n’atteignent pas Django et les erreurs d’infrastructure nécessitent
les journaux du serveur/reverse proxy. Aucun historique manquant n’est reconstitué.
Les traces ne résistent pas à un administrateur disposant des pleins droits sur
la base ou le disque : conserver des sauvegardes hors du serveur.

Aucune migration du schéma n’est nécessaire. L’API de déconnexion est
`POST /api/auth/logout`, authentifiée, disponible même pendant le remplacement
obligatoire d’un mot de passe provisoire.


## Mise à jour locale

Le lanceur Django utilise `--noreload`. Après une modification du backend, il faut
arrêter puis relancer Django sur 8012, en plus de recompiler/relancer Next.js sur
3000. Un simple contrôle HTTP 200 de la page d’accueil ne valide pas que les deux
versions sont synchronisées. Vérifier la réponse authentifiée du journal
(`actions` et `indicateurs`) et l’écran de super administration. Si Django renvoie
une ancienne réponse, l’interface présente désormais une erreur explicite dans
le journal et conserve l’accès à la gestion des comptes.
