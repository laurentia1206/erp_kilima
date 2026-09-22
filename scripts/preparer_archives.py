"""Livre le code, Docker et les données privées dans trois ZIP vérifiés.

Aucune configuration secrète copiée. Les bases SQLite sont lues via l'API de
sauvegarde (WAL compris), jamais copiées pendant une écriture.
"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SKIP = {'.git', '.claude', '.build', '.next', '__pycache__', '.pytest_cache',
        '.venv', 'venv', 'node_modules', 'backups', 'uploads'}
EXAMPLES = {'.env.example', '.env.production.example', '.env.docker.example'}


def sources(folder):
    for parent, dirs, files in os.walk(ROOT / folder):
        dirs[:] = [d for d in dirs if d not in SKIP and not (Path(parent) / d).is_symlink()]
        for name in files:
            path = Path(parent) / name
            if path.is_symlink():
                continue
            if name.startswith('.env') and name not in EXAMPLES:
                continue
            if path.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.pyc', '.pyo', '.log', '.pem', '.key', '.pfx', '.tsbuildinfo'}:
                continue
            if name.endswith(('-wal', '-shm', '-journal')):
                continue
            relative = path.relative_to(ROOT).as_posix()
            if relative.startswith('frontend/public/legacy/'):
                continue
            yield relative, path


def archive(target, files, notes=None):
    manifest = []
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        contents = [(name, path.read_bytes()) for name, path in sorted(files.items())]
        if notes:
            contents.append(('LIRE-AVANT-UTILISATION.txt', notes.encode('utf-8')))
        for relative, content in contents:
            manifest.append(hashlib.sha256(content).hexdigest() + '  ' + relative)
            z.writestr('ERP-Kilima-Django/' + relative, content)
        z.writestr('ERP-Kilima-Django/MANIFESTE-' + target.stem + '.txt', '\n'.join(manifest) + '\n')
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for name in z.namelist():
            assert '..' not in Path(name).parts and not Path(name).is_absolute()
            assert not Path(name).name.startswith('.env') or Path(name).name in EXAMPLES
        for line in manifest:
            digest, relative = line.split('  ', 1)
            assert hashlib.sha256(z.read('ERP-Kilima-Django/' + relative)).hexdigest() == digest
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(digest + '  ' + target.name + '\n', encoding='utf-8')
    return {'archive': str(target), 'fichiers': len(manifest) + 1, 'octets': target.stat().st_size, 'sha256': digest}


def main():
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out = ROOT / 'livrables'
    out.mkdir(exist_ok=True)
    stage = ROOT / '.build' / ('archives-docker-' + stamp)
    stage.mkdir(parents=True)
    files = {}
    for folder in ('backend', 'frontend', 'database', 'docs', 'scripts'):
        files.update(sources(folder))
    for name in ('.gitignore', '.dockerignore', '.env.docker.example', 'docker-compose.yaml', 'DOCKER.md',
                 'LIRE-MOI.md', 'Installer-Windows.bat', 'Demarrer-tests.bat',
                 'demarrer_tests.py', 'Demarrer-Next.bat', 'demarrer_next.py',
                 'Cahier_des_Charges_ERP_KILIMA_HOLDINGS_v1.docx'):
        files[name] = ROOT / name
    # Refuser une fuite des secrets de configuration locaux dans le code livré.
    secrets = []
    for env_path in (ROOT / 'backend/.env', ROOT / 'frontend/.env.local'):
        if env_path.exists():
            for line in env_path.read_text(encoding='utf-8-sig').splitlines():
                key, sep, value = line.partition('=')
                if sep and key.strip() in {'SECRET_KEY', 'POSTGRES_PASSWORD'} and len(value.strip()) >= 16:
                    secrets.append(value.strip().strip('"\'').encode())
    for relative, path in files.items():
        if any(secret in path.read_bytes() for secret in secrets):
            raise RuntimeError('Secret détecté dans un fichier de code : ' + relative)

    snapshots = {'kilima_test.db': ROOT / '.build/qa/kilima_qa.db',
                 'base_historique.db': ROOT / 'backend/kilima_dev.db'}
    if not snapshots['kilima_test.db'].exists():
        snapshots['kilima_test.db'] = ROOT / 'data/kilima_test.db'
    private = {}
    for name, source in snapshots.items():
        if not source.is_file():
            raise FileNotFoundError('Base attendue absente : ' + str(source))
        destination = stage / name
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(destination) as dst:
            src.backup(dst)
            assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        private['data/' + name] = destination
    for path in (ROOT / 'backend/uploads').rglob('*'):
        if path.is_file() and not path.is_symlink():
            private[path.relative_to(ROOT).as_posix()] = path
    for name in snapshots:
        with sqlite3.connect((stage / name).as_uri() + '?mode=ro', uri=True) as db:
            for (storage,) in db.execute('SELECT chemin_stockage FROM piece_jointe'):
                if storage and 'backend/uploads/' + storage.replace('\\', '/') not in private:
                    raise RuntimeError('Pièce jointe manquante ; livraison privée annulée.')

    docker = {k: v for k, v in files.items() if k.startswith('backend/deployment/') or k in
              {'docker-compose.yaml', '.dockerignore', '.env.docker.example', 'DOCKER.md',
               'backend/Dockerfile', 'backend/requirements-production.txt',
               'frontend/Dockerfile', 'frontend/nginx.conf'}}
    reports = [
        archive(out / f'ERP-Kilima-code-complet-{stamp}.zip', files),
        archive(out / f'ERP-Kilima-Docker-{stamp}.zip', docker),
        archive(out / f'ERP-Kilima-donnees-PRIVEES-{stamp}.zip', private,
                'CONFIDENTIEL — base de tests, comptes (mots de passe hachés), données RH, '
                'finance et justificatifs. ZIP non chiffré : conserver en lieu sûr et '
                'transmettre uniquement par canal sécurisé. Aucun .env inclus.\n'
                'Extraire avec le ZIP du code dans le même dossier parent pour reprendre '
                'les tests Windows. Ne pas importer ces fichiers SQLite dans PostgreSQL.\n'),
    ]
    (stage / 'resultats.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
