"""Costruisce/valida il catalogo nodi mappa dal dataset osservazioni (WU173).

Uso:
    python tools/costruisci_catalogo_nodi.py [--prod] [--days N] [--write]
    python tools/costruisci_catalogo_nodi.py --prod --write

Legge data/nodi_mappa_observations.jsonl (popolato passivamente da
tasks/raccolta.py ad ogni ricerca CERCA — vedi shared/nodi_mappa.py) e
costruisce, per ogni coordinata osservata, il tipo/livello più probabile
(majority vote sulle osservazioni concordanti).

WU175 (25/06/2026) — feedback utente: i nodi con esito SOLO
"fuori_territorio" non hanno nessuna utilità per la mappatura (il bot non
li occupa mai, sono permanentemente skippati) e venivano confusi con i nodi
realmente occupabili (es. 696_532: 49 osservazioni, tutte "fuori_territorio",
mai una sola occupazione reale — il conteggio alto era pura frequenza di
scoperta/scarto durante la ricerca, non segnale di occupazione). Il catalogo
ora include SOLO coordinate con almeno una osservazione "trovato" (= nodo
in territorio, realmente occupato/occupabile dal bot). Le coordinate
"solo fuori_territorio" sono contate a parte, escluse dal catalogo.

Per ogni coordinata nel catalogo viene anche tracciata `ultima_istanza`
(quale istanza ha effettuato l'ultima occupazione reale, esito="trovato")
e `ultima_occupazione_ts`.

WU176 (25/06/2026) — feedback utente: il dataset iniziale (357 osservazioni)
è stato minato una tantum dai log testuali PRIMA che l'hook live in
tasks/raccolta.py iniziasse a scrivere (bootstrap, vedi SEED_CUTOFF_TS).
Mostrare `ultima_istanza` calcolata anche su quelle osservazioni storiche
è ingannevole — sembra un dato "appena successo" ma può risalire a ore
prima dell'attivazione del sistema live. `ultima_istanza`/
`ultima_occupazione_ts` vengono quindi popolati SOLO se esiste almeno una
osservazione "trovato" con ts >= SEED_CUTOFF_TS; altrimenti restano None
("non ancora rilevato dal vivo" lato dashboard) anche se il nodo è
comunque nel catalogo (tipo/livello/confidenza usano tutto lo storico,
seed incluso — quello resta valido come prova di identità del nodo).

Output (sempre):
    1. Totali: osservazioni trovato vs fuori_territorio, coordinate distinte
    2. Distribuzione confidenza (solo nodi in territorio)
    3. Coordinate INSTABILI (tipo/livello discordanti tra osservazioni) —
       da rivedere manualmente, possibile collisione OCR o respawn reale
    4. Conferme cross-istanza (prova di mappa condivisa, alta confidenza)
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

# WU176: spartiacque tra seed storico (mining log una tantum, pre-hook) e
# dati genuinamente live (scritti da shared/nodi_mappa.py::registra_osservazione
# durante l'esecuzione reale del bot). Corrisponde al boot del bot prod che ha
# caricato per primo il codice dell'hook (vedi data/restart_state.json al
# momento dell'introduzione WU173). Fisso: il seed non cresce più, non serve
# aggiornarlo nelle sessioni successive.
SEED_CUTOFF_TS = datetime(2026, 6, 25, 9, 52, 5, tzinfo=timezone.utc)

# Istanze le cui osservazioni vanno escluse (lettura coordinate non
# attendibile — vedi shared/nodi_mappa.py::ISTANZE_ESCLUSE). Ridichiarato
# qui per analizzare anche dataset legacy/mining manuale che potrebbero
# non aver applicato il filtro alla fonte.
ISTANZE_ESCLUSE = {"FauMorfeus"}


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
    obs_path = root / "data" / "nodi_mappa_observations.jsonl"
    cat_path = root / "data" / "nodi_mappa_catalogo.json"
    meta_path = root / "data" / "nodi_mappa_catalogo_meta.json"

    if not obs_path.exists():
        print(f"Dataset osservazioni non trovato: {obs_path}")
        return 1

    cutoff = None
    if args.days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    # WU175: separazione netta — solo esito="trovato" entra nel catalogo
    # (nodi in territorio, realmente occupati/occupabili). "fuori_territorio"
    # viene contato a parte, nessuna utilità per la mappatura.
    by_chiave: dict[str, list[dict]] = defaultdict(list)
    chiavi_fuori_territorio: set[str] = set()
    n_scartate_istanza = 0
    n_righe = 0
    n_trovato = 0
    n_fuori_territorio = 0

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

            if r.get("esito") == "fuori_territorio":
                n_fuori_territorio += 1
                chiavi_fuori_territorio.add(r["chiave"])
                continue

            n_trovato += 1
            by_chiave[r["chiave"]].append(r)

    # Coordinate "solo fuori territorio" = non hanno NESSUNA osservazione
    # trovato — mai occupate, nessuna utilità per il catalogo.
    chiavi_solo_fuori = chiavi_fuori_territorio - set(by_chiave.keys())

    print(f"=== Osservazioni totali nel file: {n_righe} "
          f"(scartate istanze escluse: {n_scartate_istanza}) ===")
    print(f"=== trovato (in territorio): {n_trovato}   "
          f"fuori_territorio (solo scarto, nessuna utilità): {n_fuori_territorio} ===")
    print(f"=== Coordinate in territorio (catalogo): {len(by_chiave)}   "
          f"Coordinate SOLO fuori territorio (escluse): {len(chiavi_solo_fuori)} ===\n")

    if not by_chiave:
        print("Nessuna osservazione 'trovato' nel periodo (dopo esclusioni) — "
              "catalogo vuoto, nessun nodo in territorio osservato.")
        return 0

    # ── Sezione 2: distribuzione confidenza ──────────────────────────────
    dist_n_oss = Counter(len(obs) for obs in by_chiave.values())
    print("--- Distribuzione osservazioni per coordinata (solo in territorio) ---")
    for n_oss in sorted(dist_n_oss):
        print(f"  {n_oss:>3} osservazioni  ->  {dist_n_oss[n_oss]:>4} coordinate")
    print()

    # ── Costruzione catalogo (majority vote, solo esito=trovato) ─────────
    catalogo: dict[str, dict] = {}
    instabili: list[dict] = []
    confermate_cross_istanza: list[dict] = []
    n_concordanti_2plus = 0
    n_ricorrenti = 0
    n_senza_occupante_live = 0

    for chiave, obs in by_chiave.items():
        coppie = Counter((o["tipo"], o["livello"]) for o in obs)
        (tipo_top, liv_top), n_top = coppie.most_common(1)[0]
        istanze = sorted(set(o["instance"] for o in obs))
        cx = obs[0]["cx"]
        cy = obs[0]["cy"]

        obs_ordinate = sorted(obs, key=lambda o: o["ts"])
        ultima = obs_ordinate[-1]

        # WU176: ultima_istanza/ultima_occupazione_ts SOLO da osservazioni
        # live (post seed-cutoff) — mai dal seed storico minato dai log.
        obs_live = [o for o in obs_ordinate if datetime.fromisoformat(o["ts"]) >= SEED_CUTOFF_TS]
        if obs_live:
            ultima_live = obs_live[-1]
            ultima_istanza = ultima_live["instance"]
            ultima_occupazione_ts = ultima_live["ts"]
        else:
            n_senza_occupante_live += 1
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
    print(f"--- Coordinate INSTABILI (tipo/livello discordanti): "
          f"{len(instabili)} ---")
    if not instabili:
        print("  (nessuna)")
    for r in sorted(instabili, key=lambda x: -len(x["obs"])):
        print(f"  {r['chiave']}  varianti={r['varianti']}  istanze={r['istanze']}")
        for o in sorted(r["obs"], key=lambda x: x["ts"]):
            print(f"      {o['ts']}  {o['instance']:12s} "
                  f"tipo={o['tipo']:10s} Lv.{o['livello']}")
    print()

    # ── Sezione 4: conferme cross-istanza ─────────────────────────────────
    print(f"--- Conferme cross-istanza (alta confidenza): "
          f"{len(confermate_cross_istanza)} ---")
    for r in sorted(confermate_cross_istanza, key=lambda x: -x["n_oss"])[:20]:
        print(f"  {r['chiave']}  tipo={r['tipo']:<10} Lv.{r['livello']}  "
              f"n_oss={r['n_oss']:>3}  istanze={r['istanze']}")
    if len(confermate_cross_istanza) > 20:
        print(f"  ... e altre {len(confermate_cross_istanza) - 20}")
    print()

    # ── Sezione 4b: freschezza ultima_istanza (WU176) ──────────────────────
    print(f"--- Occupante live (post seed-cutoff {SEED_CUTOFF_TS.isoformat()}) ---")
    print(f"  Con ultima_istanza live:     {len(catalogo) - n_senza_occupante_live}")
    print(f"  Senza occupante live ancora: {n_senza_occupante_live}  "
          f"(mostrano '—' in dashboard finché non rivisitati dal bot)")
    print()

    # ── Sezione 5: verdetto maturità ──────────────────────────────────────
    quota_matura = n_concordanti_2plus / n_ricorrenti if n_ricorrenti else 0.0
    print("--- Verdetto maturità dataset (solo nodi in territorio) ---")
    print(f"  Coordinate ricorrenti (>1 oss.):              {n_ricorrenti}")
    print(f"  ...di cui concordanti >= {SOGLIA_CONFIDENZA_MIN} oss.:          "
          f"{n_concordanti_2plus}  ({quota_matura*100:.1f}%)")
    print(f"  Coordinate viste 1 sola volta (immature):     "
          f"{len(by_chiave) - n_ricorrenti}")
    if quota_matura >= SOGLIA_COPERTURA_MATURA and n_ricorrenti >= 20:
        print(f"  -> MATURO: {quota_matura*100:.1f}% >= soglia "
              f"{SOGLIA_COPERTURA_MATURA*100:.0f}%, campione sufficiente.")
    else:
        print(f"  -> NON ANCORA MATURO (soglia {SOGLIA_COPERTURA_MATURA*100:.0f}%, "
              f"min 20 coordinate ricorrenti) — continuare a raccogliere cicli.")
    print()

    if args.write:
        cat_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cat_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(catalogo, f, indent=2, ensure_ascii=False, sort_keys=True)
        tmp.replace(cat_path)
        print(f"Catalogo scritto: {cat_path}  ({len(catalogo)} coordinate in territorio)")

        meta = {
            "generato_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_coordinate_territorio": len(catalogo),
            "n_coordinate_solo_fuori_territorio": len(chiavi_solo_fuori),
            "n_osservazioni_trovato": n_trovato,
            "n_osservazioni_fuori_territorio": n_fuori_territorio,
            "n_senza_occupante_live": n_senza_occupante_live,
            "seed_cutoff_ts": SEED_CUTOFF_TS.isoformat(),
        }
        tmp_meta = meta_path.with_suffix(".json.tmp")
        with open(tmp_meta, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        tmp_meta.replace(meta_path)
        print(f"Meta scritto: {meta_path}")
    else:
        print("(--write non specificato — nessun file scritto, solo report)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
