import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../app_state.dart';
import '../widgets/common.dart';
import 'intervention_detail_screen.dart';

/// Interventions d'atelier : GET /api/transport/interventions?societe_id=
/// (camions et engins confondus) + signalement d'une nouvelle intervention.
class MaintenanceScreen extends StatefulWidget {
  const MaintenanceScreen({super.key});

  @override
  State<MaintenanceScreen> createState() => _MaintenanceScreenState();
}

class _MaintenanceScreenState extends State<MaintenanceScreen> {
  List interventions = [];
  bool chargement = true;
  Object? erreur;
  String? filtre; // null | planifiee | en_cours | terminee

  @override
  void initState() {
    super.initState();
    _charger();
  }

  Future<void> _charger() async {
    final etat = context.read<AppState>();
    final sid = etat.societeActive?.id;
    if (sid == null) return;
    setState(() {
      chargement = interventions.isEmpty;
      erreur = null;
    });
    try {
      final r = await etat.api
          .get('/api/transport/interventions', {'societe_id': sid});
      if (mounted) setState(() => interventions = r as List);
    } catch (e) {
      if (mounted) setState(() => erreur = e);
    } finally {
      if (mounted) setState(() => chargement = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final visibles = filtre == null
        ? interventions
        : interventions.where((i) => (i as Map)['statut'] == filtre).toList();
    return Scaffold(
      appBar: AppBar(title: const Text('Maintenance')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () async {
          final creee = await Navigator.push<bool>(
              context,
              MaterialPageRoute(
                  builder: (_) => const InterventionCreateScreen()));
          if (creee == true) _charger();
        },
        icon: const Icon(Icons.add),
        label: const Text('Signaler'),
      ),
      body: Column(
        children: [
          SizedBox(
            height: 52,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              children: const {
                null: 'Toutes',
                'planifiee': 'Planifiées',
                'en_cours': 'En cours',
                'terminee': 'Terminées',
              }
                  .entries
                  .map((e) => Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: ChoiceChip(
                          label: Text(e.value),
                          selected: filtre == e.key,
                          onSelected: (_) => setState(() => filtre = e.key),
                        ),
                      ))
                  .toList(),
            ),
          ),
          Expanded(
            child: CorpsAsync(
              chargement: chargement,
              erreur: interventions.isEmpty ? erreur : null,
              surRafraichir: _charger,
              constructeur: () => visibles.isEmpty
                  ? ListView(children: const [
                      SizedBox(height: 120),
                      Center(child: Text('Aucune intervention.'))
                    ])
                  : ListView.builder(
                      padding: const EdgeInsets.only(bottom: 88),
                      itemCount: visibles.length,
                      itemBuilder: (ctx, i) {
                        final m = visibles[i] as Map;
                        return Card(
                          margin: const EdgeInsets.symmetric(
                              horizontal: 12, vertical: 4),
                          child: ListTile(
                            leading: Icon(
                                m['cible'] == 'engin'
                                    ? Icons.agriculture
                                    : Icons.local_shipping,
                                color: couleurKilima),
                            title: Text(
                                '${m['numero']} — ${m['vehicule'] ?? '—'}'),
                            subtitle: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('${m['description'] ?? ''}',
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis),
                                Text(
                                    '${m['type'] ?? ''} · priorité ${m['priorite'] ?? 'normale'}'
                                    '${m['immobilise'] == true ? ' · immobilisé' : ''}',
                                    style: const TextStyle(
                                        fontSize: 11, color: Colors.grey)),
                              ],
                            ),
                            trailing: StatutChip('${m['statut']}'),
                            onTap: () async {
                              await Navigator.push(
                                  context,
                                  MaterialPageRoute(
                                      builder: (_) =>
                                          InterventionDetailScreen(
                                              id: '${m['id']}')));
                              _charger();
                            },
                          ),
                        );
                      },
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Signalement : POST /api/transport/interventions
/// {camion_id|engin_id, type, description, priorite, technicien?, immobilise,
///  date_prevue?, cout_estime?} — le véhicule vient de GET /api/maintenance/parc.
class InterventionCreateScreen extends StatefulWidget {
  const InterventionCreateScreen({super.key});

  @override
  State<InterventionCreateScreen> createState() =>
      _InterventionCreateScreenState();
}

class _InterventionCreateScreenState extends State<InterventionCreateScreen> {
  List vehicules = [];
  Map? vehicule;
  String type = 'reparation';
  String priorite = 'normale';
  bool immobilise = true;
  DateTime? datePrevue;
  final _description = TextEditingController();
  final _technicien = TextEditingController();
  final _coutEstime = TextEditingController();
  bool chargement = true;
  Object? erreur;
  bool envoi = false;

  @override
  void initState() {
    super.initState();
    _chargerParc();
  }

  Future<void> _chargerParc() async {
    final etat = context.read<AppState>();
    final sid = etat.societeActive?.id;
    if (sid == null) return;
    setState(() {
      chargement = true;
      erreur = null;
    });
    try {
      final r = await etat.api.get('/api/maintenance/parc', {'societe_id': sid});
      if (mounted) {
        setState(() => vehicules = (r['vehicules'] as List?) ?? []);
      }
    } catch (e) {
      if (mounted) setState(() => erreur = e);
    } finally {
      if (mounted) setState(() => chargement = false);
    }
  }

  Future<void> _soumettre() async {
    final etat = context.read<AppState>();
    final sid = etat.societeActive?.id;
    if (sid == null) return;
    if (vehicule == null) {
      montrerErreur(context, 'Choisissez un véhicule ou un engin.');
      return;
    }
    if (_description.text.trim().length < 3) {
      montrerErreur(context, 'Décrivez le problème (3 caractères minimum).');
      return;
    }
    setState(() => envoi = true);
    try {
      final cle = vehicule!['type'] == 'engin' ? 'engin_id' : 'camion_id';
      final r = await etat.api.post('/api/transport/interventions', {
        cle: vehicule!['id'],
        'type': type,
        'description': _description.text.trim(),
        'priorite': priorite,
        'immobilise': immobilise,
        if (_technicien.text.trim().isNotEmpty)
          'technicien': _technicien.text.trim(),
        if (_coutEstime.text.trim().isNotEmpty)
          'cout_estime':
              double.tryParse(_coutEstime.text.replaceAll(',', '.')),
        if (datePrevue != null)
          'date_prevue':
              '${datePrevue!.year}-${datePrevue!.month.toString().padLeft(2, '0')}-${datePrevue!.day.toString().padLeft(2, '0')}',
      }, {
        'societe_id': sid
      });
      if (mounted) {
        montrerSucces(context, 'Intervention ${r['numero']} créée.');
        Navigator.pop(context, true);
      }
    } catch (e) {
      if (mounted) montrerErreur(context, e);
    } finally {
      if (mounted) setState(() => envoi = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Signaler une intervention')),
      body: CorpsAsync(
        chargement: chargement,
        erreur: erreur,
        surRafraichir: _chargerParc,
        constructeur: () => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            DropdownButtonFormField<Map>(
              initialValue: vehicule,
              isExpanded: true,
              decoration: const InputDecoration(
                  labelText: 'Véhicule / engin *',
                  border: OutlineInputBorder()),
              items: vehicules
                  .map<DropdownMenuItem<Map>>((v) => DropdownMenuItem(
                        value: v as Map,
                        child: Text(
                            '${v['nom']}${v['detail'] != null ? ' — ${v['detail']}' : ''}'
                            ' (${v['type'] == 'engin' ? 'engin' : 'camion'}, ${v['statut']})',
                            overflow: TextOverflow.ellipsis),
                      ))
                  .toList(),
              onChanged: (v) => setState(() => vehicule = v),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: type,
              decoration: const InputDecoration(
                  labelText: 'Type', border: OutlineInputBorder()),
              items: const [
                DropdownMenuItem(
                    value: 'reparation', child: Text('Réparation')),
                DropdownMenuItem(value: 'entretien', child: Text('Entretien')),
              ],
              onChanged: (v) => setState(() => type = v!),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _description,
              maxLines: 3,
              decoration: const InputDecoration(
                  labelText: 'Description du problème *',
                  border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: priorite,
              decoration: const InputDecoration(
                  labelText: 'Priorité', border: OutlineInputBorder()),
              items: const [
                DropdownMenuItem(value: 'basse', child: Text('Basse')),
                DropdownMenuItem(value: 'normale', child: Text('Normale')),
                DropdownMenuItem(value: 'haute', child: Text('Haute')),
                DropdownMenuItem(value: 'urgente', child: Text('Urgente')),
              ],
              onChanged: (v) => setState(() => priorite = v!),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _technicien,
              decoration: const InputDecoration(
                  labelText: 'Mécanicien / technicien',
                  border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _coutEstime,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: 'Coût estimé (USD)',
                  border: OutlineInputBorder()),
            ),
            SwitchListTile(
              title: const Text('Immobiliser le véhicule'),
              subtitle: const Text(
                  'Le véhicule passe « immobilisé » au démarrage des travaux.'),
              value: immobilise,
              onChanged: (v) => setState(() => immobilise = v),
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(datePrevue == null
                  ? 'Commencer immédiatement'
                  : 'Planifiée pour le ${datePrevue!.day}/${datePrevue!.month}/${datePrevue!.year}'),
              subtitle:
                  const Text('Choisir une date future pour planifier.'),
              trailing: IconButton(
                icon: const Icon(Icons.event, color: couleurKilima),
                onPressed: () async {
                  final d = await showDatePicker(
                    context: context,
                    initialDate: DateTime.now().add(const Duration(days: 1)),
                    firstDate: DateTime.now(),
                    lastDate: DateTime.now().add(const Duration(days: 365)),
                  );
                  setState(() => datePrevue = d);
                },
              ),
            ),
            const SizedBox(height: 16),
            SizedBox(
              height: 48,
              child: FilledButton.icon(
                onPressed: envoi ? null : _soumettre,
                icon: envoi
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Icon(Icons.build),
                label: const Text('Créer l\'intervention'),
              ),
            ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }
}
