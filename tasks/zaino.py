# ==============================================================================
#  DOOMSDAY ENGINE V6 — tasks/zaino.py                              Step 19
#
#  Due modalità selezionabili da global_config.json → zaino.modalita:
#
#  MODALITÀ "bag" (default):
#    Usa interfaccia BAG (tap_barra "bag" → RESOURCE).
#    FASE 1: scan griglia via TM (find_one per ogni pin catalogo) + tap + OCR
#            pannello destra → inventario completo {(risorsa, pezzatura): owned}
#    FASE 2: calcolo greedy ottimale sul inventario completo
#    FASE 3: scroll to top + ricerca TM pin del piano + tap + input n + USE
#    Rispetta soglie: carica solo quello che serve per raggiungere il target.
#
#  MODALITÀ "svuota":
#    Apre zaino dalla HOME (icona barra alta).
#    Per ogni risorsa abilitata: naviga sidebar → USE MAX su ogni pezzatura.
#    NON controlla soglie — svuota completamente lo zaino.
#    Utile per reset manuale o test.
#
#  CONFIG (global_config.json → sezione "zaino"):
#    modalita:          "bag" | "svuota"   default "bag"
#    usa_pomodoro:      bool
#    usa_legno:         bool
#    usa_acciaio:       bool
#    usa_petrolio:      bool
#    soglia_*_m:        float (solo modalità bag)
#
#  COORDINATE CALIBRATE (960x540 — misurazioni reali 14/04/2026):
#
#  GRIGLIA BAG:
#    Spigolo (150,135), box 82×82, gap 22px
#    Col X centri: [191, 295, 399, 503, 607]
#    Riga Y centri: [176, 280, 384, 488]
#
#  PANNELLO DESTRA BAG:
#    TITOLO  : (665,  80, 824, 124)
#    OWNED   : (664, 175, 796, 206)
#    GRANTS  : (663, 206, 839, 246)
#    CAMPO   : centro (738, 445)
#    OK      : (879, 509)
#    USE     : centro (806, 492)
#
#  ZAINO HOME (modalità svuota):
#    TAP_APRI     : (430, 18)
#    TAP_CHIUDI   : (783, 68)
#    SIDEBAR_*    : vedi _DEFAULTS
#    TAP_USE_X    : 722
#    TAP_MAX_X    : 601
#    PRIMA_RIGA_Y : 140
#
#  PIN CATALOGO (templates/pin/):
#    Naming: pin_{risorsa}_{pezzatura}.png
#    Risorse: pom, leg, acc, pet
#    Pezzature per risorsa: vedi _PIN_CATALOGO
#
#  FIX/REFACTOR 15/04/2026 — architettura TM-based:
#    Sostituisce scan per coordinate fisse con find_one() su pin catalogo.
#    FASE 1: identifica icone via TM → tap → OCR pannello destra (100%)
#    FASE 2: greedy su inventario completo
#    FASE 3: rescansione TM per esecuzione
#    Eliminato bug icone_viste. _wait_ui_stabile() post-swipe.
# ==============================================================================

from __future__ import annotations

import re
import time
import numpy as np
from typing import Optional

from core.task import Task, TaskContext, TaskResult

# ------------------------------------------------------------------------------
# Costanti
# ------------------------------------------------------------------------------

_DEFAULTS: dict = {
    # Modalità
    "ZAINO_MODALITA":          "bag",

    # Abilitazione risorse
    "ZAINO_ABILITATO":         True,
    "ZAINO_USA_POMODORO":      True,
    "ZAINO_USA_LEGNO":         True,
    "ZAINO_USA_ACCIAIO":       False,
    "ZAINO_USA_PETROLIO":      True,

    # Soglie target (milioni) — solo modalità bag
    "ZAINO_SOGLIA_POMODORO_M": 10.0,
    "ZAINO_SOGLIA_LEGNO_M":    10.0,
    "ZAINO_SOGLIA_ACCIAIO_M":   7.0,
    "ZAINO_SOGLIA_PETROLIO_M":  5.0,

    # ── MODALITÀ BAG ─────────────────────────────────────────────────────────
    "BAG_RESOURCE_TAP":        (65, 110),
    # Pannello destra
    "BAG_TITOLO_ZONA":         (665,  80, 824, 124),
    "BAG_OWNED_ZONA":          (664, 175, 796, 206),
    "BAG_GRANTS_ZONA":         (663, 206, 839, 246),
    "BAG_CAMPO_QTY":           (738, 445),
    "BAG_MAX":                 (883, 444),
    "BAG_OK":                  (879, 509),
    "BAG_USE":                 (806, 492),
    # ROI griglia TM
    "BAG_GRIGLIA_ROI":         (150, 100, 660, 530),
    # Scroll
    "BAG_SCROLL_X":            480,
    "BAG_SCROLL_Y_START":      488,
    "BAG_SCROLL_Y_END":        176,
    "BAG_SCROLL_MS":           400,
    # Ritardi
    "BAG_DELAY_APRI":          2.0,
    "BAG_DELAY_ICONA":         0.8,
    "BAG_DELAY_INPUT":         0.5,
    "BAG_DELAY_USE":           1.0,
    "BAG_DELAY_POST":          1.5,
    # Wait UI stabile post-swipe
    "BAG_SCROLL_POLL_S":       0.3,
    "BAG_SCROLL_SOGLIA":       50,
    "BAG_SCROLL_TIMEOUT":      3.0,
    "BAG_SCROLL_MIN_S":        0.3,
    # TM
    "BAG_PIN_THRESHOLD":       0.80,
    # Stop scan/esecuzione
    "BAG_MAX_VUOTE":           3,
    "BAG_MAX_SCROLL":          12,

    # ── MODALITÀ SVUOTA ───────────────────────────────────────────────────────
    "SV_TAP_APRI":             (430, 18),
    "SV_TAP_CHIUDI":           (783, 68),
    "SV_SIDEBAR_POMODORO":     (80, 130),
    "SV_SIDEBAR_LEGNO":        (80, 200),
    "SV_SIDEBAR_ACCIAIO":      (80, 270),
    "SV_SIDEBAR_PETROLIO":     (80, 340),
    "SV_TAP_USE_X":            722,
    "SV_TAP_MAX_X":            601,
    "SV_PRIMA_RIGA_Y":         140,
    "SV_ALTEZZA_RIGA":         79,
    "SV_MAX_RIGHE":            5,
    "SV_DELAY_APRI":           2.0,
    "SV_DELAY_SIDEBAR":        1.0,
    "SV_DELAY_USE":            0.8,
    "SV_DELAY_MAX":            0.3,
    "SV_DELAY_CONF":           1.5,
}

