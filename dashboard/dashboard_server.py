# ==============================================================================
# DOOMSDAY ENGINE V6 — dashboard/dashboard_server.py
# Step 23 — server HTTP per la dashboard di monitoraggio V6
#
# Endpoint:
#   GET  /ping                → { ok, ts, version }
#   GET  /status.json         → legge engine_status.json (scritto dall'orchestratore)
#   GET  /config_istanze.json → legge config/instances.json + overrides runtime.json
#   GET  /log?n=&since=&filter= → ultime N righe di bot.log
#   POST /runtime.json        → merge conservativo di globali + overrides
#   GET  /robots.txt
#   GET  /*                   → file statici in dashboard/
# ==============================================================================
from __future__ import annotations

import http.server
import json
import os
import threading
import time

PORT = 8080
LOG_TAIL_LINES = 300
VERSION = "v6-step23"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp_int(v, default: int = 0, vmin: int | None = None, vmax: int | None = None) -> int:
    try:
        iv = int(float(v))
    except Exception:
        iv = int(default)
    if vmin is not None and iv < vmin:
        iv = vmin
    if vmax is not None and iv > vmax:
        iv = vmax
    return iv


def _merge_runtime(existing: dict, incoming: dict) -> dict:
    """Merge conservativo: preserva chiavi non presenti nell'incoming."""
    out = dict(existing or {})
    out.setdefault("globali", {})
    out.setdefault("overrides", {})
    out["overrides"].setdefault("mumu", {})

    inc_g = (incoming or {}).get("globali", {}) or {}
    inc_o = (incoming or {}).get("overrides", {}) or {}

    out["globali"].update(inc_g)

    if isinstance(inc_o, dict) and "mumu" in inc_o:
        if isinstance(inc_o.get("mumu"), dict):
            out["overrides"]["mumu"].update(inc_o["mumu"])
    elif isinstance(inc_o, dict):
        out["overrides"]["mumu"].update(inc_o)

    g = out.get("globali", {})
    if "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO" in g:
        g["RIFORNIMENTO_MAX_SPEDIZIONI_CICLO"] = _clamp_int(
            g["RIFORNIMENTO_MAX_SPEDIZIONI_CICLO"], default=5, vmin=0, vmax=50
        )
    return out


