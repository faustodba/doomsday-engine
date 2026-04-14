# ==============================================================================
#  DOOMSDAY ENGINE V6 — tasks/zaino.py                              Step 19
#
#  Scarico risorse dallo zaino virtuale via interfaccia BAG.
#
#  APPROCCIO (v4 — 14/04/2026):
#    Usa l'interfaccia BAG (tap_barra "bag") invece dello zaino legacy.
#    BAG mostra griglia icone con owned visibile + pannello destra con
#    quantità editabile e USE button.
#
#  ALGORITMO:
#    1. OCR PRE: legge deposito dalla barra superiore (HOME)
#    2. Calcola gap per ogni risorsa abilitata e sotto soglia
#    3. Naviga BAG → RESOURCE
#    4. SCAN + ESECUZIONE in un'unica passata (riga per riga):
#       a. Per ogni icona visibile nella griglia (5 col × N righe):
#          - tap icona → pannello destra mostra nome+owned
#          - OCR "Grants N Risorsa" → estrai pezzatura e tipo risorsa
#          - OCR "Owned: N" → quantità disponibile
#          - Se risorsa non è tra quelle da caricare → skip
#          - Calcola n = min(owned, floor(gap_residuo / pezzatura))
#          - Se n == 0 → skip (pezzatura troppo grande o gap già colmato)
#          - tap campo quantità → input_text(n) → tap OK
#          - tap USE → gap_residuo -= n * pezzatura
#          - Se gap_residuo <= 0 → STOP
#       b. Swipe giù → riga successiva
#       c. Stop se nessuna nuova icona o gap colmato
#    5. OCR POST: misura reale scaricato = post - pre
#    6. BACK → HOME
#
#  COORDINATE CALIBRATE (960x540 — da screenshot reali 14/04/2026):
#    GRIGLIA_COL_X      = [185, 268, 348, 428, 508]
#    GRIGLIA_RIGA_Y     = [196, 301, 399, 498]   (4 righe per schermata)
#    PANNELLO_OWNED     = zona (645, 165, 960, 210)
#    PANNELLO_GRANTS    = zona (645, 210, 960, 250)
#    CAMPO_QTY          = (738, 444)
#    OK_TASTIERA        = (879, 509)  ← quando tastiera aperta
#    USE_BUTTON         = (805, 493)
#    TAP_BAG_RESOURCE   = (65, 110)
#    BACK               = (28, 28)
#
#  OCR PANNELLO DESTRA:
#    "Owned: N"         → numero N = quantità disponibile
#    "Grants N Food"    → pezzatura N, risorsa = pomodoro
#    "Grants N Wood"    → pezzatura N, risorsa = legno
#    "Grants N Steel"   → pezzatura N, risorsa = acciaio
#    "Grants N Oil"     → pezzatura N, risorsa = petrolio
#    "Grants N Food or N Wood" → pack misto → ignorato
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
    # Navigazione BAG
    "TAP_BAG_RESOURCE":    (65, 110),    # tab RESOURCE nel BAG
    "BACK":                (28, 28),     # pulsante back

    # Griglia icone — 5 colonne, 4 righe visibili
    "GRIGLIA_COL_X":       [185, 268, 348, 428, 508],
    "GRIGLIA_RIGA_Y":      [196, 301, 399, 498],

    # Pannello destra — zone OCR
    "PANNELLO_OWNED_X1":   645,
    "PANNELLO_OWNED_X2":   960,
    "PANNELLO_OWNED_Y1":   165,
    "PANNELLO_OWNED_Y2":   210,
    "PANNELLO_GRANTS_X1":  645,
    "PANNELLO_GRANTS_X2":  960,
    "PANNELLO_GRANTS_Y1":  210,
    "PANNELLO_GRANTS_Y2":  250,

    # Controlli pannello destra
    "CAMPO_QTY":           (738, 444),   # campo quantità (tap per aprire tastiera)
    "OK_TASTIERA":         (879, 509),   # OK dopo input tastiera
    "USE_BUTTON":          (805, 493),   # USE button
    "MAX_BUTTON":          (883, 444),   # MAX button

    # Ritardi
    "DELAY_APRI_BAG":      2.0,          # attesa dopo apertura BAG
    "DELAY_TAP_ICONA":     0.8,          # attesa dopo tap icona
    "DELAY_INPUT_QTY":     0.5,          # attesa dopo input quantità
    "DELAY_TAP_USE":       1.0,          # attesa dopo USE
    "DELAY_SCROLL":        0.8,          # attesa dopo swipe
    "DELAY_POST_SCARICO":  1.5,          # attesa prima OCR post

    # Abilitazione risorse
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

