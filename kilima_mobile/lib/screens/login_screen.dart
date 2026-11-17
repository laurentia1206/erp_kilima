import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../app_state.dart';
import '../widgets/common.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _motDePasse = TextEditingController();
  late final TextEditingController _serveur;
  bool _chargement = false;
  bool _voirServeur = false;
  bool _voirMotDePasse = false;

  @override
  void initState() {
    super.initState();
    _serveur =
        TextEditingController(text: context.read<AppState>().api.baseUrl);
  }

  Future<void> _connexion() async {
    if (_email.text.trim().isEmpty || _motDePasse.text.isEmpty) {
      montrerErreur(context, 'Saisissez votre email et votre mot de passe.');
      return;
    }
    setState(() => _chargement = true);
    try {
      await context
          .read<AppState>()
          .connecter(_email.text, _motDePasse.text, _serveur.text);
    } catch (e) {
      if (mounted) montrerErreur(context, e);
    } finally {
      if (mounted) setState(() => _chargement = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 84,
                  height: 84,
                  decoration: BoxDecoration(
                    color: couleurKilima,
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: const Icon(Icons.terrain, color: Colors.white, size: 48),
                ),
                const SizedBox(height: 16),
                Text('Kilima Terrain',
                    style: Theme.of(context)
                        .textTheme
                        .headlineMedium
                        ?.copyWith(
                            color: couleurKilima,
                            fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                const Text('Gestion à distance — ERP Kilima Holdings',
                    style: TextStyle(color: Colors.grey)),
                const SizedBox(height: 28),
                TextField(
                  controller: _email,
                  keyboardType: TextInputType.emailAddress,
                  autofillHints: const [AutofillHints.username],
                  decoration: const InputDecoration(
                    labelText: 'Email',
                    prefixIcon: Icon(Icons.mail_outline),
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _motDePasse,
                  obscureText: !_voirMotDePasse,
                  autofillHints: const [AutofillHints.password],
                  onSubmitted: (_) => _connexion(),
                  decoration: InputDecoration(
                    labelText: 'Mot de passe',
                    prefixIcon: const Icon(Icons.lock_outline),
                    border: const OutlineInputBorder(),
                    suffixIcon: IconButton(
                      icon: Icon(_voirMotDePasse
                          ? Icons.visibility_off
                          : Icons.visibility),
                      onPressed: () =>
                          setState(() => _voirMotDePasse = !_voirMotDePasse),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: () =>
                        setState(() => _voirServeur = !_voirServeur),
                    icon: Icon(
                        _voirServeur ? Icons.expand_less : Icons.settings,
                        size: 18),
                    label: const Text('Serveur'),
                  ),
                ),
                if (_voirServeur) ...[
                  TextField(
                    controller: _serveur,
                    keyboardType: TextInputType.url,
                    decoration: const InputDecoration(
                      labelText: 'URL du serveur',
                      hintText: 'https://erp.kilima.cd',
                      prefixIcon: Icon(Icons.dns_outlined),
                      border: OutlineInputBorder(),
                      helperText:
                          'Local : http://10.0.2.2:8012 (émulateur Android)',
                    ),
                  ),
                  const SizedBox(height: 12),
                ],
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  height: 48,
                  child: FilledButton(
                    onPressed: _chargement ? null : _connexion,
                    child: _chargement
                        ? const SizedBox(
                            width: 22,
                            height: 22,
                            child: CircularProgressIndicator(
                                strokeWidth: 2, color: Colors.white))
                        : const Text('Se connecter',
                            style: TextStyle(fontSize: 16)),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
