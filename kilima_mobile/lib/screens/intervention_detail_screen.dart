import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../app_state.dart';
import '../widgets/common.dart';
import '../widgets/pieces_jointes.dart';

/// Fiche d'atelier d'une intervention : checklist, démarrage/clôture,
/// demande d'achat de pièces (réquisition) et bon de consommation du stock.
class InterventionDetailScreen extends StatefulWidget {
  final String id;
  const InterventionDetailScreen({super.key, required this.id});

  @override
  State<InterventionDetailScreen> createState() =>
      _InterventionDetailScreenState();
}

class _InterventionDetailScreenState extends State<InterventionDetailScreen> {
  Map<String, dynamic>? fiche;
  bool chargement = true;
  Object? erreur;
  bool action = false;

  @override
  void initState() {
    super.initState();
    _charger();
  }

  /// L'API n'a pas de GET détail : on relit la liste et on filtre.
  Future<void> _charger() async {
    final etat = context.read<AppState>();
    final sid = etat.societeActive?.id;
    if (sid == null) return;
    setState(() {
      chargement = fiche == null;
      erreur = null;
    });
    try {
      final liste = await etat.api
          .get('/api/transport/interventions', {'societe_id': sid}) as List;
      final trouvee = liste.cast<Map>().firstWhere(
          (i) => '${i['id']}' == widget.id,
          orElse: () => const {});
      if (mounted) {
        setState(() => fiche =
            trouvee.isEmpty ? null : Map<String, dynamic>.from(trouvee));
        if (trouvee.isEmpty) erreur = 'Intervention introuvable.';
      }
    } catch (e) {
      if (mounted) setState(() => erreur = e);
    } finally {
      if (mounted) setState(() => chargement = false);
    }
  }

  bool get modifiable => fiche != null && fiche!['statut'] != 'terminee';

  Future<void> _patch(Map<String, dynamic> corps, [String? succes]) async {
    setState(() => action = true);
    try {
      final r = await context
          .read<AppState>()
          .api
          .patch('/api/transport/interventions/${widget.id}', corps);
      if (mounted) {
        setState(() => fiche = Map<String, dynamic>.from(r));
        if (succes != null) montrerSucces(context, succes);
      }
    } catch (e) {
      if (mounted) montrerErreur(context, e);
    } finally {
      if (mounted) setState(() => action = false);
    }
  }

  Future<void> _demarrer() async {
    final api = context.read<AppState>().api;
    if (!await confirmer(context, 'Démarrer les travaux',
        'Démarrer cette intervention planifiée ?', bouton: 'Démarrer')) {
      return;
    }
    setState(() => action = true);
    try {
      final r =
          await api.post('/api/transport/interventions/${widget.id}/demarrer');
      if (mounted) {
        setState(() => fiche = Map<String, dynamic>.from(r));
        montrerSucces(context, 'Intervention démarrée.');
      }
    } catch (e) {
      if (mounted) montrerErreur(context, e);
    } finally {
      if (mounted) setState(() => action = false);
    }
  }

