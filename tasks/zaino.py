# ==============================================================================
#  DOOMSDAY ENGINE V6 — tasks/zaino.py                              Step 19
#
#  Scarico risorse dallo zaino virtuale (backpack) al deposito dell'istanza.
#
#  TRIGGER:
#    Periodico (168h — settimanale) via TaskScheduler.
#    Esegue solo SE il deposito di almeno una risorsa abilitata è sotto soglia.
#
#  LOGICA:
#    Per ogni risorsa abilitata e sotto soglia:
#      gap = target - deposito_attuale
#      Itera le pezzature dal più piccolo al più grande:
#        se pezzatura <= gap_residuo → usa MAX (USE → Max → USE)
#        se pezzatura > gap_residuo  → skip (troppo grande, sforerebbe)
#      Stop quando gap_residuo <= 0 o pezzature esaurite.
#
#  APERTURA ZAINO:
#    Tap sull'icona 🍅 nella barra alta → apre sempre su Food.
#    Per altre risorse → tap icona nella sidebar sinistra.
#
#  FLUSSO USE:
#    1. Tap USE sulla riga  → appare pulsante "Max" accanto
#    2. Tap Max             → seleziona tutti i pezzi di quella pezzatura
#    3. Tap USE             → conferma utilizzo → riga sparisce se owned=0
#
#  PACK MISTI: Basic/Intermediate/Advanced Resource Pack → ignorati.
#
#  COORDINATE DEFAULT (960x540):
#    TAP_ZAINO_APRI      = (430, 18)   — icona 🍅 barra alta
#    TAP_ZAINO_CHIUDI    = (783, 68)   — pulsante X
#    SIDEBAR_POMODORO    = (80, 130)
#    SIDEBAR_LEGNO       = (80, 200)
#    SIDEBAR_ACCIAIO     = (80, 270)
#    SIDEBAR_PETROLIO    = (80, 340)
#    TAP_USE_X           = 722
#    TAP_MAX_X           = 601
#    PRIMA_RIGA_Y        = 140
#    ALTEZZA_RIGA        = 80
#    MAX_RIGHE_VISIBILI  = 5
#
#  CONFIG (ctx.config — chiavi con fallback ai default):
#    ZAINO_ABILITATO          bool   default True
#    ZAINO_USA_POMODORO       bool   default True
#    ZAINO_USA_LEGNO          bool   default True
#    ZAINO_USA_ACCIAIO        bool   default False
#    ZAINO_USA_PETROLIO       bool   default True
#    ZAINO_SOGLIA_POMODORO_M  float  default 10.0
#    ZAINO_SOGLIA_LEGNO_M     float  default 10.0
#    ZAINO_SOGLIA_ACCIAIO_M   float  default  7.0
#    ZAINO_SOGLIA_PETROLIO_M  float  default  5.0
# ==============================================================================

from __future__ import annotations

import time
import numpy as np
from typing import Optional

from core.task import Task, TaskContext, TaskResult

# ------------------------------------------------------------------------------
# Costanti UI (960x540) — sovrascrivibili via ctx.config
# ------------------------------------------------------------------------------

_DEFAULTS: dict = {
    # Apertura / chiusura
    "TAP_ZAINO_APRI":      (430, 18),
    "TAP_ZAINO_CHIUDI":    (783, 68),
    # Sidebar risorse
    "SIDEBAR_POMODORO":    (80, 130),
    "SIDEBAR_LEGNO":       (80, 200),
    "SIDEBAR_ACCIAIO":     (80, 270),
    "SIDEBAR_PETROLIO":    (80, 340),
    # Colonne pulsanti
    "TAP_USE_X":           722,
    "TAP_MAX_X":           601,
    # Layout lista
    "PRIMA_RIGA_Y":        140,
    "ALTEZZA_RIGA":        80,
    "MAX_RIGHE_VISIBILI":  5,
    # Ritardi
    "DELAY_APRI_ZAINO":    2.0,
    "DELAY_TAP_USE":       0.8,
    "DELAY_TAP_MAX":       0.3,
    "DELAY_CONFERMA":      1.5,
    "DELAY_SIDEBAR":       1.0,
    # Abilitazione
    "ZAINO_ABILITATO":     True,
    "ZAINO_USA_POMODORO":  True,
    "ZAINO_USA_LEGNO":     True,
    "ZAINO_USA_ACCIAIO":   False,
    "ZAINO_USA_PETROLIO":  True,
    # Soglie target deposito (milioni)
    "ZAINO_SOGLIA_POMODORO_M": 10.0,
    "ZAINO_SOGLIA_LEGNO_M":    10.0,
    "ZAINO_SOGLIA_ACCIAIO_M":   7.0,
    "ZAINO_SOGLIA_PETROLIO_M":  5.0,
}