def _safe_write(wfile, data: bytes) -> None:
    try:
        wfile.write(data)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        pass


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def _make_handler(root_dir: str):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            # Serve file statici dalla cartella dashboard/
            super().__init__(*args, directory=root_dir, **kwargs)

        def log_message(self, fmt, *args):  # pylint: disable=arguments-differ
            pass  # silenzia log Apache-style

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("ngrok-skip-browser-warning", "true")
            super().end_headers()

        def do_OPTIONS(self):
            self.send_response(200)
            self.end_headers()

        # ------------------------------------------------------------------
        # GET dispatcher
        # ------------------------------------------------------------------
        def do_GET(self):
            path = self.path.split("?")[0]

            if path == "/ping":
                return self._json_ok({"ok": True, "ts": time.time(), "version": VERSION})

            if path == "/status.json":
                return self._serve_file_json(
                    os.path.join(root_dir, "..", "engine_status.json")
                )

            if path == "/config_istanze.json":
                return self._serve_config_istanze()

            if path.startswith("/log"):
                return self._serve_log()

            if path == "/robots.txt":
                body = b"User-agent: *\nAllow: /\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                _safe_write(self.wfile, body)
                return

            try:
                super().do_GET()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        # ------------------------------------------------------------------
        # POST dispatcher
        # ------------------------------------------------------------------
        def do_POST(self):
            path = self.path.split("?")[0]
            if path != "/runtime.json":
                self.send_response(404)
                self.end_headers()
                return

            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                incoming = json.loads(body.decode("utf-8"))

                rt_path = os.path.join(root_dir, "..", "runtime.json")

                try:
                    if os.path.exists(rt_path):
                        with open(rt_path, "r", encoding="utf-8") as fr:
                            existing = json.load(fr)
                    else:
                        existing = {}
                except Exception:
                    existing = {}

                merged = _merge_runtime(existing, incoming)

                tmp = rt_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fw:
                    json.dump(merged, fw, ensure_ascii=False, indent=2)
                os.replace(tmp, rt_path)

                return self._json_ok({"ok": True})
            except Exception as exc:
                return self._json_err(str(exc))

        # ------------------------------------------------------------------
        # Handlers specifici
        # ------------------------------------------------------------------
        def _serve_file_json(self, filepath: str):
            """Serve un file JSON dal filesystem."""
            try:
                abs_path = os.path.abspath(filepath)
                if not os.path.exists(abs_path):
                    return self._json_ok({})
                with open(abs_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return self._json_ok(data)
            except Exception as exc:
                return self._json_err(str(exc))

        def _serve_log(self):
            try:
                from urllib.parse import parse_qs, urlparse

                qs = parse_qs(urlparse(self.path).query)
                n = int(qs.get("n", [LOG_TAIL_LINES])[0])
                since = qs.get("since", [None])[0]
                filtro = qs.get("filter", [None])[0]

                log_path = os.path.join(root_dir, "..", "bot.log")
                if not os.path.exists(log_path):
                    return self._json_ok({"righe": [], "totale": 0})

                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    righe = f.readlines()

                if filtro:
                    righe = [r for r in righe if filtro in r]

                if since:
                    righe = [r for r in righe if r[1:9] >= since]

                righe = righe[-n:]
                return self._json_ok(
                    {"righe": [r.rstrip("\n") for r in righe], "totale": len(righe), "ts": time.time()}
                )
            except Exception as exc:
                return self._json_err(str(exc))

        def _serve_config_istanze(self):
            """
            Legge config/instances.json e runtime.json → restituisce istanze MuMu
            con overrides già applicati (la dashboard mostra il valore "effettivo"
            così il delta = 0 se l'utente non modifica nulla).
            """
            try:
                # Leggi instances.json
                inst_path = os.path.join(root_dir, "..", "config", "instances.json")
                try:
                    with open(inst_path, "r", encoding="utf-8") as f:
                        instances_raw = json.load(f)
                except Exception:
                    instances_raw = []

                # Leggi overrides da runtime.json
                rt_path = os.path.join(root_dir, "..", "runtime.json")
                try:
                    with open(rt_path, "r", encoding="utf-8") as f:
                        rt = json.load(f)
                except Exception:
                    rt = {}
                ovr_mumu = rt.get("overrides", {}).get("mumu", {})

                def _enrich(raw: dict) -> dict:
                    nome = raw.get("nome", "")
                    ovr = ovr_mumu.get(nome, {})
                    return {
                        "nome": nome,
                        "indice": raw.get("indice", ""),
                        "porta": raw.get("porta", 16384),
                        "truppe": ovr.get("truppe", raw.get("truppe", 12000)),
                        "max_squadre": ovr.get("max_squadre", raw.get("max_squadre", 4)),
                        "layout": ovr.get("layout", raw.get("layout", 1)),
                        "lingua": ovr.get("lingua", raw.get("lingua", "en")),
                        "abilitata": ovr.get("abilitata", raw.get("abilitata", True)),
                        "livello": ovr.get("livello", raw.get("livello", 6)),
                        "profilo": ovr.get("profilo", raw.get("profilo", "full")),
                        "fascia_oraria": ovr.get("fascia_oraria", raw.get("fascia_oraria", "")),
                    }

                payload = {
                    "istanze_mumu": [_enrich(i) for i in instances_raw],
                }
                return self._json_ok(payload)
            except Exception as exc:
                return self._json_err(str(exc))

        # ------------------------------------------------------------------
        # Response helpers
        # ------------------------------------------------------------------
        def _json_ok(self, payload: dict, status: int = 200):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            _safe_write(self.wfile, body)

        def _json_err(self, msg: str, status: int = 500):
            body = json.dumps({"ok": False, "error": msg}, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            _safe_write(self.wfile, body)

    return Handler


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _run():
    # Cartella che contiene questo file = dashboard/
    dashboard_dir = os.path.dirname(os.path.abspath(__file__))
    Handler = _make_handler(dashboard_dir)
    server = http.server.HTTPServer(("", PORT), Handler)
    print(f"[dashboard] Server V6 → http://localhost:{PORT}/dashboard.html")
    server.serve_forever()


def avvia():
    """Avvia il server in background (chiamata dall'orchestratore)."""
    t = threading.Thread(target=_run, daemon=True)
    t.start()


if __name__ == "__main__":
    _run()