  Future<void> _terminer() async {
    final api = context.read<AppState>().api;
    final compteur = TextEditingController(
        text: fiche?['compteur'] == null ? '' : '${fiche!['compteur']}');
    final coutReel = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Terminer l\'intervention'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
                'Le véhicule sera remis en service si plus rien ne l\'immobilise. '
                'Sans coût réel saisi, il sera calculé depuis les dépenses '
                'justifiées et les pièces sorties du stock.'),
            const SizedBox(height: 12),
            TextField(
              controller: compteur,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: 'Relevé compteur (km / h)',
                  border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: coutReel,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: 'Coût réel USD (facultatif)',
                  border: OutlineInputBorder()),
            ),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Annuler')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Terminer')),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => action = true);
    try {
      final corps = <String, dynamic>{
        if (compteur.text.trim().isNotEmpty)
          'compteur': double.tryParse(compteur.text.replaceAll(',', '.')),
        if (coutReel.text.trim().isNotEmpty)
          'cout_reel': double.tryParse(coutReel.text.replaceAll(',', '.')),
      };
      final r = await api.post(
          '/api/transport/interventions/${widget.id}/terminer', corps);
      if (mounted) {
        setState(() => fiche = Map<String, dynamic>.from(r));
        montrerSucces(context, 'Intervention terminée, véhicule remis en service.');
      }
    } catch (e) {
      if (mounted) montrerErreur(context, e);
    } finally {
      if (mounted) setState(() => action = false);
    }
  }

  // ── Checklist ──
  Future<void> _basculerTache(int index, bool ok) async {
    final liste = List<Map<String, dynamic>>.from(
        ((fiche?['checklist'] as List?) ?? [])
            .map((t) => Map<String, dynamic>.from(t as Map)));
    liste[index]['ok'] = ok;
    await _patch({'checklist': liste});
  }

  Future<void> _ajouterTache() async {
    final ctrl = TextEditingController();
    final texte = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Nouvelle tâche'),
        content: TextField(
            controller: ctrl,
            autofocus: true,
            decoration: const InputDecoration(
                labelText: 'Tâche à faire', border: OutlineInputBorder())),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Annuler')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
              child: const Text('Ajouter')),
        ],
      ),
    );
    if (texte == null || texte.isEmpty) return;
    final liste = List<Map<String, dynamic>>.from(
        ((fiche?['checklist'] as List?) ?? [])
            .map((t) => Map<String, dynamic>.from(t as Map)));
    liste.add({'t': texte, 'ok': false});
    await _patch({'checklist': liste}, 'Tâche ajoutée.');
  }

  Future<void> _supprimerTache(int index) async {
    final liste = List<Map<String, dynamic>>.from(
        ((fiche?['checklist'] as List?) ?? [])
            .map((t) => Map<String, dynamic>.from(t as Map)));
    liste.removeAt(index);
    await _patch({'checklist': liste});
  }

  Future<void> _modifierChamp(
      String champ, String libelle, String? valeurActuelle,
      {bool numerique = false}) async {
    final ctrl = TextEditingController(text: valeurActuelle ?? '');
    final texte = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(libelle),
        content: TextField(
            controller: ctrl,
            autofocus: true,
            keyboardType: numerique
                ? const TextInputType.numberWithOptions(decimal: true)
                : null,
            decoration: InputDecoration(
                labelText: libelle, border: const OutlineInputBorder())),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Annuler')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
              child: const Text('Enregistrer')),
        ],
      ),
    );
    if (texte == null) return;
    await _patch({
      champ: numerique
          ? (texte.isEmpty ? null : double.tryParse(texte.replaceAll(',', '.')))
          : texte
    }, 'Fiche mise à jour.');
  }

  @override
  Widget build(BuildContext context) {
    final f = fiche;
    final statut = '${f?['statut'] ?? ''}';
    final checklist = (f?['checklist'] as List?) ?? const [];
    final faites = checklist.where((t) => (t as Map)['ok'] == true).length;
    return Scaffold(
      appBar: AppBar(title: Text(f == null ? 'Intervention' : '${f['numero']}')),
      body: CorpsAsync(
        chargement: chargement,
        erreur: fiche == null ? erreur : null,
        surRafraichir: _charger,
        constructeur: () => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Row(
              children: [
                Icon(
                    f!['cible'] == 'engin'
                        ? Icons.agriculture
                        : Icons.local_shipping,
                    color: couleurKilima,
                    size: 32),
                const SizedBox(width: 10),
                Expanded(
                  child: Text('${f['vehicule'] ?? '—'}',
                      style: Theme.of(context).textTheme.titleLarge),
                ),
                StatutChip(statut),
              ],
            ),
            const SizedBox(height: 6),
            Text('${f['description'] ?? ''}'),
            const SizedBox(height: 4),
            Text(
                '${f['type']} · signalée le ${fmtDate('${f['date_signalement'] ?? ''}')}'
                '${f['date_prevue'] != null ? ' · prévue le ${fmtDate('${f['date_prevue']}')}' : ''}'
                '${f['immobilise'] == true ? ' · véhicule immobilisé' : ''}',
                style: const TextStyle(color: Colors.grey, fontSize: 12)),
            const Divider(height: 24),
            // ── Fiche modifiable ──
            _ligneModifiable('Priorité', '${f['priorite'] ?? 'normale'}',
                modifiable: modifiable, surModif: () async {
              final v = await showDialog<String>(
                context: context,
                builder: (ctx) => SimpleDialog(
                  title: const Text('Priorité'),
                  children: ['basse', 'normale', 'haute', 'urgente']
                      .map((p) => SimpleDialogOption(
                          onPressed: () => Navigator.pop(ctx, p),
                          child: Text(p)))
                      .toList(),
                ),
              );
              if (v != null) await _patch({'priorite': v});
            }),
            _ligneModifiable('Mécanicien', '${f['technicien'] ?? '—'}',
                modifiable: modifiable,
                surModif: () => _modifierChamp('technicien', 'Mécanicien',
                    f['technicien'] == null ? '' : '${f['technicien']}')),
            _ligneModifiable(
                'Compteur',
                f['compteur'] == null ? '—' : '${f['compteur']}',
                modifiable: modifiable,
                surModif: () => _modifierChamp('compteur', 'Relevé compteur',
                    f['compteur'] == null ? '' : '${f['compteur']}',
                    numerique: true)),
            _ligneModifiable('Coût estimé',
                fmtMontant(f['cout_estime'] as num?),
                modifiable: modifiable,
                surModif: () => _modifierChamp('cout_estime',
                    'Coût estimé (USD)',
                    f['cout_estime'] == null ? '' : '${f['cout_estime']}',
                    numerique: true)),
            _ligneModifiable('Coût pièces (stock)',
                fmtMontant(f['cout_pieces'] as num?),
                modifiable: false),
            if (statut == 'terminee')
              _ligneModifiable(
                  'Coût réel', fmtMontant(f['cout_reel'] as num?),
                  modifiable: false),
            if (f['requisitions'] != null &&
                (f['requisitions'] as List).isNotEmpty) ...[
              const SizedBox(height: 6),
              const Text('Réquisitions de pièces liées :',
                  style: TextStyle(color: Colors.grey)),
              ...(f['requisitions'] as List).map((r) => Text(
                  '• ${(r as Map)['numero']} — ${libelleStatut('${r['statut']}')} — ${fmtMontant(r['montant_usd'] as num?)}')),
            ],
            const Divider(height: 24),
            // ── Checklist ──
            Row(
              children: [
                Text('Liste de tâches',
                    style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(width: 8),
                if (checklist.isNotEmpty)
                  Text('$faites/${checklist.length}',
                      style: const TextStyle(color: couleurKilima)),
                const Spacer(),
                if (modifiable)
                  IconButton(
                      onPressed: action ? null : _ajouterTache,
                      icon:
                          const Icon(Icons.add_task, color: couleurKilima)),
              ],
            ),
            if (checklist.isEmpty)
              const Text('Aucune tâche.', style: TextStyle(color: Colors.grey))
            else
              ...checklist.asMap().entries.map((e) {
                final t = e.value as Map;
                return CheckboxListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  value: t['ok'] == true,
                  onChanged: modifiable && !action
                      ? (v) => _basculerTache(e.key, v == true)
                      : null,
                  title: Text('${t['t']}',
                      style: t['ok'] == true
                          ? const TextStyle(
                              decoration: TextDecoration.lineThrough,
                              color: Colors.grey)
                          : null),
                  secondary: modifiable
                      ? IconButton(
                          icon: const Icon(Icons.delete_outline, size: 20),
                          onPressed:
                              action ? null : () => _supprimerTache(e.key),
                        )
                      : null,
                );
              }),
            const Divider(height: 24),
            // ── Pièces de rechange ──
            if (modifiable) ...[
              Text('Pièces de rechange',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: action
                          ? null
                          : () async {
                              final fait = await Navigator.push<bool>(
                                  context,
                                  MaterialPageRoute(
                                      builder: (_) =>
                                          _DemandeAchatScreen(
                                              interventionId: widget.id)));
                              if (fait == true) _charger();
                            },
                      icon: const Icon(Icons.shopping_cart_outlined),
                      label: const Text('Demande d\'achat'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: action
                          ? null
                          : () async {
                              final fait = await Navigator.push<bool>(
                                  context,
                                  MaterialPageRoute(
                                      builder: (_) =>
                                          _BonConsommationScreen(
                                              interventionId: widget.id)));
                              if (fait == true) _charger();
                            },
                      icon: const Icon(Icons.inventory_2_outlined),
                      label: const Text('Sortie du stock'),
                    ),
                  ),
                ],
              ),
              const Divider(height: 24),
            ],
            PiecesJointesSection(
                documentType: 'intervention', documentId: widget.id),
            const SizedBox(height: 16),
            // ── Actions de statut ──
            if (action)
              const Center(child: CircularProgressIndicator())
            else if (statut == 'planifiee')
              FilledButton.icon(
                onPressed: _demarrer,
                icon: const Icon(Icons.play_arrow),
                label: const Text('Démarrer les travaux'),
              )
            else if (statut == 'en_cours')
              FilledButton.icon(
                onPressed: _terminer,
                icon: const Icon(Icons.task_alt),
                label: const Text('Terminer et remettre en service'),
              ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }

  Widget _ligneModifiable(String libelle, String valeur,
      {required bool modifiable, VoidCallback? surModif}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          SizedBox(
              width: 150,
              child:
                  Text(libelle, style: const TextStyle(color: Colors.grey))),
          Expanded(child: Text(valeur)),
          if (modifiable && surModif != null)
            InkWell(
              onTap: action ? null : surModif,
              child: const Padding(
                padding: EdgeInsets.all(4),
                child: Icon(Icons.edit, size: 18, color: couleurKilima),
              ),
            ),
        ],
      ),
    );
  }
}

