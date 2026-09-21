"""Lance la copie de recette locale ; ne cible jamais la base historique."""
from pathlib import Path
import argparse
import os
import secrets
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description='Démarrer ERP Kilima en tests locaux.')
    parser.add_argument('--verifier', action='store_true', help='Vérifier sans lancer le serveur.')
    parser.add_argument('--port', type=int, default=8012)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Le port doit être compris entre 1 et 65535.')
    root = Path(__file__).resolve().parent
    db = root / 'data/kilima_test.db'
    if not db.is_file():
        db = root / '.build/qa/kilima_qa.db'
    if not db.is_file():
        raise SystemExit('Base de tests introuvable. Extraire complètement le ZIP ; aucune base vide ne sera créée.')

    configuration = root / 'backend/.env'
    if not configuration.exists():
        # Une nouvelle clé invalide les anciennes sessions sans changer les comptes.
        with configuration.open('x', encoding='utf-8') as stream:
            template = (root / 'backend/.env.example').read_text(encoding='utf-8')
            lines = template.splitlines()
            lines = [('SECRET_KEY=' + secrets.token_urlsafe(64)) if line.startswith('SECRET_KEY=')
                     else ('DATABASE_URL=sqlite:///' + db.as_posix()) if line.startswith('DATABASE_URL=')
                     else line for line in lines]
            stream.write('\n'.join(lines) + '\n')
    env = {**os.environ, 'KILIMA_DB': 'sqlite:///' + str(db),
           'ENVIRONMENT': 'dev', 'DEBUG': 'true', 'BACKUP_ON_STARTUP': 'false',
           'ALLOWED_HOSTS': 'localhost,127.0.0.1,[::1]', 'SECURE_SSL_REDIRECT': 'false',
           'KILIMA_ENV_FILE': str(configuration), 'TRUST_PROXY_HTTPS': 'false',
           'SECURE_HSTS_SECONDS': '0'}
    directory = root / 'backend'
    commands = [['check'], ['migrate', '--check']]
    if not args.verifier:
        commands.append(['runserver', f'127.0.0.1:{args.port}', '--noreload'])
        print(f'Ouvrir http://127.0.0.1:{args.port}/ — Ctrl+C pour arrêter.', flush=True)
    for command in commands:
        result = subprocess.run([sys.executable, 'manage.py', *command], cwd=directory, env=env)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
