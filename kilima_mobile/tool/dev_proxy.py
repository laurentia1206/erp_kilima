"""Proxy de développement pour tester l'appli en mode web (flutter run -d web-server).

Le backend Django n'envoie pas d'en-têtes CORS : un navigateur refuse donc les
appels directs depuis un autre port. Ce proxy écoute sur le port 8013, relaie
tout vers http://localhost:8012 et ajoute les en-têtes CORS. Il ne sert QU'AU
développement local — l'application Android/iOS parle directement à l'API et
n'en a pas besoin.

Usage :  python tool/dev_proxy.py        (backend déjà lancé sur le port 8012)
Puis, dans l'appli web, URL du serveur : http://localhost:8013
"""
import http.server
import urllib.error
import urllib.request

BACKEND = "http://localhost:8012"
PORT = 8013


class Proxy(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, PATCH, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Authorization, Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _relayer(self):
        taille = int(self.headers.get("Content-Length") or 0)
        corps = self.rfile.read(taille) if taille else None
        requete = urllib.request.Request(
            BACKEND + self.path, data=corps, method=self.command)
        for nom in ("Authorization", "Content-Type"):
            if self.headers.get(nom):
                requete.add_header(nom, self.headers[nom])
        try:
            with urllib.request.urlopen(requete) as reponse:
                donnees = reponse.read()
                self.send_response(reponse.status)
                self._cors()
                ct = reponse.headers.get("Content-Type")
                if ct:
                    self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(donnees)))
                self.end_headers()
                self.wfile.write(donnees)
        except urllib.error.HTTPError as e:
            donnees = e.read()
            self.send_response(e.code)
            self._cors()
            ct = e.headers.get("Content-Type")
            if ct:
                self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(donnees)))
            self.end_headers()
            self.wfile.write(donnees)
        except Exception as e:  # backend éteint, etc.
            message = f'{{"detail": "Proxy : backend injoignable ({e})"}}'.encode()
            self.send_response(502)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _relayer

    def log_message(self, fmt, *args):
        print(f"[proxy] {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")


if __name__ == "__main__":
    print(f"Proxy CORS : http://localhost:{PORT} -> {BACKEND}")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Proxy).serve_forever()