/// Demande d'achat de pièces :
/// POST /api/maintenance/interventions/<id>/requisition
/// {lignes: [{description, quantite, prix_unitaire}], mode_decaissement?}
class _DemandeAchatScreen extends StatefulWidget {
  final String interventionId;
  const _DemandeAchatScreen({required this.interventionId});

  @override
  State<_DemandeAchatScreen> createState() => _DemandeAchatScreenState();
}

class _PieceSaisie {
  final description = TextEditingController();
  final quantite = TextEditingController(text: '1');
  final prix = TextEditingController();
}

class _DemandeAchatScreenState extends State<_DemandeAchatScreen> {
  final List<_PieceSaisie> pieces = [_PieceSaisie()];
  String modeDecaissement = 'avance';
  bool envoi = false;

  Future<void> _soumettre() async {
    final lignes = <Map<String, dynamic>>[];
    for (final p in pieces) {
      if (p.description.text.trim().length < 2) continue;
      lignes.add({
        'description': p.description.text.trim(),
        'quantite':
            double.tryParse(p.quantite.text.replaceAll(',', '.')) ?? 1,
        'prix_unitaire':
            double.tryParse(p.prix.text.replaceAll(',', '.')) ?? 0,
      });
    }
    if (lignes.isEmpty) {
      montrerErreur(context, 'Décrivez au moins une pièce.');
      return;
    }
    setState(() => envoi = true);
    try {
      final r = await context.read<AppState>().api.post(
          '/api/maintenance/interventions/${widget.interventionId}/requisition',
          {'lignes': lignes, 'mode_decaissement': modeDecaissement});
      if (mounted) {
        montrerSucces(context,
            'Réquisition ${r['requisition']?['numero'] ?? ''} soumise au circuit.');
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
      appBar: AppBar(title: const Text('Demande d\'achat de pièces')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text(
              'Génère une réquisition d\'achat liée à l\'intervention : elle '
              'suit le circuit de validation habituel et ses dépenses '
              'justifiées alimentent le coût réel.'),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
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
          const SizedBox(height: 16),
          ...pieces.asMap().entries.map((e) => Card(
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
                                  labelText: 'Pièce ${e.key + 1} *',
                                  border: const OutlineInputBorder(),
                                  isDense: true),
                            ),
                          ),
                          if (pieces.length > 1)
                            IconButton(
                                icon: const Icon(Icons.delete_outline,
                                    color: Colors.red),
                                onPressed: () =>
                                    setState(() => pieces.removeAt(e.key))),
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
                                  labelText: 'Prix unitaire USD',
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
            onPressed: () => setState(() => pieces.add(_PieceSaisie())),
            icon: const Icon(Icons.add),
            label: const Text('Ajouter une pièce'),
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
                  : const Icon(Icons.send),
              label: const Text('Soumettre la demande'),
            ),
          ),
        ],
      ),
    );
  }
}

