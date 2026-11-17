import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../app_state.dart';
import '../widgets/common.dart';
import '../widgets/pieces_jointes.dart';

/// Détail d'une réquisition : fiche, progression du circuit, échanges
/// (commentaires) et actions de validation.
class RequisitionDetailScreen extends StatefulWidget {
  final String id;

  /// Fourni par la liste (champ est_initiateur de GET /api/requisitions) :
  /// l'initiateur répond aux précisions, les validateurs valident/rejettent.
  final bool estInitiateur;
  const RequisitionDetailScreen(
      {super.key, required this.id, this.estInitiateur = false});

  @override
  State<RequisitionDetailScreen> createState() =>
      _RequisitionDetailScreenState();
}

class _RequisitionDetailScreenState extends State<RequisitionDetailScreen> {
  Map<String, dynamic>? req;
  List commentaires = [];
  bool chargement = true;
  Object? erreur;
  bool action = false;

  @override
  void initState() {
    super.initState();
    _charger();
  }

  Future<void> _charger() async {
    final api = context.read<AppState>().api;
    setState(() {
      chargement = req == null;
      erreur = null;
    });
    try {
      final r = await api.get('/api/requisitions/${widget.id}/detail');
      final c = await api.get('/api/requisitions/${widget.id}/commentaires');
      if (mounted) {
        setState(() {
          req = Map<String, dynamic>.from(r);
          commentaires = c as List;
        });
      }
    } catch (e) {
      if (mounted) setState(() => erreur = e);
    } finally {
      if (mounted) setState(() => chargement = false);
    }
  }

  bool get _initiateurEstMoi => widget.estInitiateur;

  Future<void> _valider(String decision) async {
    final commentaire = await _demanderTexte(
        decision == 'valide' ? 'Valider la demande' : 'Rejeter la demande',
        'Commentaire (facultatif)',
        requis: false);
    if (commentaire == null) return; // annulé
    await _action(() async {
      await context.read<AppState>().api.post(
          '/api/requisitions/${widget.id}/valider-demande', {
        'decision': decision,
        if (commentaire.isNotEmpty) 'commentaire': commentaire,
      });
    }, decision == 'valide' ? 'Demande validée.' : 'Demande rejetée.');
  }

  Future<void> _demanderPrecisions() async {
    final commentaire = await _demanderTexte(
        'Demander des précisions', 'Que faut-il préciser ? *');
    if (commentaire == null || commentaire.isEmpty) return;
    await _action(() async {
      await context.read<AppState>().api.post(
          '/api/requisitions/${widget.id}/demander-precisions',
          {'commentaire': commentaire});
    }, 'Précisions demandées à l\'initiateur.');
  }

  Future<void> _repondre() async {
    final commentaire =
        await _demanderTexte('Répondre et resoumettre', 'Votre réponse *');
    if (commentaire == null || commentaire.isEmpty) return;
    await _action(() async {
      await context
          .read<AppState>()
          .api
          .post('/api/requisitions/${widget.id}/repondre',
              {'commentaire': commentaire});
    }, 'Réponse envoyée, réquisition resoumise.');
  }