# ------------------------------------------------------------------------------
# Catalogo pin: {short: (risorsa_interna, [pezzature DESC])}
# File: templates/pin/pin_{short}_{pezzatura}.png
# Aggiungere nuove pezzature qui quando i pin diventano disponibili.
# ------------------------------------------------------------------------------
_PIN_CATALOGO: dict[str, tuple[str, list[int]]] = {
    "pom": ("pomodoro", [5000000, 1500000, 500000, 150000, 50000, 10000, 1000]),
    "leg": ("legno",    [1500000, 500000, 150000, 50000, 10000, 1000]),
    "acc": ("acciaio",  [2500000, 750000, 250000, 75000, 25000, 5000, 500]),
    "pet": ("petrolio", [300000, 100000, 30000, 10000, 2000, 200]),
}

# Mapping grants/titolo → risorsa interna (OCR pannello destra)
_GRANTS_MAP = [
    ("food",  "pomodoro"),
    ("wood",  "legno"),
    ("steel", "acciaio"),
    ("oil",   "petrolio"),
]


def _cfg(ctx: TaskContext, key: str):
    return ctx.config.get(key, _DEFAULTS[key])


# ==============================================================================
# HELPERS COMUNI
# ==============================================================================

def _ocr_deposito(ctx: TaskContext) -> dict[str, float]:
    """Legge risorse dalla barra superiore."""
    try:
        from shared.ocr_helpers import ocr_risorse
    except ImportError as exc:
        ctx.log_msg(f"[ZAINO] import ocr_helpers: {exc}")
        return {}
    screen = ctx.device.screenshot()
    if screen is None:
        return {}
    try:
        r = ocr_risorse(screen)
        return {"pomodoro": r.pomodoro, "legno": r.legno,
                "acciaio": r.acciaio, "petrolio": r.petrolio}
    except Exception as exc:
        ctx.log_msg(f"[ZAINO] OCR deposito: {exc}")
        return {}


def _calcola_gap(ctx: TaskContext,
                 deposito: dict[str, float]) -> dict[str, tuple[float, float]]:
    """Ritorna {risorsa: (valore_attuale, target)} per risorse sotto soglia."""
    usa = {
        "pomodoro": _cfg(ctx, "ZAINO_USA_POMODORO"),
        "legno":    _cfg(ctx, "ZAINO_USA_LEGNO"),
        "acciaio":  _cfg(ctx, "ZAINO_USA_ACCIAIO"),
        "petrolio": _cfg(ctx, "ZAINO_USA_PETROLIO"),
    }
    tgt = {
        "pomodoro": _cfg(ctx, "ZAINO_SOGLIA_POMODORO_M") * 1e6,
        "legno":    _cfg(ctx, "ZAINO_SOGLIA_LEGNO_M")    * 1e6,
        "acciaio":  _cfg(ctx, "ZAINO_SOGLIA_ACCIAIO_M")  * 1e6,
        "petrolio": _cfg(ctx, "ZAINO_SOGLIA_PETROLIO_M") * 1e6,
    }
    da_caricare: dict[str, tuple[float, float]] = {}
    for risorsa, target in tgt.items():
        if not usa.get(risorsa):
            ctx.log_msg(f"[ZAINO] [{risorsa}]: disabilitato")
            continue
        valore = deposito.get(risorsa, -1.0)
        if valore < 0:
            ctx.log_msg(f"[ZAINO] [{risorsa}]: OCR N/D")
            continue
        if valore < target:
            ctx.log_msg(
                f"[ZAINO] [{risorsa}]: {valore/1e6:.2f}M < "
                f"{target/1e6:.2f}M → carico (gap={(target-valore)/1e6:.3f}M)"
            )
            da_caricare[risorsa] = (valore, target)
        else:
            ctx.log_msg(
                f"[ZAINO] [{risorsa}]: {valore/1e6:.2f}M >= "
                f"{target/1e6:.2f}M — ok"
            )
    return da_caricare


