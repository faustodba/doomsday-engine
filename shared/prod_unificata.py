# ==============================================================================
#  DOOMSDAY ENGINE V6 — shared/prod_unificata.py
#
#  Produzione oraria unificata per istanza.
#
#  Metrica: M pomodoro-equivalente / 24h
#  Fonte:   state/<nome>.json::rifornimento.dettaglio_oggi (inviato netto)
#  Denominatore: 24h fisso (wall-clock) — le squadre producono continuamente;
#                non si usa il tick_total_s del bot (tempo di esecuzione task)
#
#  Pesi derivati dai cap nominali L7:
#    pomodoro = 1.0  (base: 1.32M/nodo)
#    legno    = 1.0  (1.32M/nodo, identico)
#    acciaio  = 2.0  (1.32M / 660K — lo stesso slot vale il doppio in pom-eq)
#    petrolio = 5.0  (1.32M / 264K)
#
#  Nota: la metrica misura il contributo INVIATO al master, non la produzione
#  totale del castello (che include anche quello tenuto nei depositi).
#  È la metrica rilevante per la gestione della farm.
# ==============================================================================

from __future__ import annotations

# Mapping tipo raccolta (bot internal) → risorsa standard
TIPO_TO_RISORSA: dict[str, str] = {
    "campo":    "pomodoro",
    "segheria": "legno",
    "acciaio":  "acciaio",
    "petrolio": "petrolio",
    # alias diretti
    "pomodoro": "pomodoro",
    "legno":    "legno",
}

# Cap nominale (risorsa, livello) — usato solo come riferimento esterno, non nel calcolo
CAP_NOMINALE: dict[tuple[str, int], int] = {
    ("pomodoro", 6): 1_200_000,  ("pomodoro", 7): 1_320_000,
    ("legno",    6): 1_200_000,  ("legno",    7): 1_320_000,
    ("acciaio",  6):   600_000,  ("acciaio",  7):   660_000,
    ("petrolio", 6):   240_000,  ("petrolio", 7):   264_000,
}

# Pesi: cap_L7_pomodoro / cap_L7_risorsa
PESI: dict[str, float] = {
    "pomodoro": 1.0,
    "legno":    1.0,
    "acciaio":  2.0,
    "petrolio": 5.0,
}

_M  = 1_000_000   # unità output (M)
_H  = 24.0        # finestra fissa in ore


def compute_from_dettaglio(dettaglio_oggi: list[dict]) -> dict:
    """
    Calcola prod_unif_h da dettaglio_oggi (lista spedizioni della giornata).

    Argomento: state["rifornimento"]["dettaglio_oggi"] già caricato.
    Ritorna dict con:
      prod_unif_h   : float — M pom-eq/24h  (-1 se nessun dato)
      pom_eq_totale : int   — pom-eq grezzo
      n_sped        : int   — spedizioni contate
      per_risorsa   : dict  — {risorsa: {qta_tot, n, pom_eq}}
    """
    pom_eq_totale = 0
    n_sped        = 0
    per_risorsa: dict[str, dict] = {}

    for v in (dettaglio_oggi or []):
        risorsa = str(v.get("risorsa", "") or "")
        qta     = int(v.get("qta_inviata", 0) or 0)
        if not risorsa or qta <= 0:
            continue
        peso   = PESI.get(risorsa, 1.0)
        pom_eq = int(qta * peso)
        pom_eq_totale += pom_eq
        n_sped        += 1
        pr = per_risorsa.setdefault(risorsa, {"qta_tot": 0, "n": 0, "pom_eq": 0})
        pr["qta_tot"] += qta
        pr["n"]       += 1
        pr["pom_eq"]  += pom_eq

    if pom_eq_totale > 0:
        prod_unif_h = round(pom_eq_totale / _H / _M, 3)
    else:
        prod_unif_h = -1.0

    return {
        "prod_unif_h":   prod_unif_h,
        "pom_eq_totale": pom_eq_totale,
        "n_sped":        n_sped,
        "per_risorsa":   per_risorsa,
    }


def empty_result() -> dict:
    return {
        "prod_unif_h":   -1.0,
        "pom_eq_totale": 0,
        "n_sped":        0,
        "per_risorsa":   {},
    }
