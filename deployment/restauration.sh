#!/usr/bin/env bash
# Restauration conjointe de la base PostgreSQL et des pièces jointes (volume
# uploads) de l'ERP Kilima Holdings, à partir d'un dossier produit par
# deployment/sauvegarde.sh.
#
# ATTENTION : cette restauration REMPLACE le contenu actuel de la base et des
# pièces jointes de l'environnement visé. Elle demande une confirmation tapée
# au clavier avant d'agir.
#
# À exécuter sur le serveur, depuis la racine du dépôt.
#
# Usage :
#   ./deployment/restauration.sh DOSSIER_DE_SAUVEGARDE [options]
#
# Exemple :
#   ./deployment/restauration.sh sauvegardes/kilima_2026-11-25_020000
#
# Options :
#   --env-file FICHIER  Fichier d'environnement compose (défaut : .env.docker)
#   --projet NOM        Restaurer dans un projet compose distinct (volumes
#                       isolés), par exemple kilima-restauration pour un essai
#                       sans toucher à la production. Voir DOCKER.md.
#   --simulation        Afficher les commandes sans rien exécuter
#
# Après restauration, vérifier la connexion, les totaux comptables, les
# pièces jointes et le journal d'audit. Si le code déployé est plus récent
# que la sauvegarde, le service migrate appliquera les migrations manquantes
# au redémarrage : utiliser de préférence la version du code notée dans
# INFO.txt.

set -euo pipefail

ENV_FILE=".env.docker"
PROJET=""
SIMULATION=0
SOURCE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --env-file)  ENV_FILE="$2"; shift 2 ;;
        --projet)    PROJET="$2"; shift 2 ;;
        --simulation) SIMULATION=1; shift ;;
        -h|--help)   tail -n +2 "$0" | sed -n '/^#/!q; s/^# \{0,1\}//p'; exit 0 ;;
        -*) echo "Option inconnue : $1 (voir --help)" >&2; exit 2 ;;
        *)  SOURCE="$1"; shift ;;
    esac
done

if [ -z "$SOURCE" ]; then
    echo "ERREUR : indiquer le dossier de sauvegarde à restaurer (voir --help)." >&2
    exit 2
fi

OPTS_PROJET=()
if [ -n "$PROJET" ]; then
    OPTS_PROJET=(-p "$PROJET")
fi

compose() {
    if [ "$SIMULATION" -eq 1 ]; then
        echo "[simulation] docker compose ${OPTS_PROJET[*]:-} --env-file $ENV_FILE $*"
    else
        docker compose "${OPTS_PROJET[@]}" --env-file "$ENV_FILE" "$@"
    fi
}

if [ ! -f docker-compose.yaml ]; then
    echo "ERREUR : exécuter ce script depuis la racine du dépôt (docker-compose.yaml introuvable)." >&2
    exit 1
fi
if [ ! -d "$SOURCE" ] || [ ! -s "$SOURCE/base.dump" ] || [ ! -s "$SOURCE/documents.tgz" ]; then
    echo "ERREUR : $SOURCE ne contient pas base.dump et documents.tgz." >&2
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

SOURCE_ABS="$(cd "$SOURCE" && pwd)"

echo "=== Restauration ERP Kilima ==="
echo "Sauvegarde : $SOURCE"
if [ -f "$SOURCE/INFO.txt" ]; then
    sed 's/^/   /' "$SOURCE/INFO.txt"
fi

if [ -f "$SOURCE/SHA256SUMS" ] && command -v sha256sum >/dev/null 2>&1; then
    echo "— Vérification des empreintes SHA256…"
    (cd "$SOURCE" && sha256sum -c SHA256SUMS)
else
    echo "— Pas de fichier SHA256SUMS : empreintes non vérifiées."
fi

if [ -n "$PROJET" ]; then
    CIBLE="$PROJET"
else
    CIBLE="l'environnement de PRODUCTION courant"
fi
if [ "$SIMULATION" -eq 0 ]; then
    echo
    echo "Cette opération va EFFACER la base et les pièces jointes de : $CIBLE"
    printf "Taper RESTAURER en majuscules pour continuer : "
    read -r reponse
    if [ "$reponse" != "RESTAURER" ]; then
        echo "Abandon : aucune modification effectuée."
        exit 1
    fi
fi

echo "— Arrêt des services applicatifs…"
compose stop web frontend backend || true

echo "— Démarrage de la base et attente de sa disponibilité…"
compose up -d --wait db

echo "— Restauration de la base PostgreSQL (pg_restore)…"
if [ "$SIMULATION" -eq 1 ]; then
    echo "[simulation] docker compose … exec -T db pg_restore --clean --if-exists … < $SOURCE/base.dump"
else
    docker compose "${OPTS_PROJET[@]}" --env-file "$ENV_FILE" exec -T db \
        sh -c 'pg_restore --clean --if-exists --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
        < "$SOURCE/base.dump"
fi

echo "— Restauration des pièces jointes (volume uploads)…"
compose run --rm --no-deps --user root \
    -v "$SOURCE_ABS:/restauration:ro" \
    --entrypoint sh backend \
    -c 'find /app/backend/uploads -mindepth 1 -delete && tar -xzf /restauration/documents.tgz -C /app/backend/uploads && chown -R 10001:10001 /app/backend/uploads'

echo "— Redémarrage de l'application…"
compose up -d

echo "=== Restauration terminée ==="
echo "Vérifier maintenant : connexion, totaux comptables, pièces jointes,"
echo "journal d'audit. En cas de restauration d'essai (--projet), penser à"
echo "nettoyer ensuite : docker compose -p NOM down (sans -v pour garder les volumes)."