def _get_frame(screen):
    frame = getattr(screen, "frame", None)
    if frame is None and isinstance(screen, np.ndarray):
        frame = screen
    return frame


# ==============================================================================
# SCROLL + WAIT UI STABILE
# ==============================================================================

def _wait_ui_stabile(ctx: TaskContext) -> bool:
    """
    Polling screenshot ogni BAG_SCROLL_POLL_S su ROI griglia.
    Esce quando diff pixel < BAG_SCROLL_SOGLIA oppure timeout.
    Aggiunge BAG_SCROLL_MIN_S di sleep finale.
    """
    poll_s  = _cfg(ctx, "BAG_SCROLL_POLL_S")
    soglia  = _cfg(ctx, "BAG_SCROLL_SOGLIA")
    timeout = _cfg(ctx, "BAG_SCROLL_TIMEOUT")
    min_s   = _cfg(ctx, "BAG_SCROLL_MIN_S")

    x1, y1, x2, y2 = _cfg(ctx, "BAG_GRIGLIA_ROI")
    t_start = time.time()
    frame_prec: Optional[np.ndarray] = None

    while True:
        elapsed = time.time() - t_start
        screen = ctx.device.screenshot()
        if screen is not None:
            frame = _get_frame(screen)
            if frame is not None:
                roi = frame[y1:y2, x1:x2]
                if frame_prec is not None and roi.shape == frame_prec.shape:
                    diff = int(np.mean(
                        np.abs(roi.astype(int) - frame_prec.astype(int))
                    ))
                    if diff <= soglia:
                        time.sleep(min_s)
                        ctx.log_msg(
                            f"[ZAINO] UI stabile in {elapsed:.1f}s (diff={diff})"
                        )
                        return True
                frame_prec = roi.copy()

        if elapsed >= timeout:
            ctx.log_msg(
                f"[ZAINO] WARN: UI non stabilizzata entro {timeout:.1f}s — procedo"
            )
            time.sleep(min_s)
            return False

        time.sleep(poll_s)


def _scroll_su(ctx: TaskContext) -> None:
    """Scroll griglia verso l'alto di una schermata + attesa stabilità."""
    ctx.device.swipe(
        _cfg(ctx, "BAG_SCROLL_X"), _cfg(ctx, "BAG_SCROLL_Y_START"),
        _cfg(ctx, "BAG_SCROLL_X"), _cfg(ctx, "BAG_SCROLL_Y_END"),
        duration_ms=_cfg(ctx, "BAG_SCROLL_MS"),
    )
    _wait_ui_stabile(ctx)


def _scroll_top(ctx: TaskContext) -> None:
    """Riporta la griglia in cima con scroll ripetuti verso il basso."""
    ctx.log_msg("[ZAINO] Scroll to top...")
    for _ in range(_cfg(ctx, "BAG_MAX_SCROLL")):
        ctx.device.swipe(
            _cfg(ctx, "BAG_SCROLL_X"), _cfg(ctx, "BAG_SCROLL_Y_END"),
            _cfg(ctx, "BAG_SCROLL_X"), _cfg(ctx, "BAG_SCROLL_Y_START"),
            duration_ms=_cfg(ctx, "BAG_SCROLL_MS"),
        )
        time.sleep(0.4)
    time.sleep(0.5)


# ==============================================================================
# OCR PANNELLO DESTRA BAG
# ==============================================================================

def _ocr_zona_bag(frame, zona: tuple) -> str:
    """OCR zona pannello destra BAG."""
    try:
        import pytesseract
        import os
        pytesseract.pytesseract.tesseract_cmd = os.environ.get(
            "TESSERACT_EXE",
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        )
        from PIL import Image
        x1, y1, x2, y2 = zona
        roi = frame[y1:y2, x1:x2]
        pil = Image.fromarray(roi[:, :, ::-1])
        w, h = pil.size
        if w == 0 or h == 0:
            return ""
        pil4x = pil.resize((w * 4, h * 4), Image.LANCZOS)
        return pytesseract.image_to_string(pil4x, config="--psm 6").strip()
    except Exception:
        return ""


