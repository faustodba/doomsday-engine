"""Costruisce/valida il catalogo nodi mappa dal dataset osservazioni (WU173).

Uso:
    python tools/costruisci_catalogo_nodi.py [--prod] [--days N] [--write]
    python tools/costruisci_catalogo_nodi.py --prod --write

Legge data/nodi_mappa_observations.jsonl (popolato passivamente da
tasks/raccolta.py — vedi shared/nodi_mappa.py) e costruisce, per ogni
coordinata osservata, il tipo/livello più probabile (majority vote sulle
osservazioni concordanti).

WU175 (25/06/2026) — feedback utente: i nodi con esito SOLO
"fuori_territorio" non hanno nessuna utilità per la mappatura (il bot non
li occupa mai, sono permanentemente skippati) e venivano confusi con i nodi
realmente occupabili (es. 696_532: 49 osservazioni, tutte "fuori_territorio",
mai una sola occupazione reale). Il catalogo include SOLO coordinate con
almeno una osservazione "trovato" (= nodo in territorio). Le coordinate
"solo fuori_territorio" sono contate a parte, escluse dal catalogo.

WU177 (25/06/2026) — chiarimento utente: "osservazione" e "occupazione" sono
DUE EVENTI DISTINTI nel flusso raccolta (non lo stesso evento con un filtro
temporale arbitrario, come nel tentativo WU176 con SEED_CUTOFF_TS, ora
superato):
  - "trovato"          — CERCA + lettura coordinata (tasks/raccolta.py,
                          "nodo trovato a Lv.N — procedo" + "RESERVED").
                          Il nodo esiste, tipo/livello letti, marcia non
                          ancora tentata. Alimenta prima/ultima_osservazione
                          + il majority vote tipo/livello.
  - "fuori_territorio"  — CERCA + lettura coordinata, nodo scartato perché
                          in blacklist permanente. Nessuna utilità mappatura.
  - "occupato"          — marcia CONFERMATA (post blacklist.commit, dopo
                          _esegui_marcia riuscita). Alimenta SOLO
                          ultima_istanza/ultima_occupazione_ts. Non esiste
                          nel seed storico (mai minato dai log, solo
                          "trovato"/fuori_territorio lo furono) — è quindi
                          intrinsecamente dato live, nessun cutoff arbitrario
                          necessario.

WU178 (25/06/2026) — la logica di build è stata estratta in `build_catalogo()`
per poterla richiamare anche da un background task della dashboard (rebuild
automatico periodico) e non solo da questa CLI. Vedi
dashboard/app.py::_nodi_mappa_rebuild_loop().

Output (sempre, anche da dashboard via build_catalogo(verbose=True)):
    1. Totali: osservazioni trovato/fuori_territorio/occupato, coordinate
    2. Distribuzione confidenza (solo nodi in territorio)
    3. Coordinate INSTABILI (tipo/livello discordanti tra osservazioni) —
       da rivedere manualmente, possibile collisione OCR o respawn reale
    4. Conferme cross-istanza (prova di mappa condivisa, alta confidenza)
    4b. Copertura occupazione confermata (quanti nodi hanno >=1 "occupato")
    5. Verdetto di maturità del dataset (soglia configurabile sotto)

Con --write: persiste il catalogo aggregato in data/nodi_mappa_catalogo.json
(schema minimale, pensato per un futuro consumo da tasks/raccolta.py — NON
ancora usato in produzione, fase 2 del WU173, gating manuale dell'utente).

Soglia di maturità (solo a scopo di report, non blocca --write):
    SOGLIA_CONFIDENZA_MIN = 2   osservazioni concordanti minime per
                                considerare una coordinata "attendibile"
    SOGLIA_COPERTURA_MATURA = 0.70   quota di coordinate ricorrenti che deve
                                      superare la soglia di confidenza prima
                                      di considerare il dataset maturo
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

SOGLIA_CONFIDENZA_MIN = 2
SOGLIA_COPERTURA_MATURA = 0.70

# Istanze le cui osservazioni vanno escluse (lettura coordinate non
# attendibile — vedi shared/nodi_mappa.py::ISTANZE_ESCLUSE). Ridichiarato
# qui per analizzare anche dataset legacy/mining manuale che potrebbero
# non aver applicato il filtro alla fonte.
ISTANZE_ESCLUSE = {"FauMorfeus"}


def build_catalogo(root: Path, days: int = 0, write: bool = True,
                    verbose: bool = True) -> dict:
    """
    Costruisce (ed eventualmente persiste) il catalogo nodi mappa.

    Ritorna sempre il dict `meta` (anche se write=False, in tal caso senza
    scrivere nulla su disco) — utile per loggare un riepilogo da un caller
    Python (es. background task dashboard) senza dover fare parsing di stdout.
    """
    def log(msg: str = "") -> None:
        if verbose:
            print(msg)

    obs_path = root / "data" / "nodi_mappa_observations.jsonl"
    cat_path = root / "data" / "nodi_mappa_catalogo.json"
    meta_path = root / "data" / "nodi_mappa_catalogo_meta.json"

    if not obs_path.exists():
        log(f"Dataset osservazioni non trovato: {obs_path}")
        return {"errore": "dataset_non_trovato"}

    cutoff = None
    if days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # WU175/WU177: 3 esiti separati. "trovato" -> membership catalogo +
    # tipo/livello + prima/ultima_osservazione. "occupato" -> SOLO
    # ultima_istanza/ultima_occupazione_ts. "fuori_territorio" -> escluso,
    # contato a parte.
    by_chiave: dict[str, list[dict]] = defaultdict(list)
    by_chiave_occupato: dict[str, list[dict]] = defaultdict(list)
    chiavi_fuori_territorio: set[str] = set()
    n_scartate_istanza = 0
    n_righe = 0
    n_trovato = 0
    n_fuori_territorio = 0
    n_occupato = 0

    with obs_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            n_righe += 1
            if r.get("instance") in ISTANZE_ESCLUSE:
                n_scartate_istanza += 1
                continue
            if cutoff is not None:
                try:
                    ts = datetime.fromisoformat(r["ts"])
                    if ts < cutoff:
                        continue
                except Exception:
                    pass

            esito = r.get("esito")
            if esito == "fuori_territorio":
                n_fuori_territorio += 1
                chiavi_fuori_territorio.add(r["chiave"])
                continue
            if esito == "occupato":
                n_occupato += 1
                by_chiave_occupato[r["chiave"]].append(r)
                continue

            n_trovato += 1
            by_chiave[r["chiave"]].append(r)

    # Coordinate "solo fuori territorio" = non hanno NESSUNA osservazione
    # trovato — mai occupate, nessuna utilità per il catalogo.
    chiavi_solo_fuori = chiavi_fuori_territorio - set(by_chiave.keys())

    log(f"=== Osservazioni totali nel file: {n_righe} "
        f"(scartate istanze escluse: {n_scartate_istanza}) ===")
    log(f"=== trovato: {n_trovato}   occupato (marcia confermata): {n_occupato}   "
        f"fuori_territorio (nessuna utilità): {n_fuori_territorio} ===")
    log(f"=== Coordinate in territorio (catalogo): {len(by_chiave)}   "
        f"Coordinate SOLO fuori territorio (escluse): {len(chiavi_solo_fuori)} ===\n")

    if not by_chiave:
        log("Nessuna osservazione 'trovato' nel periodo (dopo esclusioni) — "
            "catalogo vuoto, nessun nodo in territorio osservato.")
        return {"n_coordinate_territorio": 0}

    # ── Sezione 2: distribuzione confidenza ──────────────────────────────
    dist_n_oss = Counter(len(obs) for obs in by_chiave.values())
    log("--- Distribuzione osservazioni per coordinata (solo in territorio) ---")
    for n_oss in sorted(dist_n_oss):
        log(f"  {n_oss:>3} osservazioni  ->  {dist_n_oss[n_oss]:>4} coordinate")
    log()

    # ── Costruzione catalogo (majority vote su "trovato") ────────────────
    catalogo: dict[str, dict] = {}
    instabili: list[dict] = []
    confermate_cross_istanza: list[dict] = []
    n_concordanti_2plus = 0
    n_ricorrenti = 0
    n_senza_occupazione_confermata = 0

    for chiave, obs in by_chiave.items():
        coppie = Counter((o["tipo"], o["livello"]) for o in obs)
        (tipo_top, liv_top), n_top = coppie.most_common(1)[0]
        istanze = sorted(set(o["instance"] for o in obs))
        cx = obs[0]["cx"]
        cy = obs[0]["cy"]

        obs_ordinate = sorted(obs, key=lambda o: o["ts"])
        ultima = obs_ordinate[-1]

        # WU177: ultima_istanza/ultima_occupazione_ts SOLO da esito="occupato"
        # (marcia confermata) — evento distinto da "trovato", mai dal seed.
        occ = by_chiave_occupato.get(chiave)
        if occ:
            ultima_occ = sorted(occ, key=lambda o: o["ts"])[-1]
            ultima_istanza = ultima_occ["instance"]
            ultima_occupazione_ts = ultima_occ["ts"]
        else:
            n_senza_occupazione_confermata += 1
            ultima_istanza = None
            ultima_occupazione_ts = None

        entry = {
            "cx": cx, "cy": cy,
            "tipo": tipo_top, "livello": liv_top,
            "n_osservazioni": len(obs),
            "n_concordanti": n_top,
            "n_istanze": len(istanze),
            "prima_osservazione": obs_ordinate[0]["ts"],
            "ultima_osservazione": ultima["ts"],
            "ultima_istanza": ultima_istanza,
            "ultima_occupazione_ts": ultima_occupazione_ts,
        }
        catalogo[chiave] = entry

        if len(obs) > 1:
            n_ricorrenti += 1
            if len(coppie) > 1:
                instabili.append({
                    "chiave": chiave,
                    "varianti": dict(coppie),
                    "istanze": istanze,
                    "obs": obs,
                })
            elif n_top >= SOGLIA_CONFIDENZA_MIN:
                n_concordanti_2plus += 1
                if len(istanze) > 1:
                    confermate_cross_istanza.append({
                        "chiave": chiave, "tipo": tipo_top, "livello": liv_top,
                        "n_oss": n_top, "istanze": istanze,
                    })

    # ── Sezione 3: instabili ──────────────────────────────────────────────
    log(f"--- Coordinate INSTABILI (tipo/livello discordanti): "
        f"{len(instabili)} ---")
    if not instabili:
        log("  (nessuna)")
    for r in sorted(instabili, key=lambda x: -len(x["obs"])):
        log(f"  {r['chiave']}  varianti={r['varianti']}  istanze={r['istanze']}")
        for o in sorted(r["obs"], key=lambda x: x["ts"]):
            log(f"      {o['ts']}  {o['instance']:12s} "
                f"tipo={o['tipo']:10s} Lv.{o['livello']}")
    log()

    # ── Sezione 4: conferme cross-istanza ─────────────────────────────────
    log(f"--- Conferme cross-istanza (alta confidenza): "
        f"{len(confermate_cross_istanza)} ---")
    for r in sorted(confermate_cross_istanza, key=lambda x: -x["n_oss"])[:20]:
        log(f"  {r['chiave']}  tipo={r['tipo']:<10} Lv.{r['livello']}  "
            f"n_oss={r['n_oss']:>3}  istanze={r['istanze']}")
    if len(confermate_cross_istanza) > 20:
        log(f"  ... e altre {len(confermate_cross_istanza) - 20}")
    log()

    # ── Sezione 4b: copertura occupazione confermata (WU177) ──────────────
    log("--- Occupazione confermata (esito='occupato', marcia riuscita) ---")
    log(f"  Nodi con ultima_istanza nota:        {len(catalogo) - n_senza_occupazione_confermata}")
    log(f"  Nodi senza occupazione confermata:   {n_senza_occupazione_confermata}  "
        f"(mostrano '—' in dashboard finché una marcia non viene completata)")
    log()

    # ── Sezione 5: verdetto maturità ──────────────────────────────────────
    quota_matura = n_concordanti_2plus / n_ricorrenti if n_ricorrenti else 0.0
    log("--- Verdetto maturità dataset (solo nodi in territorio) ---")
    log(f"  Coordinate ricorrenti (>1 oss.):              {n_ricorrenti}")
    log(f"  ...di cui concordanti >= {SOGLIA_CONFIDENZA_MIN} oss.:          "
        f"{n_concordanti_2plus}  ({quota_matura*100:.1f}%)")
    log(f"  Coordinate viste 1 sola volta (immature):     "
        f"{len(by_chiave) - n_ricorrenti}")
    if quota_matura >= SOGLIA_COPERTURA_MATURA and n_ricorrenti >= 20:
        log(f"  -> MATURO: {quota_matura*100:.1f}% >= soglia "
            f"{SOGLIA_COPERTURA_MATURA*100:.0f}%, campione sufficiente.")
    else:
        log(f"  -> NON ANCORA MATURO (soglia {SOGLIA_COPERTURA_MATURA*100:.0f}%, "
            f"min 20 coordinate ricorrenti) — continuare a raccogliere cicli.")
    log()

    meta = {
        "generato_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_coordinate_territorio": len(catalogo),
        "n_coordinate_solo_fuori_territorio": len(chiavi_solo_fuori),
        "n_osservazioni_trovato": n_trovato,
        "n_osservazioni_occupato": n_occupato,
        "n_osservazioni_fuori_territorio": n_fuori_territorio,
        "n_senza_occupante_live": n_senza_occupazione_confermata,
    }

    if write:
        cat_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cat_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(catalogo, f, indent=2, ensure_ascii=False, sort_keys=True)
        tmp.replace(cat_path)
        log(f"Catalogo scritto: {cat_path}  ({len(catalogo)} coordinate in territorio)")

        tmp_meta = meta_path.with_suffix(".json.tmp")
        with open(tmp_meta, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        tmp_meta.replace(meta_path)
        log(f"Meta scritto: {meta_path}")
    else:
        log("(write=False — nessun file scritto, solo report)")

    return meta


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prod", action="store_true",
                        help="Usa C:/doomsday-engine-prod/data invece di dev")
    parser.add_argument("--days", type=int, default=0,
                        help="Solo ultimi N giorni (0 = tutto)")
    parser.add_argument("--write", action="store_true",
                        help="Persiste data/nodi_mappa_catalogo.json")
    args = parser.parse_args()

    root = Path("C:/doomsday-engine-prod") if args.prod else Path("C:/doomsday-engine")
    meta = build_catalogo(root, days=args.days, write=args.write, verbose=True)
    return 1 if "errore" in meta else 0


if __name__ == "__main__":
    sys.exit(main())
