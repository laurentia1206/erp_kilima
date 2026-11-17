import 'package:flutter/material.dart';

import '../api_client.dart';

const couleurKilima = Color(0xFF176B61);

String fmtMontant(num? m, [String devise = 'USD']) {
  if (m == null) return '—';
  final s = m.toStringAsFixed(2);
  final parts = s.split('.');
  final entier = parts[0].replaceAllMapped(
      RegExp(r'\B(?=(\d{3})+(?!\d))'), (match) => ' ');
  return '$entier,${parts[1]} ${devise == 'USD' ? r'$' : devise}';
}

String fmtDate(String? iso) {
  if (iso == null || iso.isEmpty) return '—';
  final d = DateTime.tryParse(iso);
  if (d == null) return iso;
  String deux(int n) => n.toString().padLeft(2, '0');
  final date = '${deux(d.day)}/${deux(d.month)}/${d.year}';
  if (d.hour == 0 && d.minute == 0 && !iso.contains('T')) return date;
  return iso.contains('T') ? '$date ${deux(d.hour)}:${deux(d.minute)}' : date;
}

/// Libellés et couleurs des statuts du circuit.
const _statuts = {
  'soumise': ('Soumise', Colors.orange),
  'en_attente_info': ('Précisions demandées', Colors.deepOrange),
  'demande_validee': ('Demande validée', Colors.blue),
  'transformee': ('Transformée en ordre', Colors.teal),
  'rejetee': ('Rejetée', Colors.red),
  'cloturee': ('Clôturée', Colors.grey),
  'planifiee': ('Planifiée', Colors.blueGrey),
  'en_cours': ('En cours', Colors.orange),
  'terminee': ('Terminée', Colors.green),
};

String libelleStatut(String? statut) =>
    _statuts[statut]?.$1 ?? (statut ?? '—');

class StatutChip extends StatelessWidget {
  final String? statut;
  const StatutChip(this.statut, {super.key});

  @override
  Widget build(BuildContext context) {
    final info = _statuts[statut] ?? (statut ?? '—', Colors.grey);
    return Chip(
      label: Text(info.$1,
          style: const TextStyle(color: Colors.white, fontSize: 12)),
      backgroundColor: info.$2,
      visualDensity: VisualDensity.compact,
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
      padding: const EdgeInsets.symmetric(horizontal: 4),
    );
  }
}

/// Affiche l'erreur API dans une barre rouge en bas d'écran.
void montrerErreur(BuildContext context, Object e) {
  final msg = e is ApiException ? e.message : 'Erreur réseau : $e';
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
    content: Text(msg),
    backgroundColor: Colors.red.shade700,
  ));
}

void montrerSucces(BuildContext context, String message) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
    content: Text(message),
    backgroundColor: couleurKilima,
  ));
}

/// Confirmation générique avant une action du circuit.
Future<bool> confirmer(BuildContext context, String titre, String message,
    {String bouton = 'Confirmer'}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(titre),
      content: Text(message),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Annuler')),
        FilledButton(
            onPressed: () => Navigator.pop(ctx, true), child: Text(bouton)),
      ],
    ),
  );
  return ok == true;
}

/// Corps standard : chargement / erreur / contenu.
class CorpsAsync extends StatelessWidget {
  final bool chargement;
  final Object? erreur;
  final Widget Function() constructeur;
  final Future<void> Function()? surRafraichir;

  const CorpsAsync(
      {super.key,
      required this.chargement,
      this.erreur,
      required this.constructeur,
      this.surRafraichir});

  @override
  Widget build(BuildContext context) {
    if (chargement) return const Center(child: CircularProgressIndicator());
    if (erreur != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_off, size: 42, color: Colors.grey),
              const SizedBox(height: 12),
              Text('$erreur', textAlign: TextAlign.center),
              const SizedBox(height: 12),
              if (surRafraichir != null)
                OutlinedButton.icon(
                    onPressed: () => surRafraichir!(),
                    icon: const Icon(Icons.refresh),
                    label: const Text('Réessayer')),
            ],
          ),
        ),
      );
    }
    final contenu = constructeur();
    if (surRafraichir == null) return contenu;
    return RefreshIndicator(onRefresh: surRafraichir!, child: contenu);
  }
}
