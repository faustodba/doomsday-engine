# ==============================================================================
#  DOOMSDAY ENGINE V6 — tasks/zaino.py                              Step 19
#
#  Due modalità selezionabili da global_config.json → zaino.modalita:
#
#  MODALITÀ "bag" (default):
#    Usa interfaccia BAG (tap_barra "bag" → RESOURCE).
#    Scan griglia → OCR pannello destra → calcolo quantità precisa → USE.
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
    "ZAINO_MODALITA":      "bag",       # "bag" | "svuota"

    # Abilitazione risorse
    "ZAINO_ABILITATO":     True,
    "ZAINO_USA_POMODORO":  True,
    "ZAINO_USA_LEGNO":     True,
    "ZAINO_USA_ACCIAIO":   False,
    "ZAINO_USA_PETROLIO":  True,

    # Soglie target (milioni) — solo modalità bag
    "ZAINO_SOGLIA_POMODORO_M": 10.0,
    "ZAINO_SOGLIA_LEGNO_M":    10.0,
    "ZAINO_SOGLIA_ACCIAIO_M":   7.0,
    "ZAINO_SOGLIA_PETROLIO_M":  5.0,

    # ── MODALITÀ BAG ─────────────────────────────────────────────────────────
    "BAG_RESOURCE_TAP":    (65, 110),   # tab RESOURCE nel BAG
    "BAG_COL_X":           [191, 295, 399, 503, 607],
    "BAG_RIGA_Y":          [176, 280, 384, 488],
    # Pannello destra
    "BAG_TITOLO_ZONA":     (665,  80, 824, 124),
    "BAG_OWNED_ZONA":      (664, 175, 796, 206),
    "BAG_GRANTS_ZONA":     (663, 206, 839, 246),
    "BAG_CAMPO_QTY":       (738, 445),
    "BAG_MAX":             (883, 444),
    "BAG_OK":              (879, 509),
    "BAG_USE":             (806, 492),
    # Ritardi BAG
    "BAG_DELAY_APRI":      2.0,
    "BAG_DELAY_ICONA":     0.8,
    "BAG_DELAY_INPUT":     0.5,
    "BAG_DELAY_USE":       1.0,
    "BAG_DELAY_SCROLL":    0.8,
    "BAG_DELAY_POST":      1.5,

    # ── MODALITÀ SVUOTA ───────────────────────────────────────────────────────
    "SV_TAP_APRI":         (430, 18),
    "SV_TAP_CHIUDI":       (783, 68),
    "SV_SIDEBAR_POMODORO": (80, 130),
    "SV_SIDEBAR_LEGNO":    (80, 200),
    "SV_SIDEBAR_ACCIAIO":  (80, 270),
    "SV_SIDEBAR_PETROLIO": (80, 340),
    "SV_TAP_USE_X":        722,
    "SV_TAP_MAX_X":        601,
    "SV_PRIMA_RIGA_Y":     140,
    "SV_ALTEZZA_RIGA":     79,
    "SV_MAX_RIGHE":        5,
    "SV_DELAY_APRI":       2.0,
    "SV_DELAY_SIDEBAR":    1.0,
    "SV_DELAY_USE":        0.8,
    "SV_DELAY_MAX":        0.3,
    "SV_DELAY_CONF":       1.5,
}

# Mapping grants/titolo → risorsa interna
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
            ctx.log_msg(f"[ZAINO] [{risorsa}]: {valore/1e6:.2f}M < "
                        f"{target/1e6:.2f}M → carico (gap={( target-valore)/1e6:.3f}M)")
            da_caricare[risorsa] = (valore, target)
        else:
            ctx.log_msg(f"[ZAINO] [{risorsa}]: {valore/1e6:.2f}M >= "
                        f"{target/1e6:.2f}M — ok")
    return da_caricare


def _get_frame(screen):
    frame = getattr(screen, "frame", None)
    if frame is None and isinstance(screen, np.ndarray):
        frame = screen
    return frame


# ==============================================================================
# MODALITÀ BAG
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
    """
    Estrae risorsa e pezzatura da testo titolo o grants.
    Ritorna ('', 0) se misto o non leggibile.
    """
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

    # Titolo come fonte primaria, grants come fallback
    risorsa, pezzatura = _parse_risorsa_pezzatura(t_titolo)
    if not risorsa:
        risorsa, pezzatura = _parse_risorsa_pezzatura(t_grants)

    # Pack misto → ignora
    if risorsa == "misto":
        return ("misto", 0, 0)

    owned = _parse_owned(t_owned)
    return (risorsa, pezzatura, owned)


