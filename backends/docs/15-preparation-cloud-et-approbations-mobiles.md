# ERP Kilima — préparation du pilote cloud et des approbations mobiles

Document de passation à l’informaticien — 15 septembre 2026.

Ce document décrit la cible proposée et les travaux à réaliser. Il ne constate ni un déploiement cloud effectué, ni une application mobile déjà livrée. L’offre exacte « Sygma Cloud » reste à identifier ; aucune compatibilité commerciale n’est présumée.

## 1. Fonctionnement proposé sur téléphone

Créer une application web installable (PWA), centrée sur les demandes et leur validation. Elle s’utilise depuis le navigateur ou une icône sur l’écran du téléphone. Le site ERP complet demeure accessible sur ordinateur.

Les deux interfaces utilisent le même serveur Django, les mêmes comptes, les mêmes droits par société et la même base PostgreSQL. Aucun transfert entre deux bases mobiles et web n’est nécessaire. Restreindre les menus mobiles ne remplace pas les contrôles d’autorisation du serveur.

Écrans à réaliser :

- Mes demandes : préparation, pièces jointes ou photo, soumission, suivi des étapes.
- À valider : dossiers autorisés pour l’utilisateur, société clairement visible, montant et devise, motif, bénéficiaire provisoire, justificatifs et historique.
- Détail : actions conformes au circuit existant, confirmation de la décision et affichage de son résultat.
- Historique et notifications : accès au dossier concerné, lecture de son état actuel après reconnexion.

Conserver les circuits existants : une approbation ne réalise pas automatiquement un paiement. Toute nouvelle délégation, règle d’escalade ou modification des étapes devra être présentée à Laurent avant développement.

Prévoir les notifications push avec autorisation de l’utilisateur, et une boîte « À valider » fiable même si la notification n’arrive pas. Les notifications ne constituent pas une preuve de lecture. Sur iPhone, le Web Push est pris en charge à partir d’iOS 16.4 pour les applications ajoutées à l’écran d’accueil. Tester les téléphones réellement utilisés. Sources : [Apple](https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers), [WebKit](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/).

Pour la première version, envoyer les demandes et approuver uniquement avec une connexion active. Après une coupure, relire l’état sur le serveur avant de réessayer. Tester et garantir qu’un double appui ou deux validateurs simultanés ne produisent pas deux opérations. Ne pas conserver les justificatifs, réponses privées ou jetons dans le cache hors connexion du service worker.

## 2. Informations à obtenir de Sygma Cloud

L’informaticien peut demander les éléments suivants au fournisseur, sans transmettre de données de paie :

| Élément | Réponse attendue |
|---|---|
| Abonnement | Nom exact de l’offre, lien fournisseur, services inclus et éventuels suppléments |
| Hébergement applicatif | Machine virtuelle Linux ou service capable d’exécuter durablement une application Python/Django et un serveur WSGI |
| Administration | Accès nominatif SSH avec clé et droits d’installation, ou mécanisme de déploiement équivalent sur service géré |
| Ressources | Processeurs, mémoire, stockage persistant, possibilité d’augmentation |
| Base | PostgreSQL disponible, version maintenue, accès privé, chiffrement et sauvegardes proposés |
| Réseau | Domaine/DNS, HTTPS, pare-feu, sorties nécessaires pour courriel et notifications push |
| Sauvegardes | Fréquence, rétention, copie indépendante, délai de restauration et responsabilité opérationnelle |
| Exploitation | Localisation des données, support, maintenance, disponibilité contractuelle, export et réversibilité |
| Recette | Possibilité d’un environnement de test distinct de la production |

Un simple espace destiné à PHP/MySQL n’est pas suffisant sans prise en charge explicite de Django et des processus persistants.

Comme hypothèse de départ pour un pilote de 10 à 30 utilisateurs simultanés : 4 vCPU, 8 Go de RAM et 100 Go SSD pour une machine applicative avec petite base locale privée. Il s’agit d’un dimensionnement provisoire à mesurer, pas d’une garantie de capacité. Réévaluer selon les PDF, les pièces jointes et les traitements mensuels. Une base gérée séparée peut modifier ce besoin. Ne pas commander de supplément avant vérification de l’offre existante.

## 3. Ce que Kilima doit fournir à l’informaticien

- Domaine appartenant au groupe et personne autorisée à modifier les DNS. Exemples à remplacer : `recette.<domaine-du-groupe>` et `erp.<domaine-du-groupe>`.
- Contacts du fournisseur et accès techniques nominatifs à durée et droits adaptés ; transmettre les secrets par un canal sécurisé, pas dans ce document.
- Liste des sociétés pilotes, utilisateurs, rôles, validateurs et affectations autorisées par société.
- Nombre d’utilisateurs simultanés estimé, téléphones Android/iPhone concernés et pays habituels de connexion.
- Boîte expéditrice et configuration du service de courriel si les notifications par courriel sont retenues.
- Données de départ expressément choisies, soldes à reprendre et responsables de leur vérification. Décider quelles opérations de test seront exclues.
- Responsable de l’exploitation, responsable des sauvegardes, contacts d’incident et créneau de bascule.

Le prestataire technique ne doit pas décider seul des rôles financiers ou des soldes d’ouverture.

## 4. État technique vérifié dans le projet

