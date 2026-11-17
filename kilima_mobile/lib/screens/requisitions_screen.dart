import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../app_state.dart';
import '../widgets/common.dart';
import 'requisition_detail_screen.dart';

/// Liste des réquisitions (GET /api/requisitions?societe_id=) + création.
class RequisitionsScreen extends StatefulWidget {
  const RequisitionsScreen({super.key});

  @override
  State<RequisitionsScreen> createState() => _RequisitionsScreenState();
}

class _RequisitionsScreenState extends State<RequisitionsScreen> {
  List lignes = [];
  bool chargement = true;
  Object? erreur;
  String? filtreStatut;

  static const filtres = {
    null: 'Toutes',
    'soumise': 'Soumises',
    'en_attente_info': 'Précisions demandées',
    'demande_validee': 'Validées',
    'transformee': 'Transformées',
    'rejetee': 'Rejetées',
  };

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
      chargement = lignes.isEmpty;
      erreur = null;
    });
    try {
      final r = await etat.api.get('/api/requisitions', {
        'societe_id': sid,
        if (filtreStatut != null) 'statut': filtreStatut!,
      });
      if (mounted) setState(() => lignes = r as List);
    } catch (e) {
      if (mounted) setState(() => erreur = e);
    } finally {
      if (mounted) setState(() => chargement = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Réquisitions')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () async {
          final creee = await Navigator.push<bool>(context,
              MaterialPageRoute(builder: (_) => const RequisitionCreateScreen()));
          if (creee == true) _charger();
        },
        icon: const Icon(Icons.add),
        label: const Text('Nouvelle'),
      ),
      body: Column(
        children: [
          SizedBox(
            height: 52,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              children: filtres.entries
                  .map((e) => Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: ChoiceChip(
                          label: Text(e.value),
                          selected: filtreStatut == e.key,
                          onSelected: (_) {
                            setState(() => filtreStatut = e.key);
                            _charger();
                          },
                        ),
                      ))
                  .toList(),
            ),
          ),
          Expanded(
            child: CorpsAsync(
              chargement: chargement,
              erreur: lignes.isEmpty ? erreur : null,
              surRafraichir: _charger,
              constructeur: () => lignes.isEmpty
                  ? ListView(children: const [
                      SizedBox(height: 120),
                      Center(child: Text('Aucune réquisition.'))
                    ])
                  : ListView.builder(
                      padding: const EdgeInsets.only(bottom: 88),
                      itemCount: lignes.length,
                      itemBuilder: (ctx, i) {
                        final r = lignes[i] as Map;
                        final prog = (r['progression'] ?? {}) as Map;
                        return Card(
                          margin: const EdgeInsets.symmetric(
                              horizontal: 12, vertical: 4),
                          child: ListTile(
                            title: Text('${r['numero']} — ${r['objet']}',
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis),
                            subtitle: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(fmtMontant(
                                    r['montant_total_usd'] as num?,
                                    'USD')),
                                if ((prog['label'] ?? '') != '')
                                  Text('${prog['label']}',
                                      style: const TextStyle(fontSize: 11)),
                                if (((r['nb_commentaires'] ?? 0) as num) > 0)
                                  Text(
                                      '${r['nb_commentaires']} échange(s)',
                                      style: const TextStyle(
                                          fontSize: 11,
                                          color: couleurKilima)),
                              ],
                            ),
                            trailing: StatutChip('${r['statut']}'),
                            onTap: () async {
                              await Navigator.push(
                                  context,
                                  MaterialPageRoute(
                                      builder: (_) =>
                                          RequisitionDetailScreen(
                                              id: '${r['id']}',
                                              estInitiateur:
                                                  r['est_initiateur'] ==
                                                      true)));
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

/// Création : POST /api/requisitions
/// {societe_id, objet, justification?, priorite, devise, mode_decaissement,
///  nature, lignes: [{description, quantite, prix_unitaire, unite?}]}
class RequisitionCreateScreen extends StatefulWidget {
  const RequisitionCreateScreen({super.key});

  @override
  State<RequisitionCreateScreen> createState() =>
      _RequisitionCreateScreenState();
}

class _LigneSaisie {
  final description = TextEditingController();
  final quantite = TextEditingController(text: '1');
  final prix = TextEditingController();
  final unite = TextEditingController();
}

class _RequisitionCreateScreenState extends State<RequisitionCreateScreen> {
  final _objet = TextEditingController();
  final _justification = TextEditingController();
  String devise = 'USD';
  String priorite = 'normal';
  String modeDecaissement = 'avance';
  String nature = 'charge';
  final List<_LigneSaisie> lignes = [_LigneSaisie()];
  bool envoi = false;

  double get total => lignes.fold(0.0, (somme, l) {
        final q = double.tryParse(l.quantite.text.replaceAll(',', '.')) ?? 0;
        final p = double.tryParse(l.prix.text.replaceAll(',', '.')) ?? 0;
        return somme + q * p;
      });

  Future<void> _soumettre() async {
    final etat = context.read<AppState>();
    final sid = etat.societeActive?.id;
    if (sid == null) return;
    if (_objet.text.trim().isEmpty) {
      montrerErreur(context, 'L\'objet est requis.');
      return;
    }
    final corps = <Map<String, dynamic>>[];
    for (final l in lignes) {
      if (l.description.text.trim().isEmpty) continue;
      corps.add({
        'description': l.description.text.trim(),
        'quantite':
            double.tryParse(l.quantite.text.replaceAll(',', '.')) ?? 1,
        'prix_unitaire':
            double.tryParse(l.prix.text.replaceAll(',', '.')) ?? 0,
        if (l.unite.text.trim().isNotEmpty) 'unite': l.unite.text.trim(),
      });
    }
    if (corps.isEmpty) {
      montrerErreur(context, 'Ajoutez au moins une ligne avec description.');
      return;
    }
    setState(() => envoi = true);
    try {
      final r = await etat.api.post('/api/requisitions', {
        'societe_id': sid,
        'objet': _objet.text.trim(),
        if (_justification.text.trim().isNotEmpty)
          'justification': _justification.text.trim(),
        'priorite': priorite,
        'devise': devise,
        'mode_decaissement': modeDecaissement,
        'nature': nature,
        'lignes': corps,
      });
      if (mounted) {
        montrerSucces(context, 'Réquisition ${r['numero']} soumise.');
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
      appBar: AppBar(title: const Text('Nouvelle réquisition')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _objet,
            decoration: const InputDecoration(
                labelText: 'Objet *', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _justification,
            maxLines: 2,
            decoration: const InputDecoration(
                labelText: 'Justification', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: devise,
                  decoration: const InputDecoration(
                      labelText: 'Devise', border: OutlineInputBorder()),
                  items: const [
                    DropdownMenuItem(value: 'USD', child: Text('USD')),
                    DropdownMenuItem(value: 'CDF', child: Text('CDF')),
                  ],
                  onChanged: (v) => setState(() => devise = v!),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: priorite,
                  decoration: const InputDecoration(
                      labelText: 'Priorité', border: OutlineInputBorder()),
                  items: const [
                    DropdownMenuItem(value: 'normal', child: Text('Normale')),
                    DropdownMenuItem(value: 'urgent', child: Text('Urgente')),
                  ],
                  onChanged: (v) => setState(() => priorite = v!),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: modeDecaissement,
                  decoration: const InputDecoration(
                      labelText: 'Mode de décaissement',
                      border: OutlineInputBorder()),
                  items: const [
                    DropdownMenuItem(
                        value: 'avance', child: Text('Avance à justifier')),
                    DropdownMenuItem(
                        value: 'paiement_direct',
                        child: Text('Paiement sur justificatif')),
                  ],
                  onChanged: (v) => setState(() => modeDecaissement = v!),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: nature,
                  decoration: const InputDecoration(
                      labelText: 'Nature', border: OutlineInputBorder()),
                  items: const [
                    DropdownMenuItem(value: 'charge', child: Text('Charge')),
                    DropdownMenuItem(
                        value: 'marchandise', child: Text('Marchandise')),
                  ],
                  onChanged: (v) => setState(() => nature = v!),
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          Text('Lignes', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          ...lignes.asMap().entries.map((e) => Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: TextField(
                              controller: e.value.description,
                              decoration: InputDecoration(
                                  labelText: 'Description ${e.key + 1} *',
                                  border: const OutlineInputBorder(),
                                  isDense: true),
                              onChanged: (_) => setState(() {}),
                            ),
                          ),
                          if (lignes.length > 1)
                            IconButton(
                              icon: const Icon(Icons.delete_outline,
                                  color: Colors.red),
                              onPressed: () =>
                                  setState(() => lignes.removeAt(e.key)),
                            ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(
                            child: TextField(
                              controller: e.value.quantite,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                      decimal: true),
                              decoration: const InputDecoration(
                                  labelText: 'Quantité',
                                  border: OutlineInputBorder(),
                                  isDense: true),
                              onChanged: (_) => setState(() {}),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: TextField(
                              controller: e.value.prix,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                      decimal: true),
                              decoration: const InputDecoration(
                                  labelText: 'Prix unitaire',
                                  border: OutlineInputBorder(),
                                  isDense: true),
                              onChanged: (_) => setState(() {}),
                            ),
                          ),
                          const SizedBox(width: 8),
                          SizedBox(
                            width: 80,
                            child: TextField(
                              controller: e.value.unite,
                              decoration: const InputDecoration(
                                  labelText: 'Unité',
                                  border: OutlineInputBorder(),
                                  isDense: true),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              )),
          OutlinedButton.icon(
            onPressed: () => setState(() => lignes.add(_LigneSaisie())),
            icon: const Icon(Icons.add),
            label: const Text('Ajouter une ligne'),
          ),
          const SizedBox(height: 16),
          Text('Total : ${fmtMontant(total, devise)}',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(color: couleurKilima)),
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
                  : const Icon(Icons.send),
              label: const Text('Soumettre la réquisition'),
            ),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