def _bag_scan_ed_esegui(ctx: TaskContext,
                        gap_residui: dict[str, float],
                        dry_run: bool = False) -> dict[str, list[dict]]:
    """
    Scorre griglia BAG schermata per schermata.

    Logica scroll corretta:
      - Tappa tutte le N righe visibili nella schermata corrente
      - Dopo aver processato tutte le righe → scroll di una schermata intera
        (N_RIGHE × 104px) verso l'alto
      - Ripete con la schermata successiva
      - Stop quando icona già vista (ciclo) o 3 schermate vuote consecutive

    Ottimizzazione USE:
      - n == owned → tap MAX → tap USE
      - n <  owned → tap campo → input_text(n) → tap OK → tap USE
    """
    col_x        = _cfg(ctx, "BAG_COL_X")
    riga_y       = _cfg(ctx, "BAG_RIGA_Y")
    campo_qty    = _cfg(ctx, "BAG_CAMPO_QTY")
    max_btn      = _cfg(ctx, "BAG_MAX")
    ok_xy        = _cfg(ctx, "BAG_OK")
    use_xy       = _cfg(ctx, "BAG_USE")
    delay_icona  = _cfg(ctx, "BAG_DELAY_ICONA")
    delay_input  = _cfg(ctx, "BAG_DELAY_INPUT")
    delay_use    = _cfg(ctx, "BAG_DELAY_USE")
    delay_scroll = _cfg(ctx, "BAG_DELAY_SCROLL")
    modo         = "[DRY] " if dry_run else ""

    # Scroll di una schermata intera = N_righe × (box + gap) = 4 × 104 = 416px
    N_RIGHE      = len(riga_y)
    SCROLL_SCHERMATA = N_RIGHE * 104   # 416px

    operazioni: dict[str, list[dict]] = {r: [] for r in gap_residui}
    icone_viste: set[tuple[str, int]] = set()
    scroll_count          = 0
    max_scroll            = 10
    schermate_vuote_consec = 0

    while scroll_count <= max_scroll:
        if all(g <= 0 for g in gap_residui.values()):
            ctx.log_msg(f"[ZAINO]{modo}Tutti i gap colmati — STOP")
            break

        nuove_in_schermata = 0

        # Processa tutte le righe visibili
        for y in riga_y:
            for x in col_x:
                ctx.device.tap(x, y)
                time.sleep(delay_icona)

                screen2 = ctx.device.screenshot()
                if screen2 is None:
                    continue
                frame2 = _get_frame(screen2)
                if frame2 is None:
                    continue

                risorsa, pezzatura, owned = _leggi_pannello_bag(ctx, frame2)

                if not risorsa or risorsa == "misto" or pezzatura <= 0:
                    continue

                ctx.log_msg(
                    f"[ZAINO]{modo}({x},{y}): "
                    f"{risorsa} {pezzatura:,} owned={owned}"
                )

                # Già vista → stiamo ciclando → stop
                chiave = (risorsa, pezzatura)
                if chiave in icone_viste:
                    ctx.log_msg(f"[ZAINO]{modo}Icona già vista — fine griglia")
                    return operazioni
                icone_viste.add(chiave)
                nuove_in_schermata += 1

                if risorsa not in gap_residui:
                    continue

                gap_r = gap_residui[risorsa]
                if gap_r <= 0 or owned <= 0:
                    continue

                n = min(owned, int(gap_r // pezzatura))
                if n <= 0:
                    ctx.log_msg(
                        f"[ZAINO]{modo}[{risorsa}] {pezzatura:,}: "
                        f"pezzatura > gap {gap_r/1e6:.3f}M — skip"
                    )
                    continue

                ctx.log_msg(
                    f"[ZAINO]{modo}[{risorsa}] {pezzatura:,}: "
                    f"uso {n}/{owned} pezzi ({n*pezzatura/1e6:.3f}M)"
                    + (" [MAX]" if n == owned else "")
                )

                if not dry_run:
                    if n == owned:
                        ctx.device.tap(*max_btn)
                        time.sleep(delay_input)
                    else:
                        ctx.device.tap(*campo_qty)
                        time.sleep(delay_input)
                        ctx.device.input_text(str(n))
                        time.sleep(delay_input)
                        ctx.device.tap(*ok_xy)
                        time.sleep(delay_input)
                    ctx.device.tap(*use_xy)
                    time.sleep(delay_use)

                gap_residui[risorsa] -= n * pezzatura
                operazioni[risorsa].append({
                    "pezzatura": pezzatura,
                    "n":         n,
                    "quantita":  n * pezzatura,
                    "max":       n == owned,
                })
                ctx.log_msg(
                    f"[ZAINO]{modo}[{risorsa}]: gap residuo = "
                    f"{gap_residui[risorsa]/1e6:.3f}M"
                )

        # Schermate vuote consecutive
        if nuove_in_schermata == 0:
            schermate_vuote_consec += 1
            ctx.log_msg(
                f"[ZAINO]{modo}Schermata vuota "
                f"{schermate_vuote_consec}/3"
            )
            if schermate_vuote_consec >= 3:
                ctx.log_msg(f"[ZAINO]{modo}3 schermate vuote — fine griglia")
                break
        else:
            schermate_vuote_consec = 0

        # Scroll di una schermata intera verso l'alto
        ctx.device.swipe(480, riga_y[-1] + 52, 480, riga_y[0] - 52,
                         duration_ms=400)
        time.sleep(delay_scroll)
        scroll_count += 1

    return operazioni


def _esegui_bag(ctx: TaskContext,
                da_caricare: dict[str, tuple[float, float]],
                dry_run: bool = False) -> dict[str, float]:
    """Esegue modalità BAG. Ritorna {risorsa: scaricato_reale_M}."""
    modo    = "[DRY] " if dry_run else ""
    snap_pre = {r: v for r, (v, _) in da_caricare.items()}

    gap_residui = {
        r: tgt - val for r, (val, tgt) in da_caricare.items()
    }

    # Apri BAG → RESOURCE
    ctx.log_msg(f"[ZAINO]{modo}Apertura BAG...")
    ctx.navigator.tap_barra(ctx, "bag")
    time.sleep(_cfg(ctx, "BAG_DELAY_APRI"))

    tap_res = _cfg(ctx, "BAG_RESOURCE_TAP")
    ctx.log_msg(f"[ZAINO]{modo}tap RESOURCE {tap_res}")
    ctx.device.tap(*tap_res)
    time.sleep(1.0)

    esiti: dict[str, float] = {
        r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]
    }

    try:
        operazioni = _bag_scan_ed_esegui(ctx, gap_residui, dry_run=dry_run)

        for risorsa, ops in operazioni.items():
            if ops:
                dettaglio = ", ".join(f"{o['pezzatura']:,}×{o['n']}" for o in ops)
                totale_ops = sum(o["quantita"] for o in ops)
                ctx.log_msg(
                    f"[ZAINO]{modo}[{risorsa}]: {dettaglio} = "
                    f"{totale_ops/1e6:.3f}M"
                )

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
            for risorsa, ops in operazioni.items():
                esiti[risorsa] = sum(o["quantita"] for o in ops) / 1e6

    finally:
        ctx.log_msg(f"[ZAINO]{modo}Torna HOME")
        ctx.navigator.vai_in_home()

    return esiti


# ==============================================================================
# MODALITÀ SVUOTA
# ==============================================================================

def _svuota_riga(ctx: TaskContext, y_riga: int) -> None:
    """USE → Max → USE su una riga."""
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
    """Verifica presenza pulsante USE giallo nella riga."""
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
    """Naviga sidebar e svuota completamente la risorsa."""
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
    """
    Modalità SVUOTA: apre zaino da HOME e svuota completamente
    le risorse abilitate senza controllo soglie.
    """
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

    # OCR PRE
    snap_pre = _ocr_deposito(ctx)
    ctx.log_msg(
        f"[ZAINO][SV] PRE: "
        f"pomodoro={snap_pre.get('pomodoro',-1)/1e6:.2f}M "
        f"legno={snap_pre.get('legno',-1)/1e6:.2f}M "
        f"acciaio={snap_pre.get('acciaio',-1)/1e6:.2f}M "
        f"petrolio={snap_pre.get('petrolio',-1)/1e6:.2f}M"
    )

    # Apri zaino
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

    # OCR POST
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
      "bag"    → scan griglia BAG + input quantità precisa (default)
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
        """Simulazione modalità bag: scan + calcolo, nessun USE."""
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
            esiti = _esegui_svuota(ctx)
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
        msg = f"{'[DRY] ' if dry_run else ''}scaricato {totale:.3f}M totale"
        ctx.log_msg(f"[ZAINO]{modo}Completato — {msg}")
        return TaskResult(success=True, message=msg, data=esiti)
