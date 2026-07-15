"""Ricostruzione di `data/tempo_raccolta_dataset.jsonl` dai due dataset sorgente.

WU225 (15/07) — `TTL_ORFANE_ORE` era 4.0 e potava le occupazioni pending prima
che il report del completamento venisse letto (il report esiste solo quando
l'istanza riparte e legge il tab: periodo di ciclo p50 3.46h). Risultato: 491
match su ~1202 coppie recuperabili, con **censura selettiva sulle raccolte
lente** (persi p50 3.00h/p90 3.89h vs matchati 2.82h/3.19h) — il dataset era
distorto verso il basso proprio nella coda che serve al predictor.

Alzare il TTL a 12.0 sistema il futuro ma non lo storico gia' perso. I due
dataset sorgente sono pero' intatti e append-only:
    data/nodi_mappa_observations.jsonl  (esito="occupato" = evento INVIO)
    data/report_raccolta_dataset.jsonl  (evento COMPLETAMENTO, tab Report)
quindi la storia e' interamente riproducibile: questo tool la rigioca da zero.

COME: NON reimplementa il matcher — azzera lo stato e richiama la
`esegui_riconciliazione()` di produzione su tutto lo storico in un colpo solo.
E' esattamente lo scenario previsto dal fix WU200quater ("primo run di recupero
su storico gia' accumulato"): l'ordine occupazioni->match->potatura fa si' che
ogni coppia valida venga abbinata PRIMA che il TTL possa scartare qualcosa.
Nessun rischio di divergenza fra ricostruzione e comportamento live, perche' e'
lo stesso identico codice.

Sicurezza:
  - dry-run di default: rigioca in una SANDBOX temporanea (copia dei soli
    sorgenti), non tocca nulla in prod, e stampa il confronto prima/dopo.
  - --apply: salva prima dataset+stato in data/archive/, poi ricostruisce.
    Reversibile: i backup bastano a tornare indietro.
  - Guard anti-race: il loop dashboard (`_tempo_raccolta_loop`, 15 min) scrive
    lo stesso stato. `_lock` e' un threading.Lock, quindi NON protegge fra
    processi. Il tool rifiuta l'--apply se la prossima passata e' imminente,
    lasciando una finestra ampia. Con la dashboard ferma il guard e' inutile
    ma innocuo (--force per saltarlo).

Uso CLI:
    py -3.14 tools/rebuild_tempo_raccolta_dataset.py --prod           # dry-run
    py -3.14 tools/rebuild_tempo_raccolta_dataset.py --prod --apply
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

_ROOT_DEV = Path(__file__).parent.parent
_ROOT_PROD = Path("C:/doomsday-engine-prod")

sys.path.insert(0, str(_ROOT_DEV))

_SORGENTI = ("data/nodi_mappa_observations.jsonl", "data/report_raccolta_dataset.jsonl")
_OUTPUT = "data/tempo_raccolta_dataset.jsonl"
_STATO = "data/tempo_raccolta_match_state.json"

# Margine minimo prima della prossima passata del loop dashboard (15 min).
_MARGINE_MIN_S = 180.0
_PERIODO_LOOP_S = 900.0


def _carica(path: Path) -> list[dict]:
    if not path.exists():
        return []
    righe = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                righe.append(json.loads(line))
            except Exception:
                continue
    return righe


def _stat_dataset(righe: list[dict]) -> dict:
    durate = sorted(r["durata_s"] / 3600 for r in righe
                    if isinstance(r.get("durata_s"), (int, float)))
    celle = Counter((r.get("instance"), r.get("tipo"), r.get("livello")) for r in righe)
    if not durate:
        return {"n": 0, "celle": 0, "celle_ok": 0}
    return {
        "n": len(righe),
        "celle": len(celle),
        "celle_ok": sum(1 for v in celle.values() if v >= 3),
        "p50": statistics.median(durate),
        "media": sum(durate) / len(durate),
        "p90": durate[int(len(durate) * 0.9)],
        "max": durate[-1],
        "implausibili": sum(1 for d in durate if d > 6),
    }


def _riga_stat(label: str, s: dict) -> str:
    if not s["n"]:
        return f"  {label:26} vuoto"
    return (f"  {label:26} n={s['n']:5}  celle={s['celle']:3} (>=3 camp.: {s['celle_ok']:3})"
            f"  p50={s['p50']:.2f}h media={s['media']:.2f}h p90={s['p90']:.2f}h"
            f" max={s['max']:.2f}h  >6h:{s['implausibili']}")


def _replay(root: Path) -> dict:
    """Azzera stato+output sotto `root` e rigioca tutto lo storico con la
    esegui_riconciliazione() di produzione. `root` deve gia' contenere i due
    sorgenti. Ritorna l'esito della riconciliazione."""
    os.environ["DOOMSDAY_ROOT"] = str(root)
    for mod in [m for m in sys.modules if "tempo_raccolta_estimator" in m]:
        del sys.modules[mod]
    from shared.tempo_raccolta_estimator import esegui_riconciliazione, TTL_ORFANE_ORE

    (root / _OUTPUT).parent.mkdir(parents=True, exist_ok=True)
    (root / _OUTPUT).write_text("", encoding="utf-8")
    (root / _STATO).write_text(
        json.dumps({"cursor_occupazioni": 0, "cursor_report": 0, "pending": {}}),
        encoding="utf-8")

    esito = esegui_riconciliazione()
    esito["ttl_usato"] = TTL_ORFANE_ORE
    return esito


