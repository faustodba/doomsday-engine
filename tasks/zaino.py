# ==============================================================================
#  DOOMSDAY ENGINE V6 — tasks/zaino.py                              Step 19
#
#  Scarico risorse dallo zaino virtuale (backpack) al deposito dell'istanza.
#
#  ALGORITMO AVANZATO (v3 — 14/04/2026):
#
#  1. OCR PRE: legge deposito attuale dalla barra superiore
#  2. SCAN INVENTARIO: scorri zaino dall'alto, per ogni riga USE (gialla):
#       - OCR testo pezzatura → valore numerico
#       - OCR numero owned → quantità disponibile
#     Stop quando non ci sono più righe USE (fine lista o solo BUY&USE)
#  3. PIANO GREEDY (dal più grande al più piccolo):
#       - gap = target - deposito_pre
#       - Per ogni pezzatura decrescente:
#           n = min(owned, floor(gap_residuo / pezzatura))
#           gap_residuo -= n * pezzatura
#       - Stop quando gap_residuo <= 0
#  4. ESECUZIONE PIANO:
#       - Per ogni pezzatura nel piano:
#           - Trova la riga tramite OCR (scroll se necessario)
#           - Tap USE × n volte (1 tap = 1 pezzo)
#           - Tra un tap e l'altro: owned scende di 1, riga sparisce a 0
#  5. OCR POST: misura reale scaricato = post - pre
#
#  COORDINATE CALIBRATE (960x540 — da screenshot reali 14/04/2026):
#    PRIMA_RIGA_Y_OWNED = 154   — Y centro testo "Owned: N" prima riga
#    ALTEZZA_RIGA       = 79    — distanza tra righe
#    MAX_RIGHE          = 5     — righe visibili per schermata
#    TITOLO_X           = (240, 580)   — zona OCR testo pezzatura
#    TITOLO_Y_OFFSET    = (-38, -10)   — offset Y da y_owned
#    OWNED_X            = (253, 350)   — zona OCR numero owned
#    OWNED_Y_OFFSET     = (-12, +12)   — offset Y da y_owned
#    USE_X              = 724          — X pulsante USE
#    USE_Y_OFFSET       = -3           — offset Y da y_owned
#    GIALLO_X           = (650, 810)   — zona check pixel gialli USE
#
#  DISTINZIONE USE vs BUY&USE:
#    Pixel gialli (R>180, G>130, B<80) in zona GIALLO_X → USE disponibile
#    Nessun pixel giallo → BUY&USE (viola) → riga ignorata
# ==============================================================================

from __future__ import annotations

import re
import time
import numpy as np
from typing import Optional

from core.task import Task, TaskContext, TaskResult

# ------------------------------------------------------------------------------
# Costanti UI calibrate (960x540)
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
    # Layout lista — calibrato da screenshot reali
    "PRIMA_RIGA_Y_OWNED":  154,    # Y centro "Owned: N" prima riga
    "ALTEZZA_RIGA":        79,     # distanza tra righe
    "MAX_RIGHE":           5,      # righe visibili per schermata
    # Zone OCR (offset da y_owned)
    "TITOLO_X1":           240,    # zona testo pezzatura
    "TITOLO_X2":           580,
    "TITOLO_Y_OFF1":       -38,
    "TITOLO_Y_OFF2":       -10,
    "OWNED_X1":            253,    # zona numero owned
    "OWNED_X2":            350,
    "OWNED_Y_OFF1":        -12,
    "OWNED_Y_OFF2":        12,
    # Pulsante USE
    "USE_X":               724,
    "USE_Y_OFFSET":        -3,
    # Check USE (giallo) vs BUY&USE (viola)
    "GIALLO_X1":           650,
    "GIALLO_X2":           810,
    # Ritardi
    "DELAY_APRI_ZAINO":    2.0,
    "DELAY_SIDEBAR":       1.0,
    "DELAY_TAP_USE":       0.6,    # attesa dopo ogni tap USE
    "DELAY_SCROLL":        0.8,    # attesa dopo swipe scroll
    "DELAY_POST_SCARICO":  1.5,    # attesa prima OCR post
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


def _cfg(ctx: TaskContext, key: str):
    return ctx.config.get(key, _DEFAULTS[key])


# ------------------------------------------------------------------------------
# Helpers frame / OCR
# ------------------------------------------------------------------------------