- Moteur actif : `backend/`, Django REST Framework ; interface commune dans `backend/static/`. Le moteur FastAPI historique n’est pas celui à déployer.
- Versions figées actuellement : Django 5.1.4, DRF 3.15.2. Django 5.1 n’est plus maintenu. Qualifier une mise à niveau vers la dernière correction disponible de Django 5.2 LTS et des dépendances compatibles avant exposition publique. [Versions officielles Django](https://www.djangoproject.com/download/).
- Installation locale de test : SQLite. Le paramétrage PostgreSQL existe, mais cela ne prouve pas que la migration des données et tous les traitements ont été validés sur PostgreSQL.
- Pièces jointes : `backend/uploads/`, à conserver sur un volume persistant protégé et à sauvegarder avec la base. Elles passent par des routes applicatives contrôlées ; ne pas exposer ce répertoire comme des fichiers publics.
- Sauvegarde existante : mécanisme SQLite au démarrage. Il ne remplace pas des sauvegardes PostgreSQL planifiées et surveillées.
- Authentification actuelle : jeton JWT, conservé dans le stockage local du navigateur, durée par défaut de 12 heures. Prévoir une revue des sessions, de la révocation et de la protection contre les injections ; une déconnexion locale seule ne révoque pas un jeton volé.
- Aucune application PWA ni notification push n’a été livrée dans cette préparation.

## 5. Travaux de déploiement à réaliser

1. Mettre à jour et tester les dépendances sur une copie isolée. Vérifier aussi les traitements concurrents sur PostgreSQL.
2. Installer un serveur WSGI de production, par exemple Gunicorn sur Linux, derrière un proxy HTTPS. Le serveur local `runserver` ne sert pas de serveur Internet. Prévoir le redémarrage automatique et les journaux. [Consignes Django](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
3. Configurer `ENVIRONMENT=production`, `DEBUG=false`, une `SECRET_KEY` aléatoire distincte par environnement et les noms autorisés dans `ALLOWED_HOSTS`. Définir `DATABASE_URL` ; vérifier qu’un ancien `KILIMA_DB` de test ne prend pas priorité.
4. Configurer correctement la terminaison HTTPS et la confiance dans les en-têtes du proxy. Le code actuel ne règle pas cette intégration. Ne faire confiance qu’au proxy contrôlé et empêcher tout accès direct au serveur applicatif.
5. Utiliser PostgreSQL maintenu avec un compte applicatif dédié, sans superutilisateur, et sans port public. Si la base est distante, adapter explicitement le paramétrage Django pour le TLS et la vérification du certificat : le parseur actuel de l’URL ignore ses paramètres de requête, donc ajouter simplement `?sslmode=...` à l’URL ne suffit pas. [Support PostgreSQL](https://www.postgresql.org/support/versioning/).
6. Renforcer les accès : comptes individuels, suppression ou désactivation des comptes de démonstration après inventaire, mots de passe personnels, limitation des tentatives, récupération de compte, révocation des sessions. Prévoir une authentification à deux facteurs pour les validateurs et administrateurs avant le pilote public ; son intégration reste à développer.
7. Protéger les justificatifs et vérifier les journaux d’approbation. Les notifications doivent éviter d’afficher des données financières confidentielles sur l’écran verrouillé.
8. Mettre en place sauvegarde PostgreSQL et fichiers, copie chiffrée séparée du serveur, alertes d’échec et restauration testée. Pour le pilote, proposer une sauvegarde quotidienne avec 30 jours de rétention ; faire valider la perte maximale acceptable et le délai de reprise. Si quelques heures de perte sont inacceptables, prévoir une sauvegarde plus fréquente ou la restauration à un instant donné.
9. Créer une recette séparée : base, fichiers, clés, comptes et notifications distincts. Ne pas envoyer de notifications réelles depuis des essais.

## 6. Reprise de données et test grandeur nature

Ne pas écraser la base locale d’origine. La base de recette actuelle contient des essais : elle ne devient pas automatiquement la base de production.

Préparer une procédure de transfert contrôlée SQLite → PostgreSQL sur copie. Vérifier les migrations historiques, les identifiants, les relations, les dates, les décimales, les séquences et les pièces jointes. Rapprocher au minimum les effectifs, demandes, soldes des caisses, écritures comptables et stocks. Un simple changement de l’adresse de connexion ne transfère pas les données.

Commencer avec un groupe restreint couvrant demandeur, valideurs, DFI et caissier. Faire les essais depuis ordinateur, Android et iPhone, avec plusieurs sociétés et une connexion hors du réseau du bureau.

Scénarios obligatoires : demande complète, pièce jointe, refus, approbations successives, accès interdit à une autre société, double appui, décisions concurrentes, réseau interrompu, session expirée, téléchargement de documents et restauration d’une sauvegarde. Vérifier que la validation conserve le circuit de décaissement séparé.

Pour le passage aux opérations réelles : arrêter temporairement les saisies sur la source retenue, prendre une sauvegarde cohérente, transférer les données, rapprocher les résultats et obtenir la validation métier. Définir à l’avance une procédure de retour qui préserve les opérations saisies depuis la bascule ; restaurer simplement une vieille copie ferait perdre ces opérations.

Le pilote est accepté après validation métier, tests d’accès, de concurrence et de restauration. Les tests locaux déjà réussis sont un point de départ, pas une validation de l’hébergement ou de la capacité en charge.