# Mapping parole chiave Grants → nome risorsa interno
_GRANTS_RISORSA = {
    "food":  "pomodoro",
    "wood":  "legno",
    "steel": "acciaio",
    "oil":   "petrolio",
}


def _cfg(ctx: TaskContext, key: str):
    return ctx.config.get(key, _DEFAULTS[key])


# ------------------------------------------------------------------------------
# OCR helpers
# ------------------------------------------------------------------------------

def _ocr_deposito(ctx: TaskContext) -> dict[str, float]:
    """Legge risorse dalla barra superiore."""
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


def _ocr_zona_testo(frame: np.ndarray,
                    x1: int, y1: int, x2: int, y2: int) -> str:
    """OCR su zona rettangolare del frame BGR. Ritorna testo pulito."""
    try:
        import pytesseract
        from PIL import Image
        roi = frame[y1:y2, x1:x2]
        pil = Image.fromarray(roi[:, :, ::-1])  # BGR→RGB
        w, h = pil.size
        pil4x = pil.resize((w * 4, h * 4), Image.LANCZOS)
        cfg = "--psm 7"
        return pytesseract.image_to_string(pil4x, config=cfg).strip()
    except Exception:
        return ""


def _parse_owned(testo: str) -> int:
    """
    Estrae owned da testo pannello destra.
    Es: 'Owned: 519' → 519, 'Owned: 33' → 33
    """
    testo = testo.replace(",", "")
    m = re.search(r"owned[:\s]+(\d+)", testo, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Fallback: primo numero
    m = re.search(r"(\d+)", testo)
    return int(m.group(1)) if m else -1


def _parse_grants(testo: str) -> tuple[str, int]:
    """
    Estrae risorsa e pezzatura da testo Grants.
    Es: 'Grants 150,000 Wood.' → ('legno', 150000)
        'Grants 1,500,000 Food.' → ('pomodoro', 1500000)
        'Grants 1,000 Food or 1,000 Wood.' → ('misto', 0) → ignora
    Returns: (risorsa, pezzatura) — ('', 0) se non parsabile o misto
    """
    testo_low = testo.lower()

    # Pack misto → ignora
    if " or " in testo_low:
        return ("misto", 0)

    # Trova tipo risorsa
    risorsa = ""
    for kw, nome in _GRANTS_RISORSA.items():
        if kw in testo_low:
            risorsa = nome
            break
    if not risorsa:
        return ("", 0)

    # Estrai numero pezzatura
    testo_num = testo.replace(",", "").replace(".", "")
    m = re.search(r"(\d+)", testo_num)
    if not m:
        return (risorsa, 0)

    return (risorsa, int(m.group(1)))


def _leggi_pannello(ctx: TaskContext,
                    frame: np.ndarray) -> tuple[str, int, int]:
    """
    Legge il pannello destra dopo tap su un'icona.
    Ritorna (risorsa, pezzatura, owned).
    ('', 0, 0) se non leggibile o pack misto.
    """
    ox1 = _cfg(ctx, "PANNELLO_OWNED_X1")
    ox2 = _cfg(ctx, "PANNELLO_OWNED_X2")
    oy1 = _cfg(ctx, "PANNELLO_OWNED_Y1")
    oy2 = _cfg(ctx, "PANNELLO_OWNED_Y2")
    gx1 = _cfg(ctx, "PANNELLO_GRANTS_X1")
    gx2 = _cfg(ctx, "PANNELLO_GRANTS_X2")
    gy1 = _cfg(ctx, "PANNELLO_GRANTS_Y1")
    gy2 = _cfg(ctx, "PANNELLO_GRANTS_Y2")

    testo_owned  = _ocr_zona_testo(frame, ox1, oy1, ox2, oy2)
    testo_grants = _ocr_zona_testo(frame, gx1, gy1, gx2, gy2)

    owned = _parse_owned(testo_owned)
    risorsa, pezzatura = _parse_grants(testo_grants)

    return (risorsa, pezzatura, owned)


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
                f"[ZAINO] [{risorsa}]: {valore/1e6:.2f}M < target {tgt/1e6:.2f}M "
                f"→ carico (gap={gap/1e6:.3f}M)"
            )
            da_caricare[risorsa] = (valore, tgt)
        else:
            ctx.log_msg(
                f"[ZAINO] [{risorsa}]: {valore/1e6:.2f}M >= target "
                f"{tgt/1e6:.2f}M — ok"
            )
    return da_caricare


