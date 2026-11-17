import 'dart:convert';

import 'package:http/http.dart' as http;

/// Erreur renvoyée par l'API ({"detail": "..."} côté Django).
class ApiException implements Exception {
  final int status;
  final String message;
  ApiException(this.status, this.message);

  @override
  String toString() => message;
}

/// Client HTTP centralisé : jeton Bearer, JSON, formulaires et multipart.
class ApiClient {
  String baseUrl;
  String? token;

  ApiClient({required this.baseUrl});

  Uri _uri(String path, [Map<String, String>? query]) {
    final base = baseUrl.endsWith('/')
        ? baseUrl.substring(0, baseUrl.length - 1)
        : baseUrl;
    return Uri.parse('$base$path').replace(
        queryParameters: (query == null || query.isEmpty) ? null : query);
  }

  Map<String, String> _headers({String? contentType}) => {
        if (token != null) 'Authorization': 'Bearer $token',
        if (contentType != null) 'Content-Type': contentType,
      };

  /// POST /api/auth/login — form-urlencoded username/password (contrat OAuth2).
  Future<void> login(String username, String password) async {
    final r = await http.post(
      _uri('/api/auth/login'),
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: {'username': username, 'password': password},
    );
    final data = _decode(r);
    token = data['access_token'] as String?;
    if (token == null) {
      throw ApiException(r.statusCode, 'Réponse de connexion invalide.');
    }
  }

  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    final r = await http.get(_uri(path, query), headers: _headers());
    return _decode(r);
  }

  Future<dynamic> post(String path,
      [Object? body, Map<String, String>? query]) async {
    final r = await http.post(_uri(path, query),
        headers: _headers(contentType: 'application/json'),
        body: jsonEncode(body ?? {}));
    return _decode(r);
  }

  Future<dynamic> patch(String path, Object body) async {
    final r = await http.patch(_uri(path),
        headers: _headers(contentType: 'application/json'),
        body: jsonEncode(body));
    return _decode(r);
  }

  /// POST /api/pieces-jointes — multipart (file + document_type + document_id).
  Future<dynamic> uploadPieceJointe({
    required String documentType,
    required String documentId,
    required String filename,
    required List<int> bytes,
  }) async {
    final req = http.MultipartRequest('POST', _uri('/api/pieces-jointes'));
    req.headers.addAll(_headers());
    req.fields['document_type'] = documentType;
    req.fields['document_id'] = documentId;
    req.files.add(http.MultipartFile.fromBytes('file', bytes,
        filename: filename));
    final r = await http.Response.fromStream(await req.send());
    return _decode(r);
  }

  dynamic _decode(http.Response r) {
    dynamic data;
    try {
      data = jsonDecode(utf8.decode(r.bodyBytes));
    } catch (_) {
      data = null;
    }
    if (r.statusCode >= 400) {
      throw ApiException(r.statusCode, _messageErreur(r.statusCode, data));
    }
    return data;
  }

  String _messageErreur(int status, dynamic data) {
    final detail = (data is Map) ? data['detail'] : null;
    if (detail is String && detail.isNotEmpty) return detail;
    if (detail is List) {
      // format 422 de validation : [{loc: [...], msg: ...}]
      return detail
          .map((e) => e is Map
              ? '${(e['loc'] as List?)?.join('.') ?? ''} : ${e['msg'] ?? e}'
              : '$e')
          .join('\n');
    }
    switch (status) {
      case 401:
        return 'Session expirée ou identifiants invalides.';
      case 403:
        return 'Accès refusé.';
      case 404:
        return 'Ressource introuvable.';
      default:
        return 'Erreur serveur ($status).';
    }
  }
}
