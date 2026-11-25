#!/usr/bin/env bash
# Sauvegarde conjointe de la base PostgreSQL et des pièces jointes (volume uploads)
# de l'ERP Kilima Holdings déployé par docker compose.
#
# À exécuter sur le serveur, depuis la racine du dépôt (là où se trouve
# docker-compose.yaml), avec un utilisateur membre du groupe docker.
#
# Usage :
#   ./deployment/sauvegarde.sh [options]
#
# Options :
#   --dossier CHEMIN    Dossier recevant les sauvegardes (défaut : ./sauvegardes)
#   --retention N       Nombre de sauvegardes conservées (défaut : 14)
#   --env-file FICHIER  Fichier d'environnement compose (défaut : .env.docker)
#   --a-chaud           Ne pas arrêter les services pendant la copie
#                       (plus rapide, mais base et documents peuvent diverger
#                       si quelqu'un travaille pendant la sauvegarde)
#   --simulation        Afficher les commandes sans rien exécuter
#
# Chaque sauvegarde produit un dossier kilima_AAAA-MM-JJ_HHMMSS contenant :
#   base.dump       export PostgreSQL au format custom (pg_dump -Fc)
#   documents.tgz   archive du volume uploads (pièces jointes)
#   SHA256SUMS      empreintes de contrôle des deux fichiers
#   INFO.txt        date, version du code, tailles

set -euo pipefail

DOSSIER_SAUVEGARDES="sauvegardes"
RETENTION=14
ENV_FILE=".env.docker"
A_CHAUD=0
SIMULATION=0

while [ $# -gt 0 ]; do
    case "$1" in
        --dossier)   DOSSIER_SAUVEGARDES="$2"; shift 2 ;;
        --retention) RETENTION="$2"; shift 2 ;;
        --env-file)  ENV_FILE="$2"; shift 2 ;;
        --a-chaud)   A_CHAUD=1; shift ;;
        --simulation) SIMULATION=1; shift ;;
        -h|--help)   tail -n +2 "$0" | sed -n '/^#/!q; s/^# \{0,1\}//p'; exit 0 ;;
        *) echo "Option inconnue : $1 (voir --help)" >&2; exit 2 ;;
    esac
done

case "$RETENTION" in
    ''|*[!0-9]*) echo "ERREUR : --retention attend un nombre entier (reçu : $RETENTION)." >&2; exit 2 ;;
esac
if [ "$RETENTION" -lt 1 ]; then
    echo "ERREUR : --retention doit être au moins 1." >&2
    exit 2
fi

compose() {
    if [ "$SIMULATION" -eq 1 ]; then
        echo "[simulation] docker compose --env-file $ENV_FILE $*"
    else
        docker compose --env-file "$ENV_FILE" "$@"
    fi
}

if [ ! -f docker-compose.yaml ]; then
    echo "ERREUR : exécuter ce script depuis la racine du dépôt (docker-compose.yaml introuvable)." >&2
    exit 1
fi
if [ "$SIMULATION" -eq 0 ]; then
    if ! command -v docker >/dev/null 2>&1; then
        echo "ERREUR : docker n'est pas disponible sur cette machine." >&2
        exit 1
    fi
    if [ ! -f "$ENV_FILE" ]; then
        echo "ERREUR : fichier d'environnement introuvable : $ENV_FILE" >&2
        exit 1
    fi
fi

HORODATAGE="$(date +%Y-%m-%d_%H%M%S)"
DESTINATION="$DOSSIER_SAUVEGARDES/kilima_$HORODATAGE"
if [ "$SIMULATION" -eq 1 ]; then
    DESTINATION_ABS="$PWD/$DESTINATION"
else
    mkdir -p "$DESTINATION"
    DESTINATION_ABS="$(cd "$DESTINATION" && pwd)"
fi

SERVICES_ARRETES=0
redemarrer() {
    if [ "$SERVICES_ARRETES" -eq 1 ]; then
        echo "— Redémarrage des services…"
        compose up -d
        SERVICES_ARRETES=0
    fi
}
# Quoi qu'il arrive (erreur comprise), ne jamais laisser l'application arrêtée.
trap redemarrer EXIT

echo "=== Sauvegarde ERP Kilima — $HORODATAGE ==="
echo "Destination : $DESTINATION"

if [ "$A_CHAUD" -eq 0 ]; then
    echo "— Arrêt des services applicatifs (la base reste en route)…"
    SERVICES_ARRETES=1
    compose stop web frontend backend
else
    echo "— Sauvegarde à chaud : les services restent en route."
fi

echo "— Export de la base PostgreSQL (pg_dump)…"
if [ "$SIMULATION" -eq 1 ]; then
    echo "[simulation] docker compose --env-file $ENV_FILE exec -T db sh -c 'pg_dump …' > $DESTINATION/base.dump"
else
    docker compose --env-file "$ENV_FILE" exec -T db \
        sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$DESTINATION/base.dump"
    # Un export au format custom commence toujours par la signature PGDMP.
    if [ "$(head -c 5 "$DESTINATION/base.dump")" != "PGDMP" ]; then
        echo "ERREUR : l'export de la base ne ressemble pas à un dump PostgreSQL valide." >&2
        exit 1
    fi
fi

echo "— Archivage des pièces jointes (volume uploads)…"
compose run --rm --no-deps --user root \
    -v "$DESTINATION_ABS:/sauvegarde" \
    --entrypoint tar backend \
    -czf /sauvegarde/documents.tgz -C /app/backend/uploads .

redemarrer
trap - EXIT

if [ "$SIMULATION" -eq 1 ]; then
    echo "[simulation] contrôles, SHA256SUMS, INFO.txt et rotation ($RETENTION conservées)"
    echo "=== Simulation terminée ==="
    exit 0
fi

echo "— Contrôles d'intégrité…"
for fichier in base.dump documents.tgz; do
    if [ ! -s "$DESTINATION/$fichier" ]; then
        echo "ERREUR : $DESTINATION/$fichier est vide ou absent." >&2
        exit 1
    fi
done
if command -v gzip >/dev/null 2>&1; then
    gzip -t "$DESTINATION/documents.tgz"
fi
(cd "$DESTINATION" && sha256sum base.dump documents.tgz > SHA256SUMS)

{
    echo "Sauvegarde ERP Kilima Holdings"
    echo "Date            : $(date '+%Y-%m-%d %H:%M:%S')"
    echo "Mode            : $([ "$A_CHAUD" -eq 1 ] && echo 'à chaud' || echo 'services arrêtés')"
    echo "Version du code : $(git rev-parse --short HEAD 2>/dev/null || echo 'inconnue')"
    echo "Taille base     : $(du -h "$DESTINATION/base.dump" | cut -f1)"
    echo "Taille documents: $(du -h "$DESTINATION/documents.tgz" | cut -f1)"
    echo
    echo "Restauration : ./deployment/restauration.sh $DESTINATION"
} > "$DESTINATION/INFO.txt"

echo "— Rotation : conservation des $RETENTION sauvegardes les plus récentes…"
ls -1d "$DOSSIER_SAUVEGARDES"/kilima_* 2>/dev/null | sort | head -n -"$RETENTION" | while read -r ancienne; do
    echo "   suppression de $ancienne"
    rm -rf "$ancienne"
done

echo "=== Sauvegarde terminée : $DESTINATION ==="
echo "Rappel : copier régulièrement ce dossier HORS du serveur, avec une copie"
echo "sécurisée de .env.docker (nécessaire à la restauration)."