def _parse_risorsa_pezzatura(testo: str) -> tuple[str, int]:
    """Estrae risorsa e pezzatura da testo titolo o grants."""
    tl = testo.lower()
    if " or " in tl:
        return ("misto", 0)
    risorsa = ""
    for kw, nome in _GRANTS_MAP:
        if kw in tl:
            risorsa = nome
            break
    if not risorsa:
        return ("", 0)
    nums = re.findall(r"\d+", testo.replace(",", "").replace(".", ""))
    pezzatura = int(nums[0]) if nums else 0
    return (risorsa, pezzatura)


def _parse_owned(testo: str) -> int:
    t = testo.replace(",", "")
    m = re.search(r"owned[:\s]+(\d+)", t, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)", t)
    return int(m.group(1)) if m else -1


def _leggi_pannello_bag(ctx: TaskContext, frame) -> tuple[str, int, int]:
    """
    Legge pannello destra dopo tap su icona.
    Ritorna (risorsa, pezzatura, owned). ('',0,0) se non leggibile.
    """
    t_titolo = _ocr_zona_bag(frame, _cfg(ctx, "BAG_TITOLO_ZONA"))
    t_owned  = _ocr_zona_bag(frame, _cfg(ctx, "BAG_OWNED_ZONA"))
    t_grants = _ocr_zona_bag(frame, _cfg(ctx, "BAG_GRANTS_ZONA"))

    risorsa, pezzatura = _parse_risorsa_pezzatura(t_titolo)
    if not risorsa:
        risorsa, pezzatura = _parse_risorsa_pezzatura(t_grants)

    if risorsa == "misto":
        return ("misto", 0, 0)

    owned = _parse_owned(t_owned)
    return (risorsa, pezzatura, owned)


# ==============================================================================
# MODALITÀ BAG
# ==============================================================================

def _pin_path(short: str, pezzatura: int) -> str:
    return f"pin/pin_{short}_{pezzatura}.png"


def _risorse_abilitate(ctx: TaskContext) -> set[str]:
    mapping = {
        "pomodoro": "ZAINO_USA_POMODORO",
        "legno":    "ZAINO_USA_LEGNO",
        "acciaio":  "ZAINO_USA_ACCIAIO",
        "petrolio": "ZAINO_USA_PETROLIO",
    }
    return {r for r, k in mapping.items() if _cfg(ctx, k)}


# ------------------------------------------------------------------------------
# FASE 1 — SCAN INVENTARIO
# ------------------------------------------------------------------------------

def _scan_inventario(
    ctx: TaskContext,
    risorse_target: set[str],
) -> dict[tuple[str, int], int]:
    """
    Scorre la griglia BAG con TM.
    Per ogni pin trovato → tap → OCR pannello destra → owned.
    Ritorna: {(risorsa, pezzatura): owned}
    """
    threshold   = _cfg(ctx, "BAG_PIN_THRESHOLD")
    delay_icona = _cfg(ctx, "BAG_DELAY_ICONA")
    max_vuote   = _cfg(ctx, "BAG_MAX_VUOTE")
    max_scroll  = _cfg(ctx, "BAG_MAX_SCROLL")
    griglia_roi = _cfg(ctx, "BAG_GRIGLIA_ROI")

    inventario: dict[tuple[str, int], int] = {}
    vuote_consec = 0
    scroll_count = 0

    ctx.log_msg("[ZAINO][SCAN] Avvio scan inventario...")

    while scroll_count <= max_scroll:
        screen = ctx.device.screenshot()
        if screen is None:
            ctx.log_msg("[ZAINO][SCAN] screenshot None — scroll e riprova")
            _scroll_su(ctx)
            scroll_count += 1
            continue

        nuovi = 0

        for short, (risorsa, pezzature) in _PIN_CATALOGO.items():
            if risorsa not in risorse_target:
                continue

            for pezzatura in pezzature:
                chiave = (risorsa, pezzatura)
                if chiave in inventario:
                    continue  # già trovato in schermata precedente

                pin = _pin_path(short, pezzatura)
                try:
                    match = ctx.matcher.find_one(
                        screen, pin,
                        threshold=threshold,
                        zone=griglia_roi,
                    )
                except FileNotFoundError:
                    continue  # pin non ancora disponibile

                if not match.found:
                    continue

                ctx.log_msg(
                    f"[ZAINO][SCAN] pin_{short}_{pezzatura} "
                    f"score={match.score:.3f} ({match.cx},{match.cy})"
                )

                # Tap → pannello destra → OCR owned
                ctx.device.tap(match.cx, match.cy)
                time.sleep(delay_icona)

                screen2 = ctx.device.screenshot()
                if screen2 is None:
                    continue
                frame2 = _get_frame(screen2)
                if frame2 is None:
                    continue

                _, _, owned = _leggi_pannello_bag(ctx, frame2)
                if owned <= 0:
                    ctx.log_msg("[ZAINO][SCAN] owned N/D — skip")
                    continue

                inventario[chiave] = owned
                nuovi += 1
                ctx.log_msg(
                    f"[ZAINO][SCAN] [{risorsa}] {pezzatura:,} owned={owned:,}"
                )

                # Riaggiorna screenshot dopo tap
                screen = ctx.device.screenshot()
                if screen is None:
                    break

        if nuovi == 0:
            vuote_consec += 1
            ctx.log_msg(
                f"[ZAINO][SCAN] Schermata vuota {vuote_consec}/{max_vuote}"
            )
            if vuote_consec >= max_vuote:
                ctx.log_msg("[ZAINO][SCAN] Fine griglia — stop scan")
                break
        else:
            vuote_consec = 0

        _scroll_su(ctx)
        scroll_count += 1

    ctx.log_msg(
        f"[ZAINO][SCAN] Completato: {len(inventario)} pezzature trovate"
    )
    return inventario