def _get_frame(screen) -> Optional[np.ndarray]:
    frame = getattr(screen, "frame", None)
    if frame is None and isinstance(screen, np.ndarray):
        frame = screen
    return frame


def _ocr_deposito(ctx: TaskContext) -> dict[str, float]:
    """Legge risorse dalla barra superiore (funziona con zaino aperto o chiuso)."""
    try:
        from shared.ocr_helpers import ocr_risorse
    except ImportError as exc:
        ctx.log_msg(f"[ZAINO] import ocr_helpers fallito: {exc}")
        return {}
    screen = ctx.device.screenshot()
    if screen is None:
        return {}
    try:
        risorse = ocr_risorse(screen)
        return {
            "pomodoro": risorse.pomodoro,
            "legno":    risorse.legno,
            "acciaio":  risorse.acciaio,
            "petrolio": risorse.petrolio,
        }
    except Exception as exc:
        ctx.log_msg(f"[ZAINO] OCR deposito errore: {exc}")
        return {}


def _parse_numero(testo: str) -> int:
    """Estrae primo numero intero da stringa (es. '694' da 'Owned: 694')."""
    testo = testo.strip().replace(",", "").replace(".", "")
    m = re.search(r"\d+", testo)
    return int(m.group()) if m else -1


def _parse_pezzatura(testo: str) -> int:
    """
    Estrae valore pezzatura dal testo riga (es. '500 Steel' → 500,
    '1,500,000 Wood' → 1500000, '25,000 Steel' → 25000).
    """
    testo = testo.strip()
    # Rimuovi nome risorsa e caratteri non numerici eccetto virgola/punto
    m = re.search(r"([\d,\.]+)", testo)
    if not m:
        return -1
    num_str = m.group(1).replace(",", "").replace(".", "")
    try:
        return int(num_str)
    except ValueError:
        return -1


def _ocr_testo_zona(ctx: TaskContext,
                    frame: np.ndarray,
                    x1: int, y1: int, x2: int, y2: int) -> str:
    """OCR su zona rettangolare del frame BGR."""
    try:
        import pytesseract
        from PIL import Image
        roi = frame[y1:y2, x1:x2]
        # Converti BGR→RGB→PIL
        pil = Image.fromarray(roi[:, :, ::-1])
        w, h = pil.size
        pil4x = pil.resize((w * 4, h * 4), Image.LANCZOS)
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789,. "
        testo = pytesseract.image_to_string(pil4x, config=cfg).strip()
        return testo
    except Exception:
        return ""


def _riga_ha_use_giallo(frame: np.ndarray,
                        y_owned: int,
                        x1: int, x2: int) -> bool:
    """
    Verifica se la riga ha pulsante USE giallo (non BUY&USE viola).
    Cerca pixel gialli (R>180, G>130, B<80) nella zona pulsante.
    """
    try:
        y1 = max(0, y_owned - 30)
        y2 = min(frame.shape[0], y_owned + 20)
        roi = frame[y1:y2, x1:x2]
        b = roi[:, :, 0].astype(int)
        g = roi[:, :, 1].astype(int)
        r = roi[:, :, 2].astype(int)
        gialli = (r > 180) & (g > 130) & (b < 80)
        return int(gialli.sum()) >= 20
    except Exception:
        return False


# ------------------------------------------------------------------------------
# SCAN INVENTARIO
# ------------------------------------------------------------------------------