# ------------------------------------------------------------------------------
# SCAN + ESECUZIONE BAG
# ------------------------------------------------------------------------------

def _scan_ed_esegui(ctx: TaskContext,
                    gap_residui: dict[str, float],
                    dry_run: bool = False) -> dict[str, list[dict]]:
    """
    Scorre la griglia BAG riga per riga.
    Per ogni icona:
      - tap → OCR pannello destra → risorsa + pezzatura + owned
      - se risorsa da caricare e n > 0 → input quantità → USE
    Ritorna log delle operazioni eseguite per ogni risorsa.
    """
    col_x    = _cfg(ctx, "GRIGLIA_COL_X")
    riga_y   = _cfg(ctx, "GRIGLIA_RIGA_Y")
    n_col    = len(col_x)
    n_righe  = len(riga_y)

    campo_qty    = _cfg(ctx, "CAMPO_QTY")
    ok_tast      = _cfg(ctx, "OK_TASTIERA")
    use_btn      = _cfg(ctx, "USE_BUTTON")
    delay_icona  = _cfg(ctx, "DELAY_TAP_ICONA")
    delay_input  = _cfg(ctx, "DELAY_INPUT_QTY")
    delay_use    = _cfg(ctx, "DELAY_TAP_USE")
    delay_scroll = _cfg(ctx, "DELAY_SCROLL")

    operazioni: dict[str, list[dict]] = {r: [] for r in gap_residui}
    scroll_count = 0
    max_scroll   = 15
    icone_viste: set[tuple[str, int]] = set()  # (risorsa, pezzatura) già processate

    while scroll_count <= max_scroll:
        # Verifica se tutti i gap sono colmati
        if all(g <= 0 for g in gap_residui.values()):
            ctx.log_msg("[ZAINO] Tutti i gap colmati — STOP")
            break

        screen = ctx.device.screenshot()
        if screen is None:
            break
        frame = getattr(screen, "frame", None)
        if frame is None and isinstance(screen, np.ndarray):
            frame = screen
        if frame is None:
            break

        nuove_in_schermata = 0

        for i_riga, y in enumerate(riga_y):
            if y > frame.shape[0] - 20:
                continue

            for i_col, x in enumerate(col_x):
                if x > frame.shape[1] - 20:
                    continue

                # Tap icona
                ctx.log_msg(f"[ZAINO] tap icona ({x},{y})")
                ctx.device.tap(x, y)
                time.sleep(delay_icona)

                # Leggi pannello destra
                screen2 = ctx.device.screenshot()
                if screen2 is None:
                    continue
                frame2 = getattr(screen2, "frame", None)
                if frame2 is None and isinstance(screen2, np.ndarray):
                    frame2 = screen2
                if frame2 is None:
                    continue

                risorsa, pezzatura, owned = _leggi_pannello(ctx, frame2)

                if not risorsa or risorsa == "misto" or pezzatura <= 0:
                    ctx.log_msg(f"[ZAINO] ({x},{y}): skip (misto o non leggibile)")
                    continue

                ctx.log_msg(
                    f"[ZAINO] ({x},{y}): {risorsa} {pezzatura:,} owned={owned}"
                )

                # Icona già processata in scroll precedente → stiamo ciclando
                chiave = (risorsa, pezzatura)
                if chiave in icone_viste:
                    ctx.log_msg(f"[ZAINO] {risorsa} {pezzatura:,} già vista — fine scan")
                    return operazioni
                icone_viste.add(chiave)
                nuove_in_schermata += 1

                # Risorsa non da caricare → skip
                if risorsa not in gap_residui:
                    continue

                gap_r = gap_residui[risorsa]
                if gap_r <= 0:
                    ctx.log_msg(f"[ZAINO] [{risorsa}]: gap già colmato — skip")
                    continue

                if owned <= 0:
                    ctx.log_msg(f"[ZAINO] [{risorsa}] {pezzatura:,}: owned=0 — skip")
                    continue

                # Calcola quante usarne
                n = min(owned, int(gap_r // pezzatura))
                if n <= 0:
                    ctx.log_msg(
                        f"[ZAINO] [{risorsa}] {pezzatura:,}: "
                        f"pezzatura > gap residuo {gap_r/1e6:.3f}M — skip"
                    )
                    continue

                ctx.log_msg(
                    f"[ZAINO] [{risorsa}] {pezzatura:,}: "
                    f"uso {n} pezzi (gap={gap_r/1e6:.3f}M)"
                )

                if not dry_run:
                    # Tap campo quantità → cancella → inserisci n → OK → USE
                    ctx.device.tap(*campo_qty)
                    time.sleep(delay_input)
                    ctx.device.input_text(str(n))
                    time.sleep(delay_input)
                    ctx.device.tap(*ok_tast)
                    time.sleep(delay_input)
                    ctx.device.tap(*use_btn)
                    time.sleep(delay_use)
                else:
                    ctx.log_msg(
                        f"[ZAINO][DRY] [{risorsa}] {pezzatura:,}: "
                        f"SIMULAZIONE {n} pezzi = {n*pezzatura/1e6:.3f}M"
                    )

                # Aggiorna gap residuo
                gap_residui[risorsa] -= n * pezzatura
                operazioni[risorsa].append({
                    "pezzatura": pezzatura,
                    "n":         n,
                    "quantita":  n * pezzatura,
                })

                ctx.log_msg(
                    f"[ZAINO] [{risorsa}]: gap residuo = "
                    f"{gap_residui[risorsa]/1e6:.3f}M"
                )

        # Nessuna nuova icona → fine lista
        if nuove_in_schermata == 0:
            ctx.log_msg("[ZAINO] Nessuna nuova icona — fine griglia")
            break

        # Scroll giù per riga successiva
        ctx.device.swipe(480, 420, 480, 180, duration_ms=400)
        time.sleep(delay_scroll)
        scroll_count += 1

    return operazioni


# ------------------------------------------------------------------------------
# Task V6
# ------------------------------------------------------------------------------

class ZainoTask(Task):
    """
    Task settimanale (168h) che scarica risorse dal BAG al deposito.

    Algoritmo v4: scan griglia BAG + OCR pannello destra + input quantità preciso.
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
        Modalità simulazione: OCR + scan BAG + calcolo piano.
        Nessun tap USE viene eseguito.
        """
        return self._esegui(ctx, dry_run=True)

    def run(self, ctx: TaskContext,
            deposito: Optional[dict[str, float]] = None) -> TaskResult:
        """Esegue lo scarico zaino completo."""
        return self._esegui(ctx, dry_run=False, deposito=deposito)

    def _esegui(self,
                ctx: TaskContext,
                dry_run: bool = False,
                deposito: Optional[dict[str, float]] = None) -> TaskResult:

        modo = "[DRY] " if dry_run else ""

        if not _cfg(ctx, "ZAINO_ABILITATO"):
            ctx.log_msg(f"[ZAINO]{modo} modulo disabilitato — skip")
            return TaskResult(
                success=True,
                message="disabilitato",
                data={r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]},
            )

        # OCR PRE
        ctx.log_msg(f"[ZAINO]{modo} OCR deposito PRE-scarico...")
        if deposito is None:
            snapshot_pre = _ocr_deposito(ctx)
            if not snapshot_pre:
                ctx.log_msg(f"[ZAINO]{modo} Deposito non disponibile — skip")
                return TaskResult(
                    success=False,
                    message="deposito non disponibile",
                    data={r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]},
                )
        else:
            snapshot_pre = deposito

        ctx.log_msg(
            f"[ZAINO]{modo} PRE: "
            f"pomodoro={snapshot_pre.get('pomodoro',-1)/1e6:.2f}M "
            f"legno={snapshot_pre.get('legno',-1)/1e6:.2f}M "
            f"acciaio={snapshot_pre.get('acciaio',-1)/1e6:.2f}M "
            f"petrolio={snapshot_pre.get('petrolio',-1)/1e6:.2f}M"
        )

        # Calcola gap
        da_caricare = _calcola_gap(ctx, snapshot_pre)
        if not da_caricare:
            ctx.log_msg(f"[ZAINO]{modo} Tutte le risorse sopra soglia — nessun carico")
            return TaskResult(
                success=True,
                message="nessun carico necessario",
                data={r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]},
            )

        # Prepara gap_residui (modificabile durante scan)
        gap_residui = {
            risorsa: tgt - val
            for risorsa, (val, tgt) in da_caricare.items()
        }

        # Naviga BAG → RESOURCE
        tap_resource = _cfg(ctx, "TAP_BAG_RESOURCE")
        ctx.log_msg(f"[ZAINO]{modo} Apertura BAG via tap_barra...")
        ctx.navigator.tap_barra(ctx, "bag")
        time.sleep(_cfg(ctx, "DELAY_APRI_BAG"))

        ctx.log_msg(f"[ZAINO]{modo} tap RESOURCE {tap_resource}")
        ctx.device.tap(*tap_resource)
        time.sleep(1.0)

        esiti: dict[str, float] = {
            r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]
        }

        try:
            # Scan + esecuzione
            operazioni = _scan_ed_esegui(ctx, gap_residui, dry_run=dry_run)

            # Riepilogo operazioni
            for risorsa, ops in operazioni.items():
                if ops:
                    totale_ops = sum(o["quantita"] for o in ops) / 1e6
                    dettaglio = ", ".join(
                        f"{o['pezzatura']:,}×{o['n']}" for o in ops
                    )
                    ctx.log_msg(
                        f"[ZAINO]{modo} [{risorsa}]: {dettaglio} = {totale_ops:.3f}M"
                    )

            if not dry_run:
                # OCR POST
                time.sleep(_cfg(ctx, "DELAY_POST_SCARICO"))
                snapshot_post = _ocr_deposito(ctx)
                for risorsa, (val_pre, _) in da_caricare.items():
                    val_post = snapshot_post.get(risorsa, -1.0)
                    if val_post >= 0 and val_pre >= 0:
                        scaricato_reale = max(0.0, val_post - val_pre)
                        esiti[risorsa]  = scaricato_reale / 1e6
                        ctx.log_msg(
                            f"[ZAINO] [{risorsa}]: PRE={val_pre/1e6:.2f}M "
                            f"POST={val_post/1e6:.2f}M "
                            f"→ reale={scaricato_reale/1e6:.3f}M"
                        )
            else:
                # In dry-run stima dal piano
                for risorsa, ops in operazioni.items():
                    esiti[risorsa] = sum(o["quantita"] for o in ops) / 1e6

        except Exception as exc:
            ctx.log_msg(f"[ZAINO]{modo} Errore: {exc}")
            return TaskResult(
                success=False,
                message=f"errore: {exc}",
                data=esiti,
            )
        finally:
            # Torna HOME
            ctx.log_msg(f"[ZAINO]{modo} Torna HOME")
            ctx.navigator.vai_in_home()

        totale = sum(esiti.values())
        msg = f"{'[DRY] ' if dry_run else ''}scaricato {totale:.3f}M totale"
        ctx.log_msg(f"[ZAINO]{modo} Completato — {msg}")
        return TaskResult(
            success=True,
            message=msg,
            data=esiti,
        )
