"""
import_server.py — sert le viewer ET permet d'importer un modèle par glisser-déposer.

    python converter/import_server.py [port] [--single] [--fresh]

  --single  chaque import REMPLACE le précédent (jamais de liste qui s'accumule)
  --fresh   vide viewer/models/ au démarrage du serveur

Ouvre l'URL affichée, dépose un .abc / .chou / .usd / .blend sur la page : le
serveur lance Blender en tâche de fond, convertit, et le viewer recharge le modèle.

Blender doit être installé. Ordre de recherche de l'exécutable :
  1. variable d'env  BLENDER=/chemin/vers/blender
  2. `blender` dans le PATH
  3. chemins d'install classiques (Windows / macOS / Linux)

Endpoints :
  GET    /                     → viewer/index.html
  GET    /models               → ["Untitled", ...]
  POST   /import?name=&decimate=&step=   (corps = octets du fichier)
                               → {"name": "...", "frameCount": N}  |  {"error": "..."}
  DELETE /models/<nom>         → {"ok": true}
"""
import http.server
import socketserver
import socket
import os
import sys
import json
import glob
import shutil
import tempfile
import subprocess
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "viewer"))
MODELS = os.path.join(ROOT, "models")
CONVERTER = os.path.join(HERE, "scene_to_sequence.py")
ALLOWED_EXT = (".abc", ".usd", ".usdc", ".usda", ".usdz", ".blend", ".chou")

_argv = sys.argv[1:]
SINGLE = "--single" in _argv
FRESH = "--fresh" in _argv
_ports = [a for a in _argv if a.isdigit()]
PORT = int(_ports[0]) if _ports else 8080


def find_blender():
    if os.environ.get("BLENDER") and os.path.isfile(os.environ["BLENDER"]):
        return os.environ["BLENDER"]
    inpath = shutil.which("blender")
    if inpath:
        return inpath
    pats = [
        r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender*\*\blender.exe",
        "/Applications/Blender.app/Contents/MacOS/Blender",
        "/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender",
    ]
    hits = []
    for p in pats:
        hits += glob.glob(p)
    hits.sort()
    return hits[-1] if hits else None


BLENDER = find_blender()


def safe_name(raw):
    base = os.path.splitext(os.path.basename(raw or "model"))[0]
    keep = "".join(c if (c.isalnum() or c in "-_") else "_" for c in base)
    return keep or "model"


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript", ".mjs": "text/javascript",
        ".json": "application/json", ".bin": "application/octet-stream",
        ".wasm": "application/wasm",
    }

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/models":
            return self._json(200, list_models())
        return super().do_GET()

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        if path == "/models":                       # DELETE /models -> clear all
            wipe_models()
            write_models_json()
            return self._json(200, {"ok": True, "cleared": True})
        if path.startswith("/models/"):             # DELETE /models/<name>
            name = safe_name(urllib.parse.unquote(path[len("/models/"):]))
            d = os.path.join(MODELS, name)
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
            write_models_json()
            return self._json(200, {"ok": True, "name": name})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/import":
            return self._json(404, {"error": "not found"})
        if not BLENDER:
            return self._json(500, {"error": "Blender introuvable — définis la variable d'env BLENDER"})

        q = urllib.parse.parse_qs(parsed.query)
        raw_name = q.get("name", ["model"])[0]
        name = safe_name(raw_name)
        decimate = q.get("decimate", ["1.0"])[0]
        step = q.get("step", ["1"])[0]
        ext = os.path.splitext(raw_name)[1].lower() or q.get("ext", [".abc"])[0].lower()
        if ext not in ALLOWED_EXT:
            return self._json(400, {"error": f"extension non gérée : {ext}"})

        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return self._json(400, {"error": "corps vide"})
        data = self.rfile.read(length)

        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        tmp.write(data)
        tmp.close()
        outdir = os.path.join(MODELS, name)

        cmd = [
            BLENDER, "--background", "--factory-startup",
            "--python", CONVERTER, "--",
            "--input", tmp.name, "--outdir", outdir,
            "--name", name, "--decimate", str(decimate), "--frame-step", str(step),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        finally:
            os.unlink(tmp.name)

        if proc.returncode != 0:
            tail = (proc.stdout + proc.stderr)[-1200:]
            return self._json(500, {"error": "échec conversion Blender", "log": tail})

        try:
            with open(os.path.join(outdir, "manifest.json")) as f:
                mani = json.load(f)
        except Exception as e:
            return self._json(500, {"error": f"pas de manifest : {e}"})

        if SINGLE:
            wipe_models(keep=name)
        write_models_json()
        return self._json(200, {"name": name, "frameCount": mani.get("frameCount", 0)})


def wipe_models(keep=None):
    if not os.path.isdir(MODELS):
        return
    for d in os.listdir(MODELS):
        p = os.path.join(MODELS, d)
        if d != keep and os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)


def list_models():
    if not os.path.isdir(MODELS):
        return []
    return sorted(
        d for d in os.listdir(MODELS)
        if os.path.isfile(os.path.join(MODELS, d, "manifest.json"))
    )


def write_models_json():
    """Keep viewer/models.json in sync so a static host (GitHub Pages) has the list."""
    try:
        with open(os.path.join(ROOT, "models.json"), "w") as f:
            json.dump(list_models(), f)
    except Exception as e:
        sys.stderr.write("models.json: %s\n" % e)


def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ips.add(s.getsockname()[0]); s.close()
    except Exception:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


if __name__ == "__main__":
    if FRESH:
        wipe_models()
    write_models_json()
    print(f"viewer  : {ROOT}")
    print(f"blender : {BLENDER or 'INTROUVABLE — défnis BLENDER=...'}")
    print(f"mode    : {'single (chaque import remplace)' if SINGLE else 'accumule'}"
          f"{'  + fresh (models vidés au démarrage)' if FRESH else ''}")
    print(f"  local : http://localhost:{PORT}/")
    for ip in lan_ips():
        print(f"  LAN   : http://{ip}:{PORT}/")
    print("Glisse un fichier sur la page pour l'importer. Ctrl+C pour arrêter.\n")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")