# Pezzature per risorsa (crescenti) — unità assolute
PEZZATURE: dict[str, list[int]] = {
    "pomodoro": [1_000, 10_000, 50_000, 150_000, 500_000, 1_500_000],
    "legno":    [1_000, 10_000, 50_000, 150_000, 500_000, 1_500_000],
    "acciaio":  [500,   5_000,  25_000,  75_000, 250_000,   750_000],
    "petrolio": [200,   2_000,  10_000,  30_000, 100_000,   300_000],
}

# Soglie pixel colore arancione "Owned: N"
_OWNED_R_MIN = 200
_OWNED_G_MIN = 100
_OWNED_G_MAX = 180
_OWNED_B_MAX = 80


def _cfg(ctx: TaskContext, key: str):
    """Legge ctx.config con fallback al default di modulo."""
    return ctx.config.get(key, _DEFAULTS[key])


# ------------------------------------------------------------------------------
# Helper: analisi screenshot per rilevare righe con owned > 0
# ------------------------------------------------------------------------------

def _riga_ha_owned(screen_path: str, y_riga: int) -> bool:
    """
    Verifica se la riga a y_riga ha testo arancione "Owned: N" (owned > 0).
    Cerca pixel arancioni nella zona testo owned (x=155..350, y=y_riga+5..y_riga+40).
    Fail-safe: True se non riesce a leggere (meglio tentare che saltare).
    """
    try:
        from PIL import Image
        img = Image.open(screen_path)
        arr = np.array(img)
        y1 = max(0, y_riga + 5)
        y2 = min(arr.shape[0], y_riga + 40)
        roi = arr[y1:y2, 155:350, :3]
        r = roi[:, :, 0].astype(int)
        g = roi[:, :, 1].astype(int)
        b = roi[:, :, 2].astype(int)
        mask = (
            (r > _OWNED_R_MIN) &
            (g > _OWNED_G_MIN) &
            (g < _OWNED_G_MAX) &
            (b < _OWNED_B_MAX)
        )
        return int(mask.sum()) >= 3
    except Exception:
        return True  # fail-safe: meglio tentare che saltare


def _conta_righe_visibili(screen_path: str) -> int:
    """
    Conta le righe visibili nella lista zaino contando i cluster
    di pixel gialli (pulsante USE) nella colonna x=700..780.
    """
    try:
        from PIL import Image
        img = Image.open(screen_path)
        arr = np.array(img)
        col = arr[:, 700:780, :3]
        r = col[:, :, 0].astype(int)
        g = col[:, :, 1].astype(int)
        b = col[:, :, 2].astype(int)
        gialli = (r > 180) & (g > 130) & (b < 80)
        righe_gialle = gialli.any(axis=1)
        count = 0
        in_cluster = False
        for v in righe_gialle:
            if v and not in_cluster:
                count += 1
                in_cluster = True
            elif not v:
                in_cluster = False
        return max(0, count)
    except Exception:
        return 0


# ------------------------------------------------------------------------------
# Operazioni UI — usano ctx.device per ADB-free nei test
# ------------------------------------------------------------------------------

def _usa_riga(ctx: TaskContext, y_riga: int) -> bool:
    """
    Esegue USE → Max → USE su una riga.
    Ritorna True se completato.
    """
    tap_use_x = _cfg(ctx, "TAP_USE_X")
    tap_max_x = _cfg(ctx, "TAP_MAX_X")
    delay_use = _cfg(ctx, "DELAY_TAP_USE")
    delay_max = _cfg(ctx, "DELAY_TAP_MAX")
    delay_conf = _cfg(ctx, "DELAY_CONFERMA")

    ctx.log(f"Zaino: tap USE ({tap_use_x},{y_riga})")
    ctx.device.tap((tap_use_x, y_riga))
    time.sleep(delay_use)

    ctx.log(f"Zaino: tap Max ({tap_max_x},{y_riga})")
    ctx.device.tap((tap_max_x, y_riga))
    time.sleep(delay_max)

    ctx.log(f"Zaino: tap USE conferma ({tap_use_x},{y_riga})")
    ctx.device.tap((tap_use_x, y_riga))
    time.sleep(delay_conf)

    return True


def _scroll_to_top(ctx: TaskContext) -> None:
    """Scroll to top della lista zaino (3× swipe giù)."""
    for _ in range(3):
        ctx.device.scroll(480, 200, 1, durata_ms=300)
        time.sleep(0.3)
    time.sleep(0.5)