def _scan_inventario(ctx: TaskContext) -> dict[int, int]:
    """
    Scorre lo zaino dall'alto verso il basso e legge tutte le pezzature
    con owned > 0 e pulsante USE giallo (non BUY&USE).

    Ritorna dict {pezzatura: owned} per le righe USE disponibili.
    """
    inventario: dict[int, int] = {}

    prima_y    = _cfg(ctx, "PRIMA_RIGA_Y_OWNED")
    alt_riga   = _cfg(ctx, "ALTEZZA_RIGA")
    max_righe  = _cfg(ctx, "MAX_RIGHE")
    tx1        = _cfg(ctx, "TITOLO_X1")
    tx2        = _cfg(ctx, "TITOLO_X2")
    ty_off1    = _cfg(ctx, "TITOLO_Y_OFF1")
    ty_off2    = _cfg(ctx, "TITOLO_Y_OFF2")
    ox1        = _cfg(ctx, "OWNED_X1")
    ox2        = _cfg(ctx, "OWNED_X2")
    oy_off1    = _cfg(ctx, "OWNED_Y_OFF1")
    oy_off2    = _cfg(ctx, "OWNED_Y_OFF2")
    gx1        = _cfg(ctx, "GIALLO_X1")
    gx2        = _cfg(ctx, "GIALLO_X2")

    scroll_eseguiti = 0
    max_scroll      = 10
    pezzature_viste: set[int] = set()
    righe_vuote_consecutive = 0

    ctx.log_msg("[ZAINO] Scan inventario — scorrimento zaino...")

    # Porta sempre in cima prima di scansionare
    _scroll_to_top(ctx)

    while scroll_eseguiti <= max_scroll:
        screen = ctx.device.screenshot()
        if screen is None:
            break
        frame = _get_frame(screen)
        if frame is None:
            break

        nuove_trovate = 0

        for i in range(max_righe):
            y_owned = prima_y + i * alt_riga
            if y_owned + 20 > frame.shape[0]:
                break

            # Verifica USE giallo
            if not _riga_ha_use_giallo(frame, y_owned, gx1, gx2):
                continue

            # OCR pezzatura
            ty1 = max(0, y_owned + ty_off1)
            ty2 = max(0, y_owned + ty_off2)
            testo_pez = _ocr_testo_zona(ctx, frame, tx1, ty1, tx2, ty2)
            pezzatura = _parse_pezzatura(testo_pez)
            if pezzatura <= 0:
                continue

            # Già vista in scroll precedente → stiamo ciclando → stop
            if pezzatura in pezzature_viste:
                continue

            # OCR owned
            oy1 = max(0, y_owned + oy_off1)
            oy2 = min(frame.shape[0], y_owned + oy_off2)
            testo_own = _ocr_testo_zona(ctx, frame, ox1, oy1, ox2, oy2)
            owned = _parse_numero(testo_own)
            if owned <= 0:
                continue

            inventario[pezzatura] = owned
            pezzature_viste.add(pezzatura)
            nuove_trovate += 1
            ctx.log_msg(
                f"[ZAINO] scan: pezzatura={pezzatura:,} owned={owned}"
            )

        if nuove_trovate == 0:
            righe_vuote_consecutive += 1
            if righe_vuote_consecutive >= 2:
                ctx.log_msg("[ZAINO] Scan completato — nessuna nuova riga")
                break
        else:
            righe_vuote_consecutive = 0

        # Scroll giù per vedere righe successive
        ctx.device.swipe(480, 350, 480, 150, duration_ms=400)
        time.sleep(_cfg(ctx, "DELAY_SCROLL"))
        scroll_eseguiti += 1

    ctx.log_msg(f"[ZAINO] Inventario trovato: {len(inventario)} pezzature")
    return inventario


# ------------------------------------------------------------------------------
# CALCOLO PIANO GREEDY
# ------------------------------------------------------------------------------