/// Bon de consommation :
/// POST /api/maintenance/interventions/<id>/consommer
/// {depot_id?, lignes: [{article_id, qte}]} — articles gérés en stock
/// (GET /api/commercial/articles), dépôts (GET /api/stock/depots).
class _BonConsommationScreen extends StatefulWidget {
  final String interventionId;
  const _BonConsommationScreen({required this.interventionId});

  @override
  State<_BonConsommationScreen> createState() => _BonConsommationScreenState();
}

class _BonConsommationScreenState extends State<_BonConsommationScreen> {
  List articles = [];
  List depots = [];
  String? depotId;
  final Map<String, double> quantites = {}; // article_id → qte
  final _recherche = TextEditingController();
  bool chargement = true;
  Object? erreur;
  bool envoi = false;

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
      chargement = true;
      erreur = null;
    });
    try {
      final arts =
          await etat.api.get('/api/commercial/articles', {'societe_id': sid});
      final deps =
          await etat.api.get('/api/stock/depots', {'societe_id': sid});
      if (mounted) {
        setState(() {
          articles = (arts as List)
              .where((a) => (a as Map)['gere_stock'] == true)
              .toList();
          depots = deps is List ? deps : ((deps as Map)['depots'] ?? []);
        });
      }
    } catch (e) {
      if (mounted) setState(() => erreur = e);
    } finally {
      if (mounted) setState(() => chargement = false);
    }
  }

  Future<void> _soumettre() async {
    final lignes = quantites.entries
        .where((e) => e.value > 0)
        .map((e) => {'article_id': e.key, 'qte': e.value})
        .toList();
    if (lignes.isEmpty) {
      montrerErreur(context, 'Indiquez les quantités à sortir du stock.');
      return;
    }
    setState(() => envoi = true);
    try {
      final r = await context.read<AppState>().api.post(
          '/api/maintenance/interventions/${widget.interventionId}/consommer',
          {if (depotId != null) 'depot_id': depotId, 'lignes': lignes});
      if (mounted) {
        montrerSucces(context,
            'Bon ${r['bon']?['numero'] ?? ''} émis — stock décrémenté.');
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
    final filtre = _recherche.text.trim().toLowerCase();
    final visibles = filtre.isEmpty
        ? articles
        : articles
            .where((a) =>
                '${(a as Map)['code']}'.toLowerCase().contains(filtre) ||
                '${a['designation']}'.toLowerCase().contains(filtre))
            .toList();
    return Scaffold(
      appBar: AppBar(title: const Text('Sortie de stock (bon)')),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: FilledButton.icon(
            onPressed: envoi || chargement ? null : _soumettre,
            icon: envoi
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.receipt_long),
            label: Text(
                'Émettre le bon (${quantites.values.where((v) => v > 0).length} article(s))'),
          ),
        ),
      ),
      body: CorpsAsync(
        chargement: chargement,
        erreur: erreur,
        surRafraichir: _charger,
        constructeur: () => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (depots.isNotEmpty)
              DropdownButtonFormField<String>(
                initialValue: depotId,
                isExpanded: true,
                decoration: const InputDecoration(
                    labelText: 'Dépôt (central par défaut)',
                    border: OutlineInputBorder()),
                items: depots
                    .map<DropdownMenuItem<String>>((d) => DropdownMenuItem(
                        value: '${(d as Map)['id']}',
                        child: Text('${d['libelle'] ?? d['code'] ?? d['id']}',
                            overflow: TextOverflow.ellipsis)))
                    .toList(),
                onChanged: (v) => setState(() => depotId = v),
              ),
            const SizedBox(height: 12),
            TextField(
              controller: _recherche,
              decoration: const InputDecoration(
                  labelText: 'Rechercher une pièce',
                  prefixIcon: Icon(Icons.search),
                  border: OutlineInputBorder()),
              onChanged: (_) => setState(() {}),
            ),
            const SizedBox(height: 8),
            if (visibles.isEmpty)
              const Padding(
                padding: EdgeInsets.all(16),
                child: Text('Aucun article géré en stock.',
                    style: TextStyle(color: Colors.grey)),
              )
            else
              ...visibles.map((a) {
                final m = a as Map;
                final id = '${m['id']}';
                final qte = quantites[id] ?? 0;
                return Card(
                  margin: const EdgeInsets.only(bottom: 6),
                  child: ListTile(
                    title: Text('${m['code']} — ${m['designation']}'),
                    subtitle: Text(
                        'En stock : ${m['stock_qte'] ?? '?'} ${m['unite'] ?? ''}'),
                    trailing: SizedBox(
                      width: 130,
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.end,
                        children: [
                          IconButton(
                            icon: const Icon(Icons.remove_circle_outline),
                            onPressed: qte > 0
                                ? () => setState(() =>
                                    quantites[id] = (qte - 1).clamp(0, 1e9))
                                : null,
                          ),
                          Text('${qte == qte.roundToDouble() ? qte.toInt() : qte}',
                              style: const TextStyle(
                                  fontWeight: FontWeight.bold)),
                          IconButton(
                            icon: const Icon(Icons.add_circle_outline,
                                color: couleurKilima),
                            onPressed: () =>
                                setState(() => quantites[id] = qte + 1),
                          ),
                        ],
                      ),
                    ),
                  ),
                );
              }),
          ],
        ),
      ),
    );
  }
}