def _naviga_sidebar(ctx: TaskContext, risorsa: str) -> bool:
    """Tap sulla tab sidebar per la risorsa. Ritorna False se non configurata."""
    sidebar_key = f"SIDEBAR_{risorsa.upper()}"
    if sidebar_key not in _DEFAULTS:
        ctx.log(f"Zaino [{risorsa}]: sidebar non configurata — skip")
        return False
    coord = _cfg(ctx, sidebar_key)
    ctx.log(f"Zaino [{risorsa}]: tap sidebar {coord}")
    ctx.device.tap(coord)
    time.sleep(_cfg(ctx, "DELAY_SIDEBAR"))
    return True


# ------------------------------------------------------------------------------
# Scarico di una singola risorsa
# ------------------------------------------------------------------------------

def _scarica_risorsa(ctx: TaskContext, risorsa: str, gap: float) -> float:
    """
    Scarica pacchetti dallo zaino per la risorsa fino a colmare gap.

    Parametri:
      risorsa : "pomodoro" | "legno" | "acciaio" | "petrolio"
      gap     : quantità mancante in unità assolute

    Ritorna:
      quantità stimata scaricata (unità assolute)
    """
    pezzature = PEZZATURE.get(risorsa, [])
    gap_residuo = gap
    scaricato = 0.0

    ctx.log(f"Zaino [{risorsa}]: gap da colmare = {gap / 1e6:.3f}M")

    _scroll_to_top(ctx)

    prima_riga_y = _cfg(ctx, "PRIMA_RIGA_Y")

    for pezzatura in pezzature:
        if gap_residuo <= 0:
            ctx.log(f"Zaino [{risorsa}]: gap colmato — stop")
            break

        # Screenshot per verificare presenza owned
        screen = ctx.device.screenshot()
        if not screen:
            ctx.log(f"Zaino [{risorsa}]: screenshot fallito — skip pezzatura {pezzatura:,}")
            continue

        # Conta righe visibili
        n_righe = _conta_righe_visibili(screen)
        if n_righe == 0:
            ctx.log(f"Zaino [{risorsa}]: nessuna riga visibile — fine lista")
            break

        y_riga = prima_riga_y

        # Verifica owned > 0 dalla riga
        if not _riga_ha_owned(screen, y_riga):
            ctx.log(f"Zaino [{risorsa}]: pezzatura {pezzatura:,} owned=0 — skip")
            continue

        # Skip se la singola pezzatura supera già il gap residuo
        if pezzatura > gap_residuo:
            ctx.log(
                f"Zaino [{risorsa}]: pezzatura {pezzatura:,} > gap residuo "
                f"{gap_residuo / 1e6:.3f}M — skip (troppo grande)"
            )
            continue

        ctx.log(
            f"Zaino [{risorsa}]: uso pezzatura {pezzatura:,} "
            f"(gap residuo {gap_residuo / 1e6:.3f}M)"
        )

        if _usa_riga(ctx, y_riga):
            # Stima conservativa: almeno 1 pezzo da questa pezzatura
            scaricato += pezzatura
            gap_residuo -= pezzatura

        time.sleep(0.5)

    ctx.log(f"Zaino [{risorsa}]: scaricato stimato {scaricato / 1e6:.3f}M")
    return scaricato


# ------------------------------------------------------------------------------
# Calcolo gap da deposito OCR simulato
# ------------------------------------------------------------------------------

def _calcola_gap(ctx: TaskContext,
                 deposito: dict[str, float]) -> dict[str, float]:
    """
    Ritorna il gap per ogni risorsa abilitata e sotto soglia.
    deposito: dict risorsa → valore assoluto.
    """
    usa_flags = {
        "pomodoro": _cfg(ctx, "ZAINO_USA_POMODORO"),
        "legno":    _cfg(ctx, "ZAINO_USA_LEGNO"),
        "acciaio":  _cfg(ctx, "ZAINO_USA_ACCIAIO"),
        "petrolio": _cfg(ctx, "ZAINO_USA_PETROLIO"),
    }
    target = {
        "pomodoro": _cfg(ctx, "ZAINO_SOGLIA_POMODORO_M") * 1e6,
        "legno":    _cfg(ctx, "ZAINO_SOGLIA_LEGNO_M")    * 1e6,
        "acciaio":  _cfg(ctx, "ZAINO_SOGLIA_ACCIAIO_M")  * 1e6,
        "petrolio": _cfg(ctx, "ZAINO_SOGLIA_PETROLIO_M") * 1e6,
    }
    gaps: dict[str, float] = {}
    for risorsa, tgt in target.items():
        if not usa_flags.get(risorsa, False):
            ctx.log(f"Zaino [{risorsa}]: disabilitato — skip")
            continue
        valore = deposito.get(risorsa, -1.0)
        if valore < 0:
            ctx.log(f"Zaino [{risorsa}]: OCR non disponibile — skip")
            continue
        if valore < tgt:
            gap = tgt - valore
            ctx.log(
                f"Zaino [{risorsa}]: {valore / 1e6:.2f}M < target {tgt / 1e6:.2f}M "
                f"→ carico (gap={gap / 1e6:.3f}M)"
            )
            gaps[risorsa] = gap
        else:
            ctx.log(
                f"Zaino [{risorsa}]: {valore / 1e6:.2f}M >= target "
                f"{tgt / 1e6:.2f}M — ok"
            )
    return gaps