# ------------------------------------------------------------------------------
# FASE 2 — CALCOLO GREEDY
# ------------------------------------------------------------------------------

def _calcola_piano(
    ctx: TaskContext,
    gap_residui: dict[str, float],
    inventario: dict[tuple[str, int], int],
) -> list[tuple[str, str, int, int, int]]:
    """
    Greedy DESC per pezzatura.
    Ritorna: [(short, risorsa, pezzatura, n_usare, owned), ...]
    """
    risorsa_to_short = {v[0]: k for k, v in _PIN_CATALOGO.items()}
    piano: list[tuple[str, str, int, int, int]] = []

    for risorsa, gap in gap_residui.items():
        if gap <= 0:
            continue
        short = risorsa_to_short.get(risorsa)
        if not short:
            continue

        pezzature_ord = sorted(
            [pez for (r, pez) in inventario if r == risorsa],
            reverse=True,
        )

        gap_rim = gap
        for pez in pezzature_ord:
            if gap_rim <= 0:
                break
            owned = inventario.get((risorsa, pez), 0)
            if owned <= 0:
                continue
            n = min(owned, int(gap_rim // pez))
            if n <= 0:
                ctx.log_msg(
                    f"[ZAINO][GREEDY] [{risorsa}] {pez:,}: "
                    f"pezzatura > gap {gap_rim/1e6:.3f}M — skip"
                )
                continue
            piano.append((short, risorsa, pez, n, owned))
            gap_rim -= n * pez
            ctx.log_msg(
                f"[ZAINO][GREEDY] [{risorsa}] {pez:,} × {n} "
                f"= {n*pez/1e6:.3f}M | gap_rim={gap_rim/1e6:.3f}M"
            )

    return piano


# ------------------------------------------------------------------------------
# FASE 3 — ESECUZIONE PIANO
# ------------------------------------------------------------------------------

def _esegui_piano(
    ctx: TaskContext,
    piano: list[tuple[str, str, int, int, int]],
    dry_run: bool = False,
) -> dict[str, float]:
    """
    Scroll to top + ricerca TM pin del piano + tap + input n + USE.
    Ritorna {risorsa: quantita_usata_totale}.
    """
    threshold   = _cfg(ctx, "BAG_PIN_THRESHOLD")
    delay_icona = _cfg(ctx, "BAG_DELAY_ICONA")
    delay_input = _cfg(ctx, "BAG_DELAY_INPUT")
    delay_use   = _cfg(ctx, "BAG_DELAY_USE")
    max_vuote   = _cfg(ctx, "BAG_MAX_VUOTE")
    max_scroll  = _cfg(ctx, "BAG_MAX_SCROLL")
    griglia_roi = _cfg(ctx, "BAG_GRIGLIA_ROI")
    campo_qty   = _cfg(ctx, "BAG_CAMPO_QTY")
    max_btn     = _cfg(ctx, "BAG_MAX")
    ok_xy       = _cfg(ctx, "BAG_OK")
    use_xy      = _cfg(ctx, "BAG_USE")
    modo        = "[DRY] " if dry_run else ""

    # Stato esecuzione: quanti pezzi restano da usare per ogni voce del piano
    piano_rim:   dict[tuple[str, int], int] = {}
    piano_short: dict[tuple[str, int], str] = {}
    esiti:       dict[str, float]           = {}

    for short, risorsa, pez, n, owned in piano:
        piano_rim[(risorsa, pez)]   = n
        piano_short[(risorsa, pez)] = short
        esiti.setdefault(risorsa, 0.0)

    _scroll_top(ctx)
    time.sleep(0.5)

    vuote_consec = 0
    scroll_count = 0

    ctx.log_msg(f"[ZAINO]{modo}Esecuzione piano ({len(piano)} voci)...")

    while scroll_count <= max_scroll:
        if all(n <= 0 for n in piano_rim.values()):
            ctx.log_msg(f"[ZAINO]{modo}Piano completato — STOP")
            break

        screen = ctx.device.screenshot()
        if screen is None:
            _scroll_su(ctx)
            scroll_count += 1
            continue

        nuovi = 0

        for (risorsa, pez), n_rim in list(piano_rim.items()):
            if n_rim <= 0:
                continue

            short = piano_short[(risorsa, pez)]
            pin   = _pin_path(short, pez)

            try:
                match = ctx.matcher.find_one(
                    screen, pin,
                    threshold=threshold,
                    zone=griglia_roi,
                )
            except FileNotFoundError:
                continue

            if not match.found:
                continue

            ctx.log_msg(
                f"[ZAINO]{modo}[{risorsa}] {pez:,} trovato "
                f"score={match.score:.3f} — uso {n_rim}"
            )

            if not dry_run:
                ctx.device.tap(match.cx, match.cy)
                time.sleep(delay_icona)

                # Verifica owned reale dal pannello (aggiusta se serve)
                screen_pan = ctx.device.screenshot()
                n_finale = n_rim
                owned_reale = n_rim
                if screen_pan is not None:
                    frame_pan = _get_frame(screen_pan)
                    if frame_pan is not None:
                        _, _, owned_ocr = _leggi_pannello_bag(ctx, frame_pan)
                        if owned_ocr > 0:
                            owned_reale = owned_ocr
                            if owned_reale < n_rim:
                                ctx.log_msg(
                                    f"[ZAINO]{modo}[{risorsa}] {pez:,}: "
                                    f"owned reale {owned_reale} < piano {n_rim}"
                                    f" — aggiusto"
                                )
                                n_finale = owned_reale

                if n_finale == owned_reale:
                    ctx.device.tap(*max_btn)
                    time.sleep(delay_input)
                else:
                    ctx.device.tap(*campo_qty)
                    time.sleep(delay_input)
                    ctx.device.input_text(str(n_finale))
                    time.sleep(delay_input)
                    ctx.device.tap(*ok_xy)
                    time.sleep(delay_input)

                ctx.device.tap(*use_xy)
                time.sleep(delay_use)
            else:
                n_finale = n_rim

            quantita = n_finale * pez
            esiti[risorsa] = esiti.get(risorsa, 0.0) + quantita
            piano_rim[(risorsa, pez)] = 0
            nuovi += 1

            ctx.log_msg(
                f"[ZAINO]{modo}[{risorsa}] {pez:,} × {n_finale} "
                f"= {quantita/1e6:.3f}M eseguito"
            )

            # Riaggiorna screenshot dopo USE
            screen = ctx.device.screenshot()
            if screen is None:
                break

        if nuovi == 0:
            vuote_consec += 1
            ctx.log_msg(
                f"[ZAINO]{modo}Schermata senza match: {vuote_consec}/{max_vuote}"
            )
            if vuote_consec >= max_vuote:
                ctx.log_msg(f"[ZAINO]{modo}Fine griglia — stop esecuzione")
                break
        else:
            vuote_consec = 0

        _scroll_su(ctx)
        scroll_count += 1

    return esiti


def _esegui_bag(
    ctx: TaskContext,
    da_caricare: dict[str, tuple[float, float]],
    dry_run: bool = False,
) -> dict[str, float]:
    """Coordina FASE 1 + FASE 2 + FASE 3."""
    modo     = "[DRY] " if dry_run else ""
    snap_pre = {r: v for r, (v, _) in da_caricare.items()}
    gap_residui   = {r: tgt - val for r, (val, tgt) in da_caricare.items()}
    risorse_target = set(da_caricare.keys())

    # Apri BAG → RESOURCE
    ctx.log_msg(f"[ZAINO]{modo}Apertura BAG...")
    ctx.navigator.tap_barra(ctx, "bag")
    time.sleep(_cfg(ctx, "BAG_DELAY_APRI"))

    ctx.log_msg(f"[ZAINO]{modo}tap RESOURCE {_cfg(ctx, 'BAG_RESOURCE_TAP')}")
    ctx.device.tap(*_cfg(ctx, "BAG_RESOURCE_TAP"))
    time.sleep(1.0)

    esiti: dict[str, float] = {
        r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]
    }

    try:
        # FASE 1
        inventario = _scan_inventario(ctx, risorse_target)
        if not inventario:
            ctx.log_msg(f"[ZAINO]{modo}Inventario vuoto — nessuna pezzatura trovata")
            return esiti

        # FASE 2
        piano = _calcola_piano(ctx, gap_residui, inventario)
        if not piano:
            ctx.log_msg(f"[ZAINO]{modo}Piano vuoto — nessuna azione necessaria")
            return esiti

        ctx.log_msg(f"[ZAINO]{modo}Piano ({len(piano)} voci):")
        for short, risorsa, pez, n, owned in piano:
            ctx.log_msg(
                f"[ZAINO]{modo}  [{risorsa}] {pez:,} × {n}/{owned} "
                f"= {n*pez/1e6:.3f}M"
            )

        # FASE 3
        esiti_piano = _esegui_piano(ctx, piano, dry_run=dry_run)

        if not dry_run:
            time.sleep(_cfg(ctx, "BAG_DELAY_POST"))
            snap_post = _ocr_deposito(ctx)
            for risorsa, val_pre in snap_pre.items():
                val_post = snap_post.get(risorsa, -1.0)
                if val_post >= 0 and val_pre >= 0:
                    reale = max(0.0, val_post - val_pre)
                    esiti[risorsa] = reale / 1e6
                    ctx.log_msg(
                        f"[ZAINO] [{risorsa}]: PRE={val_pre/1e6:.2f}M "
                        f"POST={val_post/1e6:.2f}M → reale={reale/1e6:.3f}M"
                    )
        else:
            for risorsa, qtot in esiti_piano.items():
                esiti[risorsa] = qtot / 1e6

    finally:
        ctx.log_msg(f"[ZAINO]{modo}Torna HOME")
        ctx.navigator.vai_in_home()

    return esiti


# ==============================================================================
# MODALITÀ SVUOTA
# ==============================================================================

def _svuota_riga(ctx: TaskContext, y_riga: int) -> None:
    use_x = _cfg(ctx, "SV_TAP_USE_X")
    max_x = _cfg(ctx, "SV_TAP_MAX_X")
    ctx.log_msg(f"[ZAINO][SV] USE→Max→USE ({use_x},{y_riga})")
    ctx.device.tap(use_x, y_riga)
    time.sleep(_cfg(ctx, "SV_DELAY_USE"))
    ctx.device.tap(max_x, y_riga)
    time.sleep(_cfg(ctx, "SV_DELAY_MAX"))
    ctx.device.tap(use_x, y_riga)
    time.sleep(_cfg(ctx, "SV_DELAY_CONF"))


def _riga_ha_use_giallo(screen, y_riga: int) -> bool:
    try:
        frame = _get_frame(screen)
        if frame is None:
            return True
        y1 = max(0, y_riga - 30)
        y2 = min(frame.shape[0], y_riga + 20)
        roi = frame[y1:y2, 650:810]
        r = roi[:, :, 2].astype(int)
        g = roi[:, :, 1].astype(int)
        b = roi[:, :, 0].astype(int)
        return int(((r > 180) & (g > 130) & (b < 80)).sum()) >= 20
    except Exception:
        return True


def _svuota_sidebar(ctx: TaskContext, risorsa: str) -> None:
    sidebar_map = {
        "pomodoro": "SV_SIDEBAR_POMODORO",
        "legno":    "SV_SIDEBAR_LEGNO",
        "acciaio":  "SV_SIDEBAR_ACCIAIO",
        "petrolio": "SV_SIDEBAR_PETROLIO",
    }
    key = sidebar_map.get(risorsa)
    if not key:
        ctx.log_msg(f"[ZAINO][SV] [{risorsa}]: sidebar N/D")
        return

    coord = _cfg(ctx, key)
    ctx.log_msg(f"[ZAINO][SV] [{risorsa}]: tap sidebar {coord}")
    ctx.device.tap(*coord)
    time.sleep(_cfg(ctx, "SV_DELAY_SIDEBAR"))

    prima_y  = _cfg(ctx, "SV_PRIMA_RIGA_Y")
    alt_riga = _cfg(ctx, "SV_ALTEZZA_RIGA")
    max_rig  = _cfg(ctx, "SV_MAX_RIGHE")

    righe_vuote = 0
    while righe_vuote < 3:
        screen = ctx.device.screenshot()
        if screen is None:
            break
        trovata = False
        for i in range(max_rig):
            y = prima_y + i * alt_riga
            if _riga_ha_use_giallo(screen, y):
                _svuota_riga(ctx, y)
                trovata = True
                break
        if not trovata:
            righe_vuote += 1
        else:
            righe_vuote = 0

    ctx.log_msg(f"[ZAINO][SV] [{risorsa}]: svuotato")


def _esegui_svuota(ctx: TaskContext) -> dict[str, float]:
    usa = {
        "pomodoro": _cfg(ctx, "ZAINO_USA_POMODORO"),
        "legno":    _cfg(ctx, "ZAINO_USA_LEGNO"),
        "acciaio":  _cfg(ctx, "ZAINO_USA_ACCIAIO"),
        "petrolio": _cfg(ctx, "ZAINO_USA_PETROLIO"),
    }
    risorse_da_svuotare = [r for r, on in usa.items() if on]

    if not risorse_da_svuotare:
        ctx.log_msg("[ZAINO][SV] Nessuna risorsa abilitata")
        return {r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]}

    snap_pre = _ocr_deposito(ctx)
    ctx.log_msg(
        f"[ZAINO][SV] PRE: "
        f"pomodoro={snap_pre.get('pomodoro',-1)/1e6:.2f}M "
        f"legno={snap_pre.get('legno',-1)/1e6:.2f}M "
        f"acciaio={snap_pre.get('acciaio',-1)/1e6:.2f}M "
        f"petrolio={snap_pre.get('petrolio',-1)/1e6:.2f}M"
    )

    tap_apri = _cfg(ctx, "SV_TAP_APRI")
    ctx.log_msg(f"[ZAINO][SV] Apertura zaino {tap_apri}")
    ctx.device.tap(*tap_apri)
    time.sleep(_cfg(ctx, "SV_DELAY_APRI"))

    esiti: dict[str, float] = {
        r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]
    }

    try:
        for risorsa in risorse_da_svuotare:
            ctx.log_msg(f"[ZAINO][SV] === {risorsa.upper()} ===")
            _svuota_sidebar(ctx, risorsa)
    finally:
        tap_chiudi = _cfg(ctx, "SV_TAP_CHIUDI")
        ctx.log_msg(f"[ZAINO][SV] Chiusura zaino {tap_chiudi}")
        ctx.device.tap(*tap_chiudi)
        time.sleep(1.0)

    snap_post = _ocr_deposito(ctx)
    for risorsa in risorse_da_svuotare:
        pre  = snap_pre.get(risorsa, -1.0)
        post = snap_post.get(risorsa, -1.0)
        if pre >= 0 and post >= 0:
            reale = max(0.0, post - pre)
            esiti[risorsa] = reale / 1e6
            ctx.log_msg(
                f"[ZAINO][SV] [{risorsa}]: PRE={pre/1e6:.2f}M "
                f"POST={post/1e6:.2f}M → scaricato={reale/1e6:.3f}M"
            )

    return esiti


