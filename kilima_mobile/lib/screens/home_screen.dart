import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../app_state.dart';
import '../widgets/common.dart';
import 'maintenance_screen.dart';
import 'requisitions_screen.dart';

/// Accueil : compteurs du GET /api/dashboard?societe_id= + accès aux modules.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  Map<String, dynamic>? compteurs;
  bool chargement = true;
  Object? erreur;
  String? _societeChargee;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final sid = context.watch<AppState>().societeActive?.id;
    if (sid != null && sid != _societeChargee) {
      _societeChargee = sid;
      _charger();
    }
  }

  Future<void> _charger() async {
    final etat = context.read<AppState>();
    final sid = etat.societeActive?.id;
    if (sid == null) return;
    setState(() {
      chargement = compteurs == null;
      erreur = null;
    });
    try {
      final r = await etat.api.get('/api/dashboard', {'societe_id': sid});
      if (mounted) setState(() => compteurs = Map<String, dynamic>.from(r));
    } catch (e) {
      if (mounted) setState(() => erreur = e);
    } finally {
      if (mounted) setState(() => chargement = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final etat = context.watch<AppState>();
    final societe = etat.societeActive;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Kilima Terrain'),
        actions: [
          IconButton(
            tooltip: 'Se déconnecter',
            icon: const Icon(Icons.logout),
            onPressed: () async {
              if (await confirmer(context, 'Déconnexion',
                  'Fermer la session ${etat.nomUtilisateur} ?',
                  bouton: 'Se déconnecter')) {
                await etat.deconnecter();
              }
            },
          ),
        ],
      ),
      body: CorpsAsync(
        chargement: chargement && compteurs == null,
        erreur: compteurs == null ? erreur : null,
        surRafraichir: _charger,
        constructeur: () => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // ── Sélecteur de société ──
            Card(
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                child: Row(
                  children: [
                    const Icon(Icons.business, color: couleurKilima),
                    const SizedBox(width: 12),
                    Expanded(
                      child: DropdownButtonHideUnderline(
                        child: DropdownButton<String>(
                          isExpanded: true,
                          value: societe?.id,
                          items: etat.societes
                              .map((s) => DropdownMenuItem(
                                  value: s.id,
                                  child: Text('${s.nom} (${s.code})',
                                      overflow: TextOverflow.ellipsis)))
                              .toList(),
                          onChanged: (id) {
                            final s =
                                etat.societes.firstWhere((x) => x.id == id);
                            etat.choisirSociete(s);
                          },
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            if (etat.rolesActifs.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4, left: 4),
                child: Text(
                    '${etat.nomUtilisateur} — ${etat.rolesActifs.join(', ')}',
                    style: const TextStyle(color: Colors.grey, fontSize: 12)),
              ),
            const SizedBox(height: 16),
            // ── Compteurs ──
            Text('Décaissements',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              childAspectRatio: 2.1,
              crossAxisSpacing: 10,
              mainAxisSpacing: 10,
              children: [
                _tuile('Réquisitions soumises',
                    compteurs?['requisitions_soumises'], Icons.description),
                _tuile('Ordres à valider', compteurs?['ordres_a_valider'],
                    Icons.fact_check),
                _tuile('Avances en cours', compteurs?['avances_en_cours'],
                    Icons.hourglass_top),
                _tuile('Avances en retard', compteurs?['avances_en_retard'],
                    Icons.warning_amber,
                    alerte: ((compteurs?['avances_en_retard'] ?? 0) as num) > 0),
                _tuile(
                    'Montant des avances',
                    fmtMontant((compteurs?['avances_montant_usd'] ?? 0) as num),
                    Icons.payments),
                _tuile(
                    'Bénéficiaires bloqués',
                    compteurs?['beneficiaires_bloques'],
                    Icons.block,
                    alerte:
                        ((compteurs?['beneficiaires_bloques'] ?? 0) as num) >
                            0),
              ],
            ),
            const SizedBox(height: 20),
            Text('Modules', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            _module(context, Icons.receipt_long, 'Réquisitions',
                'Demandes de fonds, validations du circuit, échanges',
                const RequisitionsScreen()),
            _module(context, Icons.build, 'Maintenance',
                'Interventions, fiche d\'atelier, pièces de rechange',
                const MaintenanceScreen()),
          ],
        ),
      ),
    );
  }

  Widget _tuile(String libelle, Object? valeur, IconData icone,
      {bool alerte = false}) {
    return Card(
      color: alerte ? Colors.red.shade50 : null,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            Icon(icone,
                color: alerte ? Colors.red.shade700 : couleurKilima, size: 28),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Text('${valeur ?? '—'}',
                        style: TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.bold,
                            color: alerte
                                ? Colors.red.shade700
                                : couleurKilima)),
                  ),
                  Text(libelle,
                      style:
                          const TextStyle(fontSize: 11, color: Colors.grey),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _module(BuildContext context, IconData icone, String titre,
      String description, Widget ecran) {
    return Card(
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: couleurKilima,
          child: Icon(icone, color: Colors.white),
        ),
        title: Text(titre),
        subtitle: Text(description, style: const TextStyle(fontSize: 12)),
        trailing: const Icon(Icons.chevron_right),
        onTap: () async {
          await Navigator.push(
              context, MaterialPageRoute(builder: (_) => ecran));
          _charger(); // les compteurs reflètent ce qui vient d'être fait
        },
      ),
    );
  }
}