  Future<String?> _demanderTexte(String titre, String libelle,
      {bool requis = true}) {
    final ctrl = TextEditingController();
    return showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(titre),
        content: TextField(
          controller: ctrl,
          maxLines: 3,
          autofocus: true,
          decoration: InputDecoration(
              labelText: libelle, border: const OutlineInputBorder()),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Annuler')),
          FilledButton(
            onPressed: () {
              if (requis && ctrl.text.trim().isEmpty) return;
              Navigator.pop(ctx, ctrl.text.trim());
            },
            child: const Text('Envoyer'),
          ),
        ],
      ),
    );
  }

  Future<void> _action(Future<void> Function() fn, String succes) async {
    setState(() => action = true);
    try {
      await fn();
      if (mounted) montrerSucces(context, succes);
      await _charger();
    } catch (e) {
      if (mounted) montrerErreur(context, e);
    } finally {
      if (mounted) setState(() => action = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = req;
    final statut = '${r?['statut'] ?? ''}';
    final enValidation = statut == 'soumise' || statut == 'en_attente_info';
    return Scaffold(
      appBar: AppBar(title: Text(r == null ? 'Réquisition' : '${r['numero']}')),
      body: CorpsAsync(
        chargement: chargement,
        erreur: req == null ? erreur : null,
        surRafraichir: _charger,
        constructeur: () => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Row(
              children: [
                Expanded(
                  child: Text('${r!['objet']}',
                      style: Theme.of(context).textTheme.titleMedium),
                ),
                StatutChip(statut),
              ],
            ),
            const SizedBox(height: 4),
            Text(
                'Initiateur : ${r['initiateur'] ?? '—'} · ${fmtDate('${r['date'] ?? ''}')}',
                style: const TextStyle(color: Colors.grey, fontSize: 12)),
            if ((r['justification'] ?? '') != '')
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('${r['justification']}'),
              ),
            const Divider(height: 24),
            _infos(r),
            const Divider(height: 24),
            Text('Progression',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            Text('${(r['progression'] ?? const {})['label'] ?? '—'}'),
            const SizedBox(height: 6),
            ...(((r['progression'] ?? const {})['etapes'] as List?) ?? const [])
                .map((e) {
              final d = '${(e as Map)['decision']}';
              return Row(
                children: [
                  Icon(
                    d == 'valide'
                        ? Icons.check_circle
                        : d == 'rejete'
                            ? Icons.cancel
                            : Icons.radio_button_unchecked,
                    size: 18,
                    color: d == 'valide'
                        ? Colors.green
                        : d == 'rejete'
                            ? Colors.red
                            : Colors.grey,
                  ),
                  const SizedBox(width: 6),
                  Text('${e['role']} — ${d == 'en_attente' ? 'en attente' : d}'),
                ],
              );
            }),
            const Divider(height: 24),
            Text('Lignes', style: Theme.of(context).textTheme.titleMedium),
            ...((r['lignes'] as List?) ?? const []).map((l) => ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text('${(l as Map)['description']}'),
                  subtitle: Text(
                      '${l['quantite']} ${l['unite'] ?? ''} × ${fmtMontant(l['prix_unitaire'] as num?, '${r['devise']}')}'),
                  trailing: Text(fmtMontant(l['montant'] as num?, '${r['devise']}'),
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                )),
            Align(
              alignment: Alignment.centerRight,
              child: Text(
                  'Total : ${fmtMontant(r['montant_total'] as num?, '${r['devise']}')}'
                  '${r['devise'] != 'USD' ? ' (${fmtMontant(r['montant_total_usd'] as num?)})' : ''}',
                  style: Theme.of(context)
                      .textTheme
                      .titleMedium
                      ?.copyWith(color: couleurKilima)),
            ),
            const Divider(height: 24),
            Text('Échanges', style: Theme.of(context).textTheme.titleMedium),
            if (commentaires.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 4),
                child:
                    Text('Aucun échange.', style: TextStyle(color: Colors.grey)),
              )
            else
              ...commentaires.map((c) {
                final m = c as Map;
                final estQuestion = m['type'] == 'precision_demandee';
                return Card(
                  color: estQuestion ? Colors.orange.shade50 : Colors.grey.shade100,
                  margin: const EdgeInsets.symmetric(vertical: 4),
                  child: Padding(
                    padding: const EdgeInsets.all(10),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                            '${m['auteur'] ?? '—'} · '
                            '${estQuestion ? 'précisions demandées' : 'réponse'} · '
                            '${fmtDate('${m['created_at'] ?? ''}')}',
                            style: const TextStyle(
                                fontSize: 11, color: Colors.grey)),
                        const SizedBox(height: 4),
                        Text('${m['message']}'),
                      ],
                    ),
                  ),
                );
              }),
            const Divider(height: 24),
            PiecesJointesSection(documentType: 'requisition', documentId: widget.id),
            const SizedBox(height: 16),
            // ── Actions du circuit ──
            if (action)
              const Center(child: CircularProgressIndicator())
            else if (enValidation) ...[
              if (!_initiateurEstMoi) ...[
                Row(
                  children: [
                    Expanded(
                      child: FilledButton.icon(
                        onPressed: () => _valider('valide'),
                        icon: const Icon(Icons.check),
                        label: const Text('Valider'),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FilledButton.icon(
                        style: FilledButton.styleFrom(
                            backgroundColor: Colors.red.shade700),
                        onPressed: () => _valider('rejete'),
                        icon: const Icon(Icons.close),
                        label: const Text('Rejeter'),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  onPressed: _demanderPrecisions,
                  icon: const Icon(Icons.help_outline),
                  label: const Text('Demander des précisions'),
                ),
              ],
              if (_initiateurEstMoi && statut == 'en_attente_info')
                FilledButton.icon(
                  onPressed: _repondre,
                  icon: const Icon(Icons.reply),
                  label: const Text('Répondre et resoumettre'),
                ),
            ],
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }

  Widget _infos(Map r) {
    Widget ligne(String libelle, String valeur) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(
            children: [
              SizedBox(
                  width: 150,
                  child: Text(libelle,
                      style: const TextStyle(color: Colors.grey))),
              Expanded(child: Text(valeur)),
            ],
          ),
        );
    return Column(
      children: [
        ligne('Priorité', '${r['priorite'] ?? '—'}'),
        ligne(
            'Mode de décaissement',
            r['mode_decaissement'] == 'paiement_direct'
                ? 'Paiement sur justificatif'
                : 'Avance à justifier'),
        ligne('Devise', '${r['devise'] ?? '—'}'),
        ligne('Pièces jointes', '${r['nb_pieces_jointes'] ?? 0}'),
      ],
    );
  }
}