def _calcola_piano(gap: float,
                   inventario: dict[int, int]) -> dict[int, int]:
    """
    Calcola quanti pezzi usare per ogni pezzatura per colmare il gap.
    Greedy dal più grande al più piccolo.

    Ritorna dict {pezzatura: n_tap} solo per pezzature con n_tap > 0.
    """
    piano: dict[int, int] = {}
    gap_residuo = gap

    # Ordine decrescente
    for pezzatura in sorted(inventario.keys(), reverse=True):
        if gap_residuo <= 0:
            break
        owned = inventario[pezzatura]
        n = min(owned, int(gap_residuo // pezzatura))
        if n > 0:
            piano[pezzatura] = n
            gap_residuo -= n * pezzatura

    return piano


# ------------------------------------------------------------------------------
# ESECUZIONE PIANO
# ------------------------------------------------------------------------------

def _trova_riga_y(ctx: TaskContext,
                  frame: np.ndarray,
                  pezzatura: int) -> Optional[int]:
    """
    Trova la Y_owned della riga corrispondente alla pezzatura cercata.
    Scansiona le righe visibili e fa OCR del titolo per matchare.
    Ritorna Y_owned se trovata, None altrimenti.
    """
    prima_y   = _cfg(ctx, "PRIMA_RIGA_Y_OWNED")
    alt_riga  = _cfg(ctx, "ALTEZZA_RIGA")
    max_righe = _cfg(ctx, "MAX_RIGHE")
    tx1       = _cfg(ctx, "TITOLO_X1")
    tx2       = _cfg(ctx, "TITOLO_X2")
    ty_off1   = _cfg(ctx, "TITOLO_Y_OFF1")
    ty_off2   = _cfg(ctx, "TITOLO_Y_OFF2")
    gx1       = _cfg(ctx, "GIALLO_X1")
    gx2       = _cfg(ctx, "GIALLO_X2")

    for i in range(max_righe):
        y_owned = prima_y + i * alt_riga
        if y_owned + 20 > frame.shape[0]:
            break
        if not _riga_ha_use_giallo(frame, y_owned, gx1, gx2):
            continue
        ty1 = max(0, y_owned + ty_off1)
        ty2 = max(0, y_owned + ty_off2)
        testo = _ocr_testo_zona(ctx, frame, tx1, ty1, tx2, ty2)
        pez_letta = _parse_pezzatura(testo)
        if pez_letta == pezzatura:
            return y_owned

    return None


def _scorri_a_pezzatura(ctx: TaskContext, pezzatura: int) -> Optional[int]:
    """
    Torna in cima e cerca la riga della pezzatura con scroll progressivo.
    Ritorna Y_owned se trovata, None dopo max_scroll tentativi.
    """
    _scroll_to_top(ctx)
    max_scroll = 8

    for _ in range(max_scroll):
        screen = ctx.device.screenshot()
        if screen is None:
            break
        frame = _get_frame(screen)
        if frame is None:
            break
        y = _trova_riga_y(ctx, frame, pezzatura)
        if y is not None:
            return y
        # Scroll giù
        ctx.device.swipe(480, 350, 480, 150, duration_ms=400)
        time.sleep(_cfg(ctx, "DELAY_SCROLL"))

    return None


def _esegui_piano(ctx: TaskContext, piano: dict[int, int]) -> None:
    """
    Esegue il piano: per ogni pezzatura (dal più grande al più piccolo)
    fa N tap USE sulla riga corrispondente.
    Gestisce la scomparsa della riga quando owned → 0.
    """
    use_x      = _cfg(ctx, "USE_X")
    use_y_off  = _cfg(ctx, "USE_Y_OFFSET")
    delay_use  = _cfg(ctx, "DELAY_TAP_USE")

    for pezzatura in sorted(piano.keys(), reverse=True):
        n_tap = piano[pezzatura]
        ctx.log_msg(
            f"[ZAINO] Eseguo: pezzatura={pezzatura:,} × {n_tap} tap"
        )

        for tap_i in range(n_tap):
            # Trova riga (potrebbe essersi spostata dopo tap precedenti)
            y_owned = _scorri_a_pezzatura(ctx, pezzatura)
            if y_owned is None:
                ctx.log_msg(
                    f"[ZAINO] pezzatura {pezzatura:,} non trovata "
                    f"(tap {tap_i+1}/{n_tap}) — riga esaurita"
                )
                break

            y_use = y_owned + use_y_off
            ctx.log_msg(
                f"[ZAINO] tap USE ({use_x},{y_use}) "
                f"[{tap_i+1}/{n_tap}]"
            )
            ctx.device.tap(use_x, y_use)
            time.sleep(delay_use)


# ------------------------------------------------------------------------------
# Helpers scroll / sidebar
# ------------------------------------------------------------------------------

def _scroll_to_top(ctx: TaskContext) -> None:
    """Porta la lista in cima (3× swipe giù)."""
    for _ in range(3):
        ctx.device.swipe(480, 180, 480, 420, duration_ms=300)
        time.sleep(0.3)
    time.sleep(0.5)


def _naviga_sidebar(ctx: TaskContext, risorsa: str) -> bool:
    sidebar_key = f"SIDEBAR_{risorsa.upper()}"
    if sidebar_key not in _DEFAULTS:
        ctx.log_msg(f"[ZAINO] [{risorsa}]: sidebar non configurata — skip")
        return False
    coord = _cfg(ctx, sidebar_key)
    ctx.log_msg(f"[ZAINO] [{risorsa}]: tap sidebar {coord}")
    ctx.device.tap(*coord)
    time.sleep(_cfg(ctx, "DELAY_SIDEBAR"))
    return True


# ------------------------------------------------------------------------------
# Calcolo gap / target
# ------------------------------------------------------------------------------

def _calcola_gap(ctx: TaskContext,
                 deposito: dict[str, float]) -> dict[str, tuple[float, float]]:
    """
    Ritorna {risorsa: (valore_attuale, target)} per risorse sotto soglia.
    """
    usa_flags = {
        "pomodoro": _cfg(ctx, "ZAINO_USA_POMODORO"),
        "legno":    _cfg(ctx, "ZAINO_USA_LEGNO"),
        "acciaio":  _cfg(ctx, "ZAINO_USA_ACCIAIO"),
        "petrolio": _cfg(ctx, "ZAINO_USA_PETROLIO"),
    }
    targets = {
        "pomodoro": _cfg(ctx, "ZAINO_SOGLIA_POMODORO_M") * 1e6,
        "legno":    _cfg(ctx, "ZAINO_SOGLIA_LEGNO_M")    * 1e6,
        "acciaio":  _cfg(ctx, "ZAINO_SOGLIA_ACCIAIO_M")  * 1e6,
        "petrolio": _cfg(ctx, "ZAINO_SOGLIA_PETROLIO_M") * 1e6,
    }
    da_caricare: dict[str, tuple[float, float]] = {}
    for risorsa, tgt in targets.items():
        if not usa_flags.get(risorsa, False):
            ctx.log_msg(f"[ZAINO] [{risorsa}]: disabilitato — skip")
            continue
        valore = deposito.get(risorsa, -1.0)
        if valore < 0:
            ctx.log_msg(f"[ZAINO] [{risorsa}]: OCR non disponibile — skip")
            continue
        if valore < tgt:
            gap = tgt - valore
            ctx.log_msg(
                f"[ZAINO] [{risorsa}]: {valore/1e6:.2f}M < target "
                f"{tgt/1e6:.2f}M → carico (gap={gap/1e6:.3f}M)"
            )
            da_caricare[risorsa] = (valore, tgt)
        else:
            ctx.log_msg(
                f"[ZAINO] [{risorsa}]: {valore/1e6:.2f}M >= target "
                f"{tgt/1e6:.2f}M — ok"
            )
    return da_caricare


# ------------------------------------------------------------------------------
# Task V6
# ------------------------------------------------------------------------------

class ZainoTask(Task):
    """
    Task settimanale (168h) che scarica dal backpack virtuale le risorse
    il cui deposito è sotto la soglia configurata.

    Algoritmo avanzato v3:
      scan inventario → piano greedy → N tap precisi → OCR pre/post reale
    """

    def name(self) -> str:
        return "zaino"

    def schedule_type(self) -> str:
        return "periodic"

    def interval_hours(self) -> float:
        return 168.0

    def should_run(self, ctx) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("zaino")
        return True

    def run_dry(self, ctx: TaskContext) -> TaskResult:
        """
        Modalità simulazione: OCR deposito + scan inventario + calcolo piano.
        Nessun tap viene eseguito. Utile per verificare letture e piano prima
        di eseguire lo scarico reale.
        """
        ctx.log_msg("[ZAINO][DRY] Modalità simulazione — nessun tap verrà eseguito")

        if not _cfg(ctx, "ZAINO_ABILITATO"):
            ctx.log_msg("[ZAINO][DRY] modulo disabilitato — skip")
            return TaskResult(success=True, message="disabilitato", data={})

        # OCR PRE
        ctx.log_msg("[ZAINO][DRY] OCR deposito...")
        snapshot_pre = _ocr_deposito(ctx)
        if not snapshot_pre:
            ctx.log_msg("[ZAINO][DRY] Deposito non disponibile — skip")
            return TaskResult(success=False, message="deposito non disponibile", data={})

        ctx.log_msg(
            f"[ZAINO][DRY] Deposito: "
            f"pomodoro={snapshot_pre.get('pomodoro',-1)/1e6:.2f}M "
            f"legno={snapshot_pre.get('legno',-1)/1e6:.2f}M "
            f"acciaio={snapshot_pre.get('acciaio',-1)/1e6:.2f}M "
            f"petrolio={snapshot_pre.get('petrolio',-1)/1e6:.2f}M"
        )

        da_caricare = _calcola_gap(ctx, snapshot_pre)
        if not da_caricare:
            ctx.log_msg("[ZAINO][DRY] Tutte le risorse sopra soglia — nessun carico")
            return TaskResult(success=True, message="nessun carico necessario", data={})

        # Apri zaino
        tap_apri = _cfg(ctx, "TAP_ZAINO_APRI")
        ctx.log_msg(f"[ZAINO][DRY] Apertura zaino (tap {tap_apri})")
        ctx.device.tap(*tap_apri)
        time.sleep(_cfg(ctx, "DELAY_APRI_ZAINO"))

        piani: dict[str, dict] = {}

        try:
            for risorsa, (val_pre, target) in da_caricare.items():
                gap = target - val_pre
                ctx.log_msg(f"[ZAINO][DRY] === {risorsa.upper()} (gap={gap/1e6:.3f}M) ===")

                if not _naviga_sidebar(ctx, risorsa):
                    continue

                # Scan inventario
                inventario = _scan_inventario(ctx)
                if not inventario:
                    ctx.log_msg(f"[ZAINO][DRY] [{risorsa}]: inventario vuoto")
                    continue

                ctx.log_msg(f"[ZAINO][DRY] [{risorsa}] Inventario:")
                totale_disponibile = 0
                for pez, owned in sorted(inventario.items()):
                    contributo = pez * owned
                    totale_disponibile += contributo
                    ctx.log_msg(
                        f"[ZAINO][DRY]   pezzatura={pez:>12,} "
                        f"owned={owned:>4} "
                        f"contributo={contributo/1e6:.3f}M"
                    )
                ctx.log_msg(
                    f"[ZAINO][DRY] [{risorsa}] Totale disponibile: "
                    f"{totale_disponibile/1e6:.3f}M"
                )

                # Piano greedy
                piano = _calcola_piano(gap, inventario)
                if not piano:
                    ctx.log_msg(f"[ZAINO][DRY] [{risorsa}]: piano vuoto — scorte insufficienti")
                    continue

                ctx.log_msg(f"[ZAINO][DRY] [{risorsa}] Piano di scarico:")
                totale_piano = 0
                n_tap_totali = 0
                for pez, n in sorted(piano.items(), reverse=True):
                    contributo = pez * n
                    totale_piano += contributo
                    n_tap_totali += n
                    ctx.log_msg(
                        f"[ZAINO][DRY]   pezzatura={pez:>12,} "
                        f"× {n:>3} tap "
                        f"= {contributo/1e6:.3f}M"
                    )
                ctx.log_msg(
                    f"[ZAINO][DRY] [{risorsa}] Totale piano: "
                    f"{totale_piano/1e6:.3f}M in {n_tap_totali} tap"
                )
                ctx.log_msg(
                    f"[ZAINO][DRY] [{risorsa}] Deposito stimato post: "
                    f"{(val_pre + totale_piano)/1e6:.2f}M "
                    f"(target={target/1e6:.2f}M)"
                )

                piani[risorsa] = {
                    "gap_m":           round(gap / 1e6, 3),
                    "disponibile_m":   round(totale_disponibile / 1e6, 3),
                    "piano_m":         round(totale_piano / 1e6, 3),
                    "n_tap":           n_tap_totali,
                    "deposito_post_m": round((val_pre + totale_piano) / 1e6, 2),
                }

        finally:
            tap_chiudi = _cfg(ctx, "TAP_ZAINO_CHIUDI")
            ctx.log_msg(f"[ZAINO][DRY] Chiusura zaino (tap {tap_chiudi})")
            ctx.device.tap(*tap_chiudi)
            time.sleep(1.0)

        ctx.log_msg("[ZAINO][DRY] Simulazione completata — nessun tap eseguito")
        return TaskResult(
            success=True,
            message="dry-run completato",
            data=piani,
        )

    def run(self, ctx: TaskContext,
            deposito: Optional[dict[str, float]] = None) -> TaskResult:
        """
        Esegue lo scarico zaino con algoritmo avanzato.

        Parametri:
          ctx      : TaskContext
          deposito : dict risorsa→valore (iniettato dai test; None = OCR auto)
        """
        if not _cfg(ctx, "ZAINO_ABILITATO"):
            ctx.log_msg("[ZAINO] modulo disabilitato — skip")
            return TaskResult(
                success=True,
                message="disabilitato",
                data={r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]},
            )

        # --- OCR PRE ---
        ctx.log_msg("[ZAINO] OCR deposito PRE-scarico...")
        if deposito is None:
            snapshot_pre = _ocr_deposito(ctx)
            if not snapshot_pre:
                ctx.log_msg("[ZAINO] Deposito non disponibile — skip")
                return TaskResult(
                    success=False,
                    message="deposito non disponibile",
                    data={r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]},
                )
        else:
            snapshot_pre = deposito

        ctx.log_msg(
            f"[ZAINO] PRE: "
            f"pomodoro={snapshot_pre.get('pomodoro',-1)/1e6:.2f}M "
            f"legno={snapshot_pre.get('legno',-1)/1e6:.2f}M "
            f"acciaio={snapshot_pre.get('acciaio',-1)/1e6:.2f}M "
            f"petrolio={snapshot_pre.get('petrolio',-1)/1e6:.2f}M"
        )

        # --- Calcola cosa caricare ---
        da_caricare = _calcola_gap(ctx, snapshot_pre)
        if not da_caricare:
            ctx.log_msg("[ZAINO] Tutte le risorse sopra soglia — nessun carico")
            return TaskResult(
                success=True,
                message="nessun carico necessario",
                data={r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]},
            )

        # --- Apri zaino ---
        tap_apri = _cfg(ctx, "TAP_ZAINO_APRI")
        ctx.log_msg(f"[ZAINO] Apertura zaino (tap {tap_apri})")
        ctx.device.tap(*tap_apri)
        time.sleep(_cfg(ctx, "DELAY_APRI_ZAINO"))

        esiti: dict[str, float] = {
            r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]
        }

        try:
            for risorsa, (val_pre, target) in da_caricare.items():
                gap = target - val_pre
                ctx.log_msg(f"[ZAINO] === {risorsa.upper()} (gap={gap/1e6:.3f}M) ===")

                # Naviga sidebar
                if not _naviga_sidebar(ctx, risorsa):
                    continue

                # Scan inventario
                inventario = _scan_inventario(ctx)
                if not inventario:
                    ctx.log_msg(f"[ZAINO] [{risorsa}]: inventario vuoto — skip")
                    continue

                # Totale disponibile
                totale_disponibile = sum(
                    p * q for p, q in inventario.items()
                )
                ctx.log_msg(
                    f"[ZAINO] [{risorsa}]: disponibile={totale_disponibile/1e6:.3f}M "
                    f"gap={gap/1e6:.3f}M"
                )

                # Piano greedy
                piano = _calcola_piano(gap, inventario)
                if not piano:
                    ctx.log_msg(
                        f"[ZAINO] [{risorsa}]: piano vuoto "
                        f"(scorte insufficienti o già sopra target)"
                    )
                    continue

                piano_str = ", ".join(
                    f"{p:,}×{n}" for p, n in sorted(piano.items(), reverse=True)
                )
                ctx.log_msg(f"[ZAINO] [{risorsa}]: piano = {piano_str}")

                # Esegui piano
                _esegui_piano(ctx, piano)

                # OCR POST per questa risorsa
                time.sleep(_cfg(ctx, "DELAY_POST_SCARICO"))
                snapshot_post = _ocr_deposito(ctx)
                val_post = snapshot_post.get(risorsa, -1.0)

                if val_post >= 0 and val_pre >= 0:
                    scaricato_reale = max(0.0, val_post - val_pre)
                    esiti[risorsa]  = scaricato_reale / 1e6
                    ctx.log_msg(
                        f"[ZAINO] [{risorsa}]: PRE={val_pre/1e6:.2f}M "
                        f"POST={val_post/1e6:.2f}M "
                        f"→ scaricato reale={scaricato_reale/1e6:.3f}M"
                    )
                else:
                    ctx.log_msg(
                        f"[ZAINO] [{risorsa}]: OCR post non disponibile"
                    )

        except Exception as exc:
            ctx.log_msg(f"[ZAINO] Errore: {exc}")
            return TaskResult(
                success=False,
                message=f"errore: {exc}",
                data=esiti,
            )
        finally:
            tap_chiudi = _cfg(ctx, "TAP_ZAINO_CHIUDI")
            ctx.log_msg(f"[ZAINO] Chiusura zaino (tap {tap_chiudi})")
            ctx.device.tap(*tap_chiudi)
            time.sleep(1.0)

        totale = sum(esiti.values())
        ctx.log_msg(f"[ZAINO] Completato — totale scaricato reale: {totale:.3f}M")
        return TaskResult(
            success=True,
            message=f"scaricato {totale:.3f}M totale",
            data=esiti,
        )
