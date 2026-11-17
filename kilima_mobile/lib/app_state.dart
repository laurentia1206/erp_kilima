import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';

/// URL par défaut du backend selon la plateforme :
/// - émulateur Android : 10.0.2.2 pointe vers le PC hôte ;
/// - web / bureau : localhost.
/// En production, saisir l'URL HTTPS dans l'écran de connexion
/// (champ « Serveur ») — elle est mémorisée sur l'appareil.
String defaultBaseUrl() {
  if (kIsWeb) return 'http://localhost:8013'; // proxy de dev (tool/dev_proxy.py)
  if (defaultTargetPlatform == TargetPlatform.android) {
    return 'http://10.0.2.2:8012';
  }
  return 'http://localhost:8012';
}

class Societe {
  final String id;
  final String code;
  final String nom;
  final List<String> roles;
  Societe(this.id, this.code, this.nom, this.roles);

  factory Societe.fromJson(Map<String, dynamic> j) => Societe(
        j['id'] as String,
        (j['code'] ?? '') as String,
        (j['nom'] ?? '') as String,
        ((j['roles'] as List?) ?? const []).map((e) => '$e').toList(),
      );
}

/// État global : session, société active, client API.
class AppState extends ChangeNotifier {
  final ApiClient api = ApiClient(baseUrl: defaultBaseUrl());

  Map<String, dynamic>? utilisateur;
  List<Societe> societes = [];
  Societe? societeActive;
  bool pret = false; // restauration de session terminée

  bool get connecte => api.token != null && utilisateur != null;

  String get nomUtilisateur {
    final u = utilisateur;
    if (u == null) return '';
    return [u['prenom'], u['nom']].where((e) => (e ?? '') != '').join(' ');
  }

  /// Rôles de l'utilisateur sur la société active.
  List<String> get rolesActifs => societeActive?.roles ?? const [];

  Future<void> restaurer() async {
    final prefs = await SharedPreferences.getInstance();
    api.baseUrl = prefs.getString('kt_base_url') ?? defaultBaseUrl();
    final token = prefs.getString('kt_token');
    if (token != null) {
      api.token = token;
      try {
        await _chargerSession(prefs.getString('kt_societe'));
      } on ApiException {
        api.token = null; // jeton expiré → retour à la connexion
      } catch (_) {
        api.token = null; // serveur injoignable au démarrage
      }
    }
    pret = true;
    notifyListeners();
  }

  Future<void> connecter(String email, String motDePasse, String url) async {
    api.baseUrl = url.trim();
    await api.login(email.trim(), motDePasse);
    await _chargerSession(null);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('kt_base_url', api.baseUrl);
    await prefs.setString('kt_token', api.token!);
    notifyListeners();
  }

  Future<void> _chargerSession(String? societeMemorisee) async {
    utilisateur = Map<String, dynamic>.from(await api.get('/api/auth/me'));
    final brut = await api.get('/api/societes') as List;
    societes = brut
        .map((e) => Societe.fromJson(Map<String, dynamic>.from(e)))
        .toList();
    societeActive = null;
    if (societes.isNotEmpty) {
      societeActive = societes.firstWhere((s) => s.id == societeMemorisee,
          orElse: () => societes.first);
    }
  }

  Future<void> choisirSociete(Societe s) async {
    societeActive = s;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('kt_societe', s.id);
    notifyListeners();
  }

  Future<void> deconnecter() async {
    try {
      await api.post('/api/auth/logout');
    } catch (_) {}
    api.token = null;
    utilisateur = null;
    societes = [];
    societeActive = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('kt_token');
    notifyListeners();
  }
}
