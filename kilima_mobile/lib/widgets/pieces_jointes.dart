import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../app_state.dart';
import 'common.dart';

/// Section « Pièces jointes » d'un document (réquisition, intervention…) :
/// liste les fichiers attachés et permet d'ajouter une photo (appareil photo
/// ou galerie) envoyée en multipart sur POST /api/pieces-jointes.
class PiecesJointesSection extends StatefulWidget {
  final String documentType;
  final String documentId;
  const PiecesJointesSection(
      {super.key, required this.documentType, required this.documentId});

  @override
  State<PiecesJointesSection> createState() => _PiecesJointesSectionState();
}

class _PiecesJointesSectionState extends State<PiecesJointesSection> {
  List pieces = [];
  bool chargement = true;
  bool envoi = false;

  @override
  void initState() {
    super.initState();
    _charger();
  }

  Future<void> _charger() async {
    final api = context.read<AppState>().api;
    try {
      final r = await api.get('/api/pieces-jointes', {
        'document_type': widget.documentType,
        'document_id': widget.documentId,
      });
      if (mounted) setState(() => pieces = r as List);
    } catch (e) {
      if (mounted) montrerErreur(context, e);
    } finally {
      if (mounted) setState(() => chargement = false);
    }
  }

  Future<void> _ajouter(ImageSource source) async {
    final api = context.read<AppState>().api;
    try {
      final image = await ImagePicker()
          .pickImage(source: source, maxWidth: 1920, imageQuality: 85);
      if (image == null) return;
      setState(() => envoi = true);
      final bytes = await image.readAsBytes();
      await api.uploadPieceJointe(
        documentType: widget.documentType,
        documentId: widget.documentId,
        filename: image.name.isEmpty ? 'photo.jpg' : image.name,
        bytes: bytes,
      );
      if (mounted) montrerSucces(context, 'Pièce jointe envoyée.');
      await _charger();
    } catch (e) {
      if (mounted) montrerErreur(context, e);
    } finally {
      if (mounted) setState(() => envoi = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text('Pièces jointes',
                style: Theme.of(context).textTheme.titleMedium),
            const Spacer(),
            if (envoi)
              const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2))
            else ...[
              IconButton(
                tooltip: 'Prendre une photo',
                icon: const Icon(Icons.photo_camera, color: couleurKilima),
                onPressed: () => _ajouter(ImageSource.camera),
              ),
              IconButton(
                tooltip: 'Choisir un fichier',
                icon: const Icon(Icons.attach_file, color: couleurKilima),
                onPressed: () => _ajouter(ImageSource.gallery),
              ),
            ],
          ],
        ),
        if (chargement)
          const Padding(
            padding: EdgeInsets.all(8),
            child: LinearProgressIndicator(),
          )
        else if (pieces.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 4),
            child: Text('Aucune pièce jointe.',
                style: TextStyle(color: Colors.grey)),
          )
        else
          ...pieces.map((p) => ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.description_outlined),
                title: Text('${p['nom_fichier'] ?? 'fichier'}'),
                subtitle: Text(
                    '${(((p['taille_octets'] ?? 0) as num) / 1024).toStringAsFixed(0)} Ko'),
              )),
      ],
    );
  }
}
