import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'widgets/common.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final etat = AppState();
  etat.restaurer();
  runApp(ChangeNotifierProvider.value(value: etat, child: const KilimaApp()));
}

class KilimaApp extends StatelessWidget {
  const KilimaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Kilima Terrain',
      debugShowCheckedModeBanner: false,
      locale: const Locale('fr'),
      supportedLocales: const [Locale('fr')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
            seedColor: couleurKilima, primary: couleurKilima),
        appBarTheme: const AppBarTheme(
          backgroundColor: couleurKilima,
          foregroundColor: Colors.white,
        ),
        floatingActionButtonTheme: const FloatingActionButtonThemeData(
          backgroundColor: couleurKilima,
          foregroundColor: Colors.white,
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(backgroundColor: couleurKilima),
        ),
      ),
      home: const _Portier(),
    );
  }
}

/// Aiguillage : restauration de session → connexion → accueil.
class _Portier extends StatelessWidget {
  const _Portier();

  @override
  Widget build(BuildContext context) {
    final etat = context.watch<AppState>();
    if (!etat.pret) {
      return const Scaffold(
          body: Center(child: CircularProgressIndicator()));
    }
    return etat.connecte ? const HomeScreen() : const LoginScreen();
  }
}