def _guard_race(root: Path, force: bool) -> bool:
    """True se si puo' procedere. Il loop dashboard scrive lo stesso stato ogni
    15 min e `_lock` non protegge fra processi."""
    stato = root / _STATO
    if not stato.exists() or force:
        return True
    eta_s = datetime.now().timestamp() - stato.stat().st_mtime
    manca = _PERIODO_LOOP_S - (eta_s % _PERIODO_LOOP_S)
    print(f"  ultima passata dashboard: {eta_s:.0f}s fa · prossima stimata fra ~{manca:.0f}s")
    if manca < _MARGINE_MIN_S:
        print(f"  ABORT: margine < {_MARGINE_MIN_S:.0f}s. Rischio race sullo stato.")
        print("         Riprova fra qualche minuto, o ferma la dashboard, o usa --force.")
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prod", action="store_true", help="opera su C:/doomsday-engine-prod")
    ap.add_argument("--apply", action="store_true", help="scrive davvero (default: dry-run in sandbox)")
    ap.add_argument("--force", action="store_true", help="salta il guard anti-race")
    args = ap.parse_args()

    root = _ROOT_PROD if args.prod else _ROOT_DEV
    print(f"root: {root}")

    for s in _SORGENTI:
        p = root / s
        if not p.exists():
            print(f"ABORT: sorgente mancante: {p}")
            return 1
        print(f"  sorgente {s:44} {p.stat().st_size:>9} byte")

    prima = _stat_dataset(_carica(root / _OUTPUT))
    print()
    print(_riga_stat("PRIMA (dataset attuale)", prima))

    # --- DRY-RUN: replay in sandbox, prod intatta -----------------------------
    if not args.apply:
        sandbox = Path(tempfile.mkdtemp(prefix="rebuild_trd_"))
        (sandbox / "data").mkdir(parents=True)
        for s in _SORGENTI:
            shutil.copy2(root / s, sandbox / s)
        esito = _replay(sandbox)
        dopo = _stat_dataset(_carica(sandbox / _OUTPUT))
        print(_riga_stat("DOPO  (simulato)", dopo))
        print()
        print(f"  TTL usato: {esito['ttl_usato']}h · match={esito['match_nuovi']}"
              f" · report_orfani={esito['report_orfane']}"
              f" · potate={esito['occupazioni_potate']} · pending={esito['pending_attuali']}")
        if esito.get("errore"):
            print(f"  ERRORE: {esito['errore']}")
            return 1
        print(f"\n  guadagno: {prima['n']} -> {dopo['n']} match"
              f" (+{dopo['n'] - prima['n']}), celle >=3 campioni"
              f" {prima['celle_ok']} -> {dopo['celle_ok']}")
        shutil.rmtree(sandbox, ignore_errors=True)
        print("\n  DRY-RUN: niente e' stato scritto. Rilancia con --apply.")
        return 0

    # --- APPLY ----------------------------------------------------------------
    print()
    if not _guard_race(root, args.force):
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    arch = root / "data" / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    for src, nome in ((root / _OUTPUT, f"tempo_raccolta_dataset_pre-WU225_{ts}.jsonl"),
                      (root / _STATO, f"tempo_raccolta_match_state_pre-WU225_{ts}.json")):
        if src.exists():
            shutil.copy2(src, arch / nome)
            print(f"  backup: data/archive/{nome}")

    esito = _replay(root)
    dopo = _stat_dataset(_carica(root / _OUTPUT))
    print()
    print(_riga_stat("DOPO  (scritto)", dopo))
    print(f"\n  TTL usato: {esito['ttl_usato']}h · match={esito['match_nuovi']}"
          f" · report_orfani={esito['report_orfane']}"
          f" · potate={esito['occupazioni_potate']} · pending={esito['pending_attuali']}")
    if esito.get("errore"):
        print(f"  ERRORE: {esito['errore']}")
        return 1
    print(f"\n  guadagno: {prima['n']} -> {dopo['n']} match (+{dopo['n'] - prima['n']}),"
          f" celle >=3 campioni {prima['celle_ok']} -> {dopo['celle_ok']}")
    print("\n  Nessun riavvio necessario: bot e dashboard rileggono il dataset via"
          "\n  cache invalidata su (path, mtime, size) e lo stato ad ogni passata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