# ==============================================================================
# TASK V6
# ==============================================================================

class ZainoTask(Task):
    """
    Task settimanale (168h) — scarica risorse al deposito.

    Modalità selezionabile via global_config.json → zaino.modalita:
      "bag"    → scan TM + greedy + esecuzione (default)
      "svuota" → svuota completamente tutte le pezzature abilitate
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
        """Simulazione: scan + calcolo, nessun USE."""
        return self._esegui(ctx, dry_run=True)

    def run(self, ctx: TaskContext,
            deposito: Optional[dict[str, float]] = None) -> TaskResult:
        return self._esegui(ctx, dry_run=False, deposito=deposito)

    def _esegui(self,
                ctx: TaskContext,
                dry_run: bool = False,
                deposito: Optional[dict[str, float]] = None) -> TaskResult:

        modo = "[DRY] " if dry_run else ""

        if not _cfg(ctx, "ZAINO_ABILITATO"):
            ctx.log_msg(f"[ZAINO]{modo}disabilitato — skip")
            return TaskResult(
                success=True, message="disabilitato",
                data={r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]},
            )

        modalita = _cfg(ctx, "ZAINO_MODALITA")
        ctx.log_msg(f"[ZAINO]{modo}Modalità: {modalita.upper()}")

        # ── MODALITÀ SVUOTA ───────────────────────────────────────────────────
        if modalita == "svuota":
            if dry_run:
                ctx.log_msg("[ZAINO][DRY] modalità svuota non supporta dry-run")
                return TaskResult(success=True, message="dry-run N/A per svuota",
                                  data={})
            esiti  = _esegui_svuota(ctx)
            totale = sum(esiti.values())
            ctx.log_msg(f"[ZAINO][SV] Completato — {totale:.3f}M totale")
            return TaskResult(
                success=True,
                message=f"svuotato {totale:.3f}M totale",
                data=esiti,
            )

        # ── MODALITÀ BAG ──────────────────────────────────────────────────────
        ctx.log_msg(f"[ZAINO]{modo}OCR deposito PRE...")
        if deposito is None:
            snapshot_pre = _ocr_deposito(ctx)
            if not snapshot_pre:
                ctx.log_msg(f"[ZAINO]{modo}Deposito N/D — skip")
                return TaskResult(
                    success=False, message="deposito non disponibile",
                    data={r: 0.0 for r in ["pomodoro","legno","acciaio","petrolio"]},
                )
        else:
            snapshot_pre = deposito

        ctx.log_msg(
            f"[ZAINO]{modo}PRE: "
            f"pomodoro={snapshot_pre.get('pomodoro',-1)/1e6:.2f}M "
            f"legno={snapshot_pre.get('legno',-1)/1e6:.2f}M "
            f"acciaio={snapshot_pre.get('acciaio',-1)/1e6:.2f}M "
            f"petrolio={snapshot_pre.get('petrolio',-1)/1e6:.2f}M"
        )

        da_caricare = _calcola_gap(ctx, snapshot_pre)
        if not da_caricare:
            ctx.log_msg(f"[ZAINO]{modo}Tutte sopra soglia — nessun carico")
            return TaskResult(
                success=True, message="nessun carico necessario",
                data={r: 0.0 for r in ["pomodoro","legno","acciaio","petrolio"]},
            )

        try:
            esiti = _esegui_bag(ctx, da_caricare, dry_run=dry_run)
        except Exception as exc:
            ctx.log_msg(f"[ZAINO]{modo}Errore: {exc}")
            return TaskResult(
                success=False, message=f"errore: {exc}",
                data={r: 0.0 for r in ["pomodoro","legno","acciaio","petrolio"]},
            )

        totale = sum(esiti.values())
        msg    = f"{'[DRY] ' if dry_run else ''}scaricato {totale:.3f}M totale"
        ctx.log_msg(f"[ZAINO]{modo}Completato — {msg}")
        return TaskResult(success=True, message=msg, data=esiti)
