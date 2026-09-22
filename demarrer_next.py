"""Lance Next.js et, si nécessaire, l'API Django sur la copie de recette."""
from pathlib import Path
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description='ERP Kilima : frontend Next.js et API Django de tests.')
    parser.add_argument('--port', type=int, default=3000)
    parser.add_argument('--api-port', type=int, default=8012)
    parser.add_argument('--verifier', action='store_true')
    args = parser.parse_args()
    if not (1 <= args.port <= 65535 and 1 <= args.api_port <= 65535) or args.port == args.api_port:
        parser.error('Choisir deux ports distincts entre 1 et 65535.')
    root = Path(__file__).resolve().parent
    frontend = root / 'frontend'
    node = shutil.which('node')
    if not node or not (frontend / 'node_modules/next/dist/bin/next').is_file():
        raise SystemExit('Installer Node.js puis exécuter Installer-Windows.bat (ou npm ci dans frontend).')
    subprocess.run([sys.executable, str(root / 'demarrer_tests.py'), '--verifier'], check=True)
    subprocess.run([node, 'scripts/prepare-assets.mjs'], cwd=frontend, check=True)
    if args.verifier:
        subprocess.run([node, 'node_modules/typescript/bin/tsc', '--noEmit'], cwd=frontend, check=True)
        print('Frontend Next.js et copie de recette vérifiés.')
        return
    api_url = f'http://127.0.0.1:{args.api_port}'
    def healthy():
        try:
            with urlopen(api_url + '/api/health', timeout=2) as response:
                data = json.load(response)
                return data.get('status') == 'ok' and data.get('env') in {'dev', 'development', 'test'}
        except Exception:
            return False
    def occupied(port):
        with socket.socket() as connection:
            return connection.connect_ex(('127.0.0.1', port)) == 0
    if occupied(args.port):
        raise SystemExit(f'Le port {args.port} est déjà utilisé. Ouvrir la page existante ou choisir --port.')
    if occupied(args.api_port) and not healthy():
        raise SystemExit('Le port API est occupé par un service inattendu. Choisir --api-port.')
    children = []
    try:
        if not healthy():
            api = subprocess.Popen([sys.executable, str(root / 'demarrer_tests.py'), '--port', str(args.api_port)], cwd=root)
            children.append(api)
            for _ in range(60):
                if api.poll() is not None:
                    raise RuntimeError('Le serveur Django ne démarre pas.')
                if healthy():
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError('Le serveur Django ne répond pas.')
        print(f'Ouvrir http://127.0.0.1:{args.port}/ — Ctrl+C pour arrêter.', flush=True)
        env = {**os.environ, 'DJANGO_API_URL': api_url,
               'APP_URL': f'http://127.0.0.1:{args.port}', 'NEXT_TELEMETRY_DISABLED': '1'}
        app = subprocess.Popen([node, 'node_modules/next/dist/bin/next', 'dev', '--webpack', '--hostname', '127.0.0.1', '--port', str(args.port)], cwd=frontend, env=env)
        children.append(app)
        app.wait()
    finally:
        for process in reversed(children):
            if process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    process.terminate()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
