# Kilima Terrain — application mobile

Application Flutter de **gestion à distance** de l'ERP Kilima Holdings.
Elle consomme les API REST du backend Django existant (aucune modification
du backend n'est nécessaire).

## Périmètre de cette première version

1. **Connexion** (`POST /api/auth/login`) et choix de la société active ;
2. **Accueil** : compteurs décaissements (`GET /api/dashboard`) ;
3. **Réquisitions** : liste, détail avec progression du circuit, échanges
   (précisions / réponses), création, validation / rejet ;
4. **Maintenance** : interventions camions & engins, fiche d'atelier
   (liste de tâches, mécanicien, compteur), démarrer / terminer, demande
   d'achat de pièces (réquisition liée) et bon de consommation du stock ;
5. **Pièces jointes** : photos prises sur place (appareil photo) envoyées en
   multipart (`POST /api/pieces-jointes`) sur les réquisitions et
   interventions.

Interface en français, charte Kilima (teal `#176B61`).

## Prérequis

- [SDK Flutter](https://docs.flutter.dev/get-started/install/windows) stable
  (projet créé avec Flutter 3.50 / Dart 3.14) — dézippé par exemple dans
  `C:\Users\<vous>\flutter`, avec `flutter\bin` ajouté au PATH ;
- Pour l'APK Android : Android Studio (SDK Android + outils de build) ;
- Le backend Django de l'ERP lancé : `python manage.py runserver 8012`
  depuis `version deployée\erp_kilima\backend`.

## Lancer en développement

```bash
flutter pub get
```

### Sur un émulateur ou un téléphone Android

```bash
flutter run
```

L'URL par défaut est `http://10.0.2.2:8012` (l'adresse du PC vue depuis
l'émulateur Android). Sur un **téléphone réel** branché en USB ou sur le même
Wi-Fi, ouvrir « Serveur » sur l'écran de connexion et saisir
`http://<IP-du-PC>:8012`.

### En mode web (test rapide sans Android)

Le backend n'envoie pas d'en-têtes CORS ; le navigateur refuse donc les appels
directs depuis un autre port. Un petit proxy de développement est fourni :

```bash
python tool/dev_proxy.py
```

```bash
flutter run -d web-server --web-port 8014
```

Puis ouvrir `http://localhost:8014` — l'URL de serveur par défaut en mode web
est `http://localhost:8013` (le proxy). Ce proxy ne sert **qu'au test local**.

### Compte de démonstration

`dfi@kilima.cd` / `demo1234` (sociétés Guest House Relax, ETS Horizon…).

## Configurer l'URL de production (HTTPS)

Sur l'écran de connexion, toucher **Serveur** et saisir l'URL publique du
backend, par exemple `https://erp.kilima.cd`. Elle est **mémorisée sur
l'appareil** (il n'y a rien à recompiler). L'application ajoute elle-même
`/api/...` aux chemins.

> Production = HTTPS obligatoire : Android bloque le HTTP clair vers un
> domaine public. Le `usesCleartextTraffic="true"` du manifeste ne sert
> qu'aux tests locaux en `http://`.

## Construire l'APK Android

```bash
flutter build apk --release
```

L'APK est produit dans `build/app/outputs/flutter-apk/app-release.apk` ;
le copier sur les téléphones (ou le distribuer par lien) et l'installer
(« sources inconnues » à autoriser). Pour un APK plus léger par architecture :

```bash
flutter build apk --release --split-per-abi
```

> Signature : le build release utilise la clé de débogage par défaut, ce qui
> suffit pour une distribution interne. Pour publier sur le Play Store, créer
> une clé (`keytool`) et la déclarer dans `android/app/build.gradle.kts`
> (bloc `signingConfigs`) — voir la documentation Flutter « build and release
> an Android app ».

## Structure du code

| Fichier | Rôle |
|---|---|
| `lib/api_client.dart` | Client HTTP : login form-urlencoded, Bearer, JSON, multipart, erreurs `{detail}` |
| `lib/app_state.dart` | Session (jeton, utilisateur, sociétés, société active), persistance locale |
| `lib/screens/login_screen.dart` | Connexion + URL du serveur |
| `lib/screens/home_screen.dart` | Compteurs du dashboard + navigation |
| `lib/screens/requisitions_screen.dart` | Liste + création de réquisitions |
| `lib/screens/requisition_detail_screen.dart` | Détail, progression, échanges, actions du circuit |
| `lib/screens/maintenance_screen.dart` | Interventions + signalement |
| `lib/screens/intervention_detail_screen.dart` | Fiche d'atelier, checklist, pièces (achat / stock) |
| `lib/widgets/pieces_jointes.dart` | Photos / fichiers joints (multipart) |
| `tool/dev_proxy.py` | Proxy CORS pour le test en mode web uniquement |

Chaque appel API reproduit le contrat exact des vues Django
(`core/views.py`, `apps/approbations/views.py`, `apps/transport/views.py`,
`apps/maintenance/views.py`, `core/config_views.py`).