# ------------------------------------------------------------------------------
# Task V6
# ------------------------------------------------------------------------------

class ZainoTask(Task):
    """
    Task settimanale (168h) che scarica dal backpack virtuale le risorse
    il cui deposito è sotto la soglia configurata.
    """

    @property
    def name(self) -> str:
        return "zaino"

    @property
    def schedule_type(self) -> str:
        return "periodic"

    @property
    def interval_hours(self) -> float:
        return 168.0  # settimanale

    # ------------------------------------------------------------------
    # Interfaccia pubblica per i test — permette di iniettare il deposito
    # ------------------------------------------------------------------

    def run(self, ctx: TaskContext,
            deposito: Optional[dict[str, float]] = None) -> TaskResult:
        """
        Esegue lo scarico zaino.

        Parametri:
          ctx      : TaskContext con device, config, logger
          deposito : dict risorsa→valore_assoluto (iniettato dai test;
                     in produzione viene letto tramite ctx.device.screenshot
                     + OCR esterno prima di chiamare run())

        Ritorna TaskResult con data = {risorsa: scaricato_M, ...}
        """
        # --- Verifica abilitazione ---
        if not _cfg(ctx, "ZAINO_ABILITATO"):
            ctx.log("Zaino: modulo disabilitato (ZAINO_ABILITATO=False) — skip")
            return TaskResult(
                success=True,
                message="disabilitato",
                data={r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]},
            )

        # --- Verifica deposito ---
        if deposito is None:
            # Produzione: screenshot e OCR gestiti dall'orchestrator
            # Qui usiamo un deposito vuoto (nessuna risorsa da caricare)
            ctx.log("Zaino: deposito non fornito — skip (usare orchestrator)")
            return TaskResult(
                success=False,
                message="deposito non disponibile",
                data={r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]},
            )

        # --- Calcola gap ---
        gaps = _calcola_gap(ctx, deposito)

        if not gaps:
            ctx.log("Zaino: tutte le risorse sopra soglia — nessun carico necessario")
            return TaskResult(
                success=True,
                message="nessun carico necessario",
                data={r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]},
            )

        # --- Apri zaino ---
        tap_apri = _cfg(ctx, "TAP_ZAINO_APRI")
        ctx.log(f"Zaino: apertura (tap {tap_apri})")
        ctx.device.tap(tap_apri)
        time.sleep(_cfg(ctx, "DELAY_APRI_ZAINO"))

        esiti: dict[str, float] = {
            r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]
        }

        try:
            for risorsa, gap in gaps.items():
                ctx.log(f"Zaino: === {risorsa.upper()} ===")
                if not _naviga_sidebar(ctx, risorsa):
                    continue
                scaricato = _scarica_risorsa(ctx, risorsa, gap)
                esiti[risorsa] = scaricato / 1e6  # in milioni
        except Exception as e:
            ctx.log(f"Zaino: errore durante scarico: {e}")
            return TaskResult(
                success=False,
                message=f"errore: {e}",
                data=esiti,
            )
        finally:
            # Chiudi zaino sempre
            tap_chiudi = _cfg(ctx, "TAP_ZAINO_CHIUDI")
            ctx.log(f"Zaino: chiusura (tap {tap_chiudi})")
            ctx.device.tap(tap_chiudi)
            time.sleep(1.0)

        totale = sum(esiti.values())
        ctx.log(f"Zaino: completato — totale scaricato: {totale:.3f}M")
        return TaskResult(
            success=True,
            message=f"scaricato {totale:.3f}M totale",
            data=esiti,
        )
