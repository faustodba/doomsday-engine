# ==============================================================================
#  DOOMSDAY ENGINE V6 — tasks/raccolta.py                           Step 21
#
#  Invio squadre raccoglitrici ai nodi risorse sulla mappa.
#
#  FIX 12/04/2026:
#    - _leggi_coordinate_nodo: ctx.matcher.find() → ctx.matcher.find_one()
#    - _esegui_marcia: stessa correzione firma matcher (2 occorrenze)
#    - _invia_squadra: stessa correzione firma matcher (1 occorrenza)
#
#  UPGRADE 15/04/2026 — integrazione V5:
#    Step 1: OCR coordinate nodo reali (chiave "X_Y" invece di "tipo_campo")
#            → permette più squadre dello stesso tipo su nodi diversi
#            → tap lente coordinate (380,18) → OCR zone X/Y dal popup
#    Step 2: OCR ETA marcia dalla maschera invio pre-MARCIA
#            → TTL blacklist dinamico basato su distanza reale
#    Step 3: Conferma contatore post-marcia via leggi_contatore_slot()
#            → commit blacklist solo se contatore aumenta (marcia confermata)
#            → rollback automatico se marcia silenziosamente fallita
#    Step 4: Nodo fuori territorio → blacklist COMMITTED (non solo skip neutro)
#            → evita di ritentare lo stesso nodo fuori territorio
#    Step 5: Verifica livello nodo via OCR titolo popup ("Campo Lv.6")
#            → scarta e blacklista nodi sotto RACCOLTA_LIVELLO
#    Step 6: Blacklist statica su disco nodi fuori territorio
#            → file JSON per istanza in data/blacklist_fuori_{istanza}.json
#            → check pre-tap: se nodo già noto fuori territorio → skip immediato
#            → risparmio popup e BACK su nodi permanentemente fuori zona
#
#  FLUSSO AGGIORNATO:
#    0. Verifica abilitazione + slot liberi (iniettabile nei test)
#    1. Naviga in mappa
#    2. Loop: finché attive < obiettivo e fallimenti < MAX_FALLIMENTI:
#       a. Seleziona tipo dalla sequenza (allocation gap V5)
#       b. Cerca nodo (LENTE → tipo × 2 → livello → CERCA)
#       c. Tap nodo → verifica GATHER → OCR coordinate reali
#       d. Check blacklist statica fuori territorio (disco)
#       e. Check blacklist dinamica (RAM)
#       f. Verifica livello nodo via OCR
#       g. Verifica territorio → se fuori: blacklist statica + dinamica
#       h. RESERVED → _esegui_marcia (con OCR ETA)
#       i. Verifica contatore post-marcia → COMMITTED o rollback
#    3. Ritorna in home
#
#  COORDINATE DEFAULT (960x540):
#    TAP_LENTE              = (38, 325)    icona lente grande in mappa
#    TAP_LENTE_COORD        = (380, 18)    icona lente piccola per coordinate
#    TAP_NODO               = (480, 280)   centro nodo dopo CERCA
#    TAP_RACCOGLI           = (230, 390)   pulsante RACCOGLI nel popup nodo
#    TAP_SQUADRA            = (700, 185)   selezione squadra
#    TAP_MARCIA             = (727, 476)   pulsante MARCIA
#    NODO_TITOLO_ZONA       = (250,150,720,185)  OCR livello nodo
#    OCR_COORD_ZONA_X       = (430,125,530,155)  OCR coordinata X popup lente
#    OCR_COORD_ZONA_Y       = (535,125,635,155)  OCR coordinata Y popup lente
#    OCR_ETA_ZONA           = (580,440,780,470)  OCR timer ETA marcia
#
#  CONFIG (ctx.config — chiavi con fallback ai default):
#    RACCOLTA_ABILITATA          bool   default True
#    RACCOLTA_SEQUENZA           list   default ["campo","segheria","petrolio","acciaio"]
#    RACCOLTA_OBIETTIVO          int    default 4
#    RACCOLTA_MAX_FALLIMENTI     int    default 3
#    RACCOLTA_TRUPPE             int    default 0
#    RACCOLTA_LIVELLO            int    default 6
#    RACCOLTA_LIVELLO_MIN        int    default 6  (scarta nodi sotto questo livello)
#    BLACKLIST_COMMITTED_TTL     int    default 120
#    BLACKLIST_RESERVED_TTL      int    default 45
#    BLACKLIST_ATTESA_NODO       int    default 120
#    BLACKLIST_FUORI_DIR         str    default "data"
#    ETA_MARGINE_S               int    default 5  (margine su ETA per TTL)
#    ETA_MIN_S                   int    default 8  (ETA minima accettabile)
#    ETA_MAX_S                   int    default 600 (oltre: valore anomalo OCR)
# ==============================================================================

from __future__ import annotations

import json
import math as _math
import os
import re as _re
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

from core.task import Task, TaskContext, TaskResult

# ------------------------------------------------------------------------------
# Default costanti
# ------------------------------------------------------------------------------

_DEFAULTS: dict = {
    # Coordinate UI (960x540)
    "TAP_LENTE":            (38,  325),
    "TAP_LENTE_COORD":      (380,  18),   # lente piccola → popup coordinate X/Y
    "TAP_NODO":             (480, 280),
    "TAP_RACCOGLI":         (230, 390),
    "TAP_SQUADRA":          (700, 185),
    "TAP_MARCIA":           (727, 476),
    "TAP_CANCELLA":         (527, 469),
    "TAP_CAMPO_TESTO":      (748,  75),
    "TAP_OK_TASTIERA":      (480, 380),
    # Icone tipo risorsa nella lente
    "TAP_ICONA_TIPO": {
        "campo":    (410, 450),
        "segheria": (535, 450),
        "acciaio":  (672, 490),
        "petrolio": (820, 490),
    },
    # Coordinate livello per tipo
    "COORD_LIVELLO": {
        "campo":    {"meno": (294, 295), "piu": (519, 293), "search": (413, 352)},
        "segheria": {"meno": (419, 295), "piu": (644, 293), "search": (538, 352)},
        "acciaio":  {"meno": (556, 295), "piu": (781, 293), "search": (675, 352)},
        "petrolio": {"meno": (701, 295), "piu": (890, 293), "search": (791, 352)},
    },
    # Template verifica tipo selezionato nella lente
    "TMPL_TIPO": {
        "campo":    "pin/pin_field.png",
        "segheria": "pin/pin_sawmill.png",
        "acciaio":  "pin/pin_steel_mill.png",
        "petrolio": "pin/pin_oil_refinery.png",
    },
    "SOGLIA_TIPO":          0.85,
    "ROI_LENTE":            (350, 460, 870, 540),
    # Template gather + marcia + enter coordinates
    "TEMPLATE_GATHER":      "pin/pin_gather.png",
    "ROI_GATHER":           (60, 350, 420, 420),
    "TEMPLATE_MARCIA":      "pin/pin_march.png",
    "TEMPLATE_ENTER":       "pin/pin_enter.png",   # popup "Enter coordinates"
    "ROI_ENTER":            (300,  85, 700, 125),
    "TEMPLATE_SOGLIA":      0.75,
    # OCR coordinate nodo — zona popup lente piccola (V5 ocr.py)
    "OCR_COORD_ZONA_X":     (430, 125, 530, 155),
    "OCR_COORD_ZONA_Y":     (535, 125, 635, 155),
    # OCR livello nodo — titolo popup (V5 raccolta.py)
    "NODO_TITOLO_ZONA":     (250, 150, 720, 185),
    # OCR ETA marcia — zona timer nella maschera invio (V5 config.py)
    "OCR_ETA_ZONA":         (580, 440, 780, 470),
    "ETA_MARGINE_S":        5,
    "ETA_MIN_S":            8,
    "ETA_MAX_S":            600,
    # Logica raccolta
    "RACCOLTA_ABILITATA":       True,
    "RACCOLTA_SEQUENZA":        ["campo", "segheria", "petrolio", "acciaio"],
    "RACCOLTA_OBIETTIVO":       4,
    "RACCOLTA_MAX_FALLIMENTI":  3,
    "RACCOLTA_TRUPPE":          0,
    "RACCOLTA_LIVELLO":         6,
    "RACCOLTA_LIVELLO_MIN":     6,
    # Blacklist
    "BLACKLIST_COMMITTED_TTL":  120,
    "BLACKLIST_RESERVED_TTL":   45,
    "BLACKLIST_ATTESA_NODO":    120,
    "BLACKLIST_FUORI_DIR":      "data",
    # Ritardi
    "DELAY_POST_MARCIA":        2.0,
    "DELAY_CERCA":              1.5,
}

_TUTTI_I_TIPI = ["campo", "segheria", "petrolio", "acciaio"]


def _cfg(ctx: TaskContext, key: str):
    return ctx.config.get(key, _DEFAULTS[key])


# ==============================================================================
# Allocation — logica gap V5 allocation.py
# ==============================================================================

_RATIO_TARGET_DEFAULT = {
    "campo":    0.3500,
    "segheria": 0.3500,
    "petrolio": 0.1875,
    "acciaio":  0.1125,
}
_TIPO_TO_RISORSA = {
    "campo":    "pomodoro",
    "segheria": "legno",
    "petrolio": "petrolio",
    "acciaio":  "acciaio",
}
_SOGLIA_OCR_MIN = 100_000


def _calcola_sequenza_allocation(slot_liberi: int, deposito: dict,
                                  ratio_target: dict | None = None) -> list[str]:
    if slot_liberi <= 0:
        return []
    ratio = ratio_target or _RATIO_TARGET_DEFAULT
    valori = {}
    for tipo, risorsa in _TIPO_TO_RISORSA.items():
        v = deposito.get(risorsa, -1)
        valori[tipo] = float(v) if (v is not None and v >= _SOGLIA_OCR_MIN) else 0.0
    totale = sum(valori.values())
    if totale < 1_000:
        base = ["campo", "segheria", "petrolio", "campo", "segheria",
                "acciaio", "campo", "segheria", "petrolio", "campo",
                "segheria", "acciaio", "campo", "segheria", "petrolio", "campo"]
        return base[:slot_liberi]
    perc_att = {t: valori[t] / totale for t in ratio}
    gap      = {t: ratio[t] - perc_att[t] for t in ratio}
    tipi_ord = sorted(gap.keys(), key=lambda t: gap[t], reverse=True)
    cap      = max(1, _math.floor(slot_liberi / 2))
    contatori = {t: 0 for t in ratio}
    sequenza  = []
    for tipo in tipi_ord:
        if len(sequenza) >= slot_liberi:
            break
        if gap[tipo] > 0:
            gap_pos_tot = max(sum(g for g in gap.values() if g > 0), 0.001)
            peso = gap[tipo] / gap_pos_tot
            n = min(cap, max(1, round(peso * slot_liberi)), slot_liberi - len(sequenza))
            for _ in range(n):
                if len(sequenza) < slot_liberi:
                    sequenza.append(tipo)
                    contatori[tipo] += 1
    idx = 0
    safety = 0
    while len(sequenza) < slot_liberi:
        tipo = tipi_ord[idx % len(tipi_ord)]
        if contatori[tipo] < cap:
            sequenza.append(tipo)
            contatori[tipo] += 1
        idx += 1
        safety += 1
        if safety > len(tipi_ord) * slot_liberi * 2:
            cap = slot_liberi
            safety = 0
    return sequenza[:slot_liberi]


# Verifica territorio alleanza — pixel check V5
_TERRITORIO_BUFF_ZONA = (250, 340, 420, 370)
_TERRITORIO_SOGLIA_PX = 20


# ==============================================================================
# Blacklist dinamica RAM — RESERVED/COMMITTED con TTL
# ==============================================================================

class Blacklist:
    """
    Blacklist nodi con stati RESERVED / COMMITTED e TTL indipendenti.
    Chiave: "X_Y" (coordinate reali OCR) — permette più squadre stesso tipo.
    """

    def __init__(self, committed_ttl: int = 120, reserved_ttl: int = 45):
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.committed_ttl = committed_ttl
        self.reserved_ttl  = reserved_ttl

    def _pulisci(self) -> None:
        ora = time.time()
        scaduti = [k for k, v in self._data.items()
                   if ora - v.get("ts", 0) > (
                       self.committed_ttl if v.get("state") == "COMMITTED"
                       else self.reserved_ttl)]
        for k in scaduti:
            del self._data[k]

    def contiene(self, chiave: str) -> bool:
        if not chiave:
            return False
        with self._lock:
            self._pulisci()
            return chiave in self._data

    def reserve(self, chiave: str) -> None:
        if not chiave:
            return
        with self._lock:
            self._data[chiave] = {"ts": time.time(), "state": "RESERVED", "eta_s": None}

    def commit(self, chiave: str, eta_s: Optional[float] = None) -> None:
        if not chiave:
            return
        with self._lock:
            self._data[chiave] = {"ts": time.time(), "state": "COMMITTED", "eta_s": eta_s}

    def rollback(self, chiave: str) -> None:
        if not chiave:
            return
        with self._lock:
            self._data.pop(chiave, None)

    def get_eta(self, chiave: str) -> Optional[float]:
        with self._lock:
            v = self._data.get(chiave)
            return v.get("eta_s") if isinstance(v, dict) else None

    def get_state(self, chiave: str) -> Optional[str]:
        with self._lock:
            v = self._data.get(chiave)
            return v.get("state") if isinstance(v, dict) else None

    def snapshot(self) -> dict:
        with self._lock:
            self._pulisci()
            return dict(self._data)

    def __len__(self) -> int:
        with self._lock:
            self._pulisci()
            return len(self._data)


# ==============================================================================
# Step 6 — Blacklist statica su disco: nodi fuori territorio
# ==============================================================================

class BlacklistFuori:
    """
    Blacklist persistente su disco dei nodi fuori territorio.
    File: {BLACKLIST_FUORI_DIR}/blacklist_fuori_globale.json
    Formato: {"X_Y": {"ts": float, "tipo": str}}
    Nessun TTL — i nodi fuori territorio sono permanenti (la mappa non cambia).
    Globale: condivisa tra tutte le istanze (stesso server/mappa).
    Thread-safe tramite lock.
    """

    def __init__(self, data_dir: str = "data"):
        self._lock = threading.Lock()
        path = Path(data_dir)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        path.mkdir(parents=True, exist_ok=True)
        self._path = path / "blacklist_fuori_globale.json"
        self._data: dict[str, dict] = self._carica()

    def _carica(self) -> dict:
        try:
            if self._path.exists():
                return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _salva(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass

    def contiene(self, chiave: str) -> bool:
        if not chiave:
            return False
        with self._lock:
            return chiave in self._data

    def aggiungi(self, chiave: str, tipo: str) -> None:
        if not chiave:
            return
        with self._lock:
            self._data[chiave] = {"ts": time.time(), "tipo": tipo}
            self._salva()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


# ==============================================================================
# Selezione sequenza risorse
# ==============================================================================

def _interleave(sequenza: list) -> list:
    """
    Trasforma una sequenza con tipi consecutivi uguali in una sequenza
    interleaved che alterna i tipi il più possibile.

    Algoritmo greedy: ad ogni posizione sceglie il tipo con più occorrenze
    rimanenti che NON sia uguale all'ultimo inserito.

    Esempi:
      [campo, campo, petrolio, petrolio] → [petrolio, campo, petrolio, campo]
      [campo, campo, campo, segheria]    → [campo, segheria, campo, campo]
      [campo, campo, campo, campo]       → invariata (impossibile alternare)

    Motivazione: evita di inviare due squadre consecutive dello stesso tipo
    riducendo l'attesa sul nodo (il gioco propone lo stesso nodo finché non
    è fisicamente occupato — con l'alternanza il nodo è già occupato quando
    ci si ritorna).
    """
    from collections import Counter
    if not sequenza:
        return []
    conteggi = Counter(sequenza)
    risultato = []
    ultimo = None
    for _ in range(len(sequenza)):
        candidati = [(cnt, tipo) for tipo, cnt in conteggi.items()
                     if cnt > 0 and tipo != ultimo]
        if not candidati:
            candidati = [(cnt, tipo) for tipo, cnt in conteggi.items() if cnt > 0]
        _, scelto = max(candidati)
        risultato.append(scelto)
        conteggi[scelto] -= 1
        ultimo = scelto
    return risultato


def _calcola_sequenza(obiettivo: int, sequenza_base: list[str],
                       tipi_bloccati: set[str]) -> list[str]:
    disponibili = [t for t in sequenza_base if t not in tipi_bloccati]
    if not disponibili:
        disponibili = [t for t in _TUTTI_I_TIPI if t not in tipi_bloccati]
    if not disponibili:
        return []
    n = max(obiettivo * 3, 10)
    return (disponibili * (n // len(disponibili) + 1))[:n]


# ==============================================================================
# Operazioni UI
# ==============================================================================

def _nodo_in_territorio(screen, tipo: str, ctx: TaskContext) -> bool:
    """Pixel check V5: popup nodo mostra buff territorio (+30%)? Fail-safe True."""
    try:
        frame = getattr(screen, "frame", None)
        if frame is None:
            return True
        x1, y1, x2, y2 = _TERRITORIO_BUFF_ZONA
        zona = frame[y1:y2, x1:x2, :3].astype(int)
        r, g, b = zona[:, :, 0], zona[:, :, 1], zona[:, :, 2]
        verdi = (g > 140) & (g > r * 1.4) & (g > b * 1.3) & ((g - r) > 40)
        n_verdi = int(verdi.sum())
        in_territorio = n_verdi >= _TERRITORIO_SOGLIA_PX
        ctx.log_msg(f"Raccolta [{tipo}]: territorio pixel_verdi={n_verdi} "
                    f"(soglia={_TERRITORIO_SOGLIA_PX}) → {'IN' if in_territorio else 'FUORI'}")
        return in_territorio
    except Exception:
        return True


def _verifica_tipo(ctx: TaskContext, tipo: str) -> bool:
    """Verifica visiva che il tipo sia selezionato nel pannello lente."""
    tmpl_tipo = _cfg(ctx, "TMPL_TIPO").get(tipo)
    if not tmpl_tipo:
        return True
    soglia = _cfg(ctx, "SOGLIA_TIPO")
    roi    = _cfg(ctx, "ROI_LENTE")
    time.sleep(0.5)
    ctx.device.screenshot()          # flush frame cached
    time.sleep(0.2)
    screen = ctx.device.screenshot() # frame live
    if not screen:
        return True
    r = ctx.matcher.find_one(screen, tmpl_tipo, threshold=soglia, zone=roi)
    ctx.log_msg(f"Raccolta: [VERIFICA] tipo {tipo} score={r.score:.3f} → "
                f"{'OK' if r.found else 'NON selezionato'}")
    return r.found


def _cerca_nodo(ctx: TaskContext, tipo: str,
                livello_override: int = 0) -> bool:
    """
    LENTE → tap tipo × 2 → verifica tipo → livello → CERCA.
    Ritorna True se CERCA eseguita correttamente.
    Se livello_override > 0 sovrascrive il livello di default.
    """
    tap_lente   = _cfg(ctx, "TAP_LENTE")
    coord_lv    = _cfg(ctx, "COORD_LIVELLO").get(tipo, _cfg(ctx, "COORD_LIVELLO")["campo"])
    # Livello nodo dall'istanza (instances.json → livello), fallback a RACCOLTA_LIVELLO
    livello     = max(1, min(7, int(ctx.config.get("livello", _cfg(ctx, "RACCOLTA_LIVELLO")))))
    if livello_override > 0:
        livello = max(1, min(7, livello_override))
    delay_cerca = _cfg(ctx, "DELAY_CERCA")
    tap_icona   = _cfg(ctx, "TAP_ICONA_TIPO").get(tipo, _cfg(ctx, "TAP_ICONA_TIPO")["campo"])

    ctx.log_msg(f"Raccolta: LENTE → {tipo} Lv.{livello}")
    ctx.device.tap(tap_lente)
    time.sleep(0.8)

    ctx.device.tap(tap_icona)
    ctx.device.tap(tap_icona)
    time.sleep(1.2)

    if not _verifica_tipo(ctx, tipo):
        ctx.log_msg(f"Raccolta: tipo {tipo} NON selezionato — retry tap icona")
        ctx.device.tap(tap_icona)
        time.sleep(1.5)
        if not _verifica_tipo(ctx, tipo):
            ctx.log_msg(f"Raccolta: tipo {tipo} ancora NON selezionato — reset pannello")
            ctx.device.key("KEYCODE_BACK")
            time.sleep(2.0)
            ctx.device.tap(tap_lente)
            time.sleep(0.8)
            ctx.device.tap(tap_icona)
            ctx.device.tap(tap_icona)
            time.sleep(1.5)
            if not _verifica_tipo(ctx, tipo):
                ctx.log_msg(f"Raccolta: tipo {tipo} NON selezionato dopo reset — abort")
                ctx.device.key("KEYCODE_BACK")
                time.sleep(0.5)
                return False

    for _ in range(7):
        ctx.device.tap(coord_lv["meno"])
        time.sleep(0.15)
    time.sleep(0.3)
    for _ in range(livello - 1):
        ctx.device.tap(coord_lv["piu"])
        time.sleep(0.2)

    ctx.device.tap(coord_lv["search"])
    time.sleep(delay_cerca)
    ctx.log_msg(f"Raccolta: CERCA eseguita per {tipo} Lv.{livello}")
    return True


def _cerca_nodo_con_fallback(ctx: TaskContext, tipo: str) -> tuple[bool, int]:
    """
    Tenta la ricerca nodo con sequenza livelli: 7 → livello_default → 5.
    Deduplicati e ordinati dal più alto al più basso.
    Ritorna (trovato, livello_usato). livello_usato=0 se fallisce tutto.
    """
    livello_base = max(1, min(7, int(
        ctx.config.get("livello", _cfg(ctx, "RACCOLTA_LIVELLO"))
    )))

    # Sequenza: 7, livello_base (se diverso da 7 e 5), 5
    # Deduplicata e ordinata dal più alto al più basso
    candidati = sorted(set([7, livello_base, 5]), reverse=True)
    # Rimuovi livelli fuori range
    candidati = [lv for lv in candidati if 1 <= lv <= 7]

    for lv in candidati:
        ctx.log_msg(f"Raccolta: tentativo CERCA {tipo} Lv.{lv}")
        ok = _cerca_nodo(ctx, tipo, livello_override=lv)
        if ok:
            return True, lv
        # Se _cerca_nodo fallisce per tipo NON selezionato,
        # non ha senso ritentare con altro livello — abort
        # _cerca_nodo ritorna False solo per tipo NON selezionato
        # In quel caso usciamo subito
        ctx.log_msg(f"Raccolta: CERCA {tipo} Lv.{lv} fallita — "
                    f"tipo NON selezionato, abort sequenza")
        return False, 0

    return False, 0


# ==============================================================================
# Step 1 — OCR coordinate nodo reali (V5 ocr.py → _ocr_box + _leggi_coord_nodo)
# ==============================================================================

def _ocr_coord_box(frame, zona: tuple) -> Optional[int]:
    """
    OCR su una zona del frame per leggere coordinata numerica (3-4 cifre).
    Tradotto da V5 ocr._ocr_box().
    """
    try:
        import pytesseract
        import os
        from PIL import Image
        pytesseract.pytesseract.tesseract_cmd = os.environ.get(
            "TESSERACT_EXE",
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        )
        x1, y1, x2, y2 = zona
        roi = frame[y1:y2, x1:x2]
        import cv2
        big  = cv2.resize(roi, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        pil = Image.fromarray(thresh)
        testo = pytesseract.image_to_string(
            pil,
            config="--psm 7 -c tessedit_char_whitelist=0123456789XY:#. "
        ).strip()
        numeri = _re.findall(r'\d{3,4}', testo)
        return int(numeri[0]) if numeri else None
    except Exception:
        return None


def _leggi_coord_nodo(ctx: TaskContext) -> Optional[str]:
    """
    Step 1: tap lente coordinate (380,18) → verifica popup → OCR X/Y.
    Ritorna chiave "X_Y" (es. "712_535") oppure None se OCR fallisce.
    Tradotto da V5 raccolta._leggi_coord_nodo() + ocr.leggi_coordinate_nodo_mem().
    """
    tap_lente_coord = _cfg(ctx, "TAP_LENTE_COORD")
    tmpl_enter      = _cfg(ctx, "TEMPLATE_ENTER")
    roi_enter       = _cfg(ctx, "ROI_ENTER")
    soglia          = _cfg(ctx, "TEMPLATE_SOGLIA")
    zona_x          = _cfg(ctx, "OCR_COORD_ZONA_X")
    zona_y          = _cfg(ctx, "OCR_COORD_ZONA_Y")

    time.sleep(1.5)

    # Tap lente coordinata + verifica popup aperto
    ctx.device.tap(tap_lente_coord)
    time.sleep(1.3)

    screen = ctx.device.screenshot()
    if screen is None:
        return None

    try:
        enter_ok = ctx.matcher.find_one(screen, tmpl_enter,
                                         threshold=soglia, zone=roi_enter)
        if not enter_ok.found:
            ctx.log_msg("[COORD] pin_enter NON visibile — retry tap lente coord")
            ctx.device.tap(tap_lente_coord)
            time.sleep(1.3)
            screen = ctx.device.screenshot()
            if screen is None:
                return None
            enter_ok2 = ctx.matcher.find_one(screen, tmpl_enter,
                                              threshold=soglia, zone=roi_enter)
            if not enter_ok2.found:
                ctx.log_msg("[COORD] ANOMALIA: pin_enter ancora non visibile — OCR potrebbe fallire")
        else:
            ctx.log_msg(f"[COORD] pin_enter score={enter_ok.score:.3f} — OK")
    except FileNotFoundError:
        ctx.log_msg("[COORD] pin_enter.png non trovato — procedo senza verifica")

    frame = getattr(screen, "frame", None)
    if frame is None:
        return None

    cx = _ocr_coord_box(frame, zona_x)
    cy = _ocr_coord_box(frame, zona_y)

    # Retry se una coordinata non letta
    if cx is None or cy is None:
        time.sleep(0.6)
        screen2 = ctx.device.screenshot()
        if screen2 is not None:
            frame2 = getattr(screen2, "frame", None)
            if frame2 is not None:
                if cx is None:
                    cx = _ocr_coord_box(frame2, zona_x)
                if cy is None:
                    cy = _ocr_coord_box(frame2, zona_y)

    # Fallback cx: se Y leggibile ma X no, usa centro mappa (V5 pattern)
    if cx is None and cy is not None:
        cx = 690
        ctx.log_msg(f"[COORD] cx fallback=690 cy={cy}")

    if cx is not None and cy is not None:
        chiave = f"{cx}_{cy}"
        ctx.log_msg(f"[COORD] coordinate nodo: ({cx},{cy}) → chiave={chiave}")
        return chiave

    ctx.log_msg("[COORD] OCR coordinate fallito — procedo senza chiave")
    return None


# ==============================================================================
# Step 5 — OCR livello nodo dal titolo popup (V5 raccolta._leggi_livello_nodo_da_img)
# ==============================================================================

def _leggi_livello_nodo(ctx: TaskContext, screen) -> int:
    """
    Step 5: legge il livello del nodo dal titolo del popup (es. "Campo Lv.6" → 6).
    Ritorna int >= 1 se leggibile, -1 se OCR fallisce (fail-safe: non scarta).
    Tradotto da V5 raccolta._leggi_livello_nodo_da_img().
    """
    try:
        import pytesseract
        import os
        from PIL import Image
        pytesseract.pytesseract.tesseract_cmd = os.environ.get(
            "TESSERACT_EXE",
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        )
        frame = getattr(screen, "frame", None)
        if frame is None:
            return -1
        x1, y1, x2, y2 = _cfg(ctx, "NODO_TITOLO_ZONA")
        roi = frame[y1:y2, x1:x2]
        import cv2
        pil = Image.fromarray(roi[:, :, ::-1])
        w, h = pil.size
        big = pil.resize((w * 4, h * 4), Image.LANCZOS)
        bw  = big.convert("L").point(lambda p: 255 if p > 130 else 0)
        cfg = ("--psm 7 -c tessedit_char_whitelist="
               "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789. ")
        testo = pytesseract.image_to_string(bw, config=cfg).strip()
        m = _re.search(r'[Ll][Vv]\.?\s*(\d+)', testo)
        return int(m.group(1)) if m else -1
    except Exception:
        return -1


# ==============================================================================
# Step 2 — OCR ETA marcia dalla maschera invio (V5 ocr.leggi_eta_marcia_mem)
# ==============================================================================

_ETA_RE = _re.compile(
    r"(?:(\d+)\s*:\s*(\d{2})\s*:\s*(\d{2}))|(?:(\d{1,2})\s*:\s*(\d{2}))"
)


def _parse_eta_secondi(testo: str) -> Optional[int]:
    """Parsa 'H:MM:SS' o 'MM:SS' in secondi. Ritorna None se non leggibile."""
    if not testo:
        return None
    t = testo.strip().replace(' ', '').replace('O', '0').replace('o', '0')
    m = _ETA_RE.search(t)
    if not m:
        return None
    if m.group(1) is not None:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    return int(m.group(4)) * 60 + int(m.group(5))


def _leggi_eta_marcia(ctx: TaskContext, screen) -> Optional[int]:
    """
    Step 2: OCR timer ETA dalla maschera invio pre-MARCIA.
    Ritorna secondi (int) oppure None se non leggibile.
    Tradotto da V5 ocr.leggi_eta_marcia_mem() + _leggi_eta_marcia_da_img().
    """
    try:
        import pytesseract
        import os
        from PIL import Image, ImageFilter, ImageEnhance, ImageOps
        pytesseract.pytesseract.tesseract_cmd = os.environ.get(
            "TESSERACT_EXE",
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        )
        frame = getattr(screen, "frame", None)
        if frame is None:
            return None
        x1, y1, x2, y2 = _cfg(ctx, "OCR_ETA_ZONA")
        roi = frame[y1:y2, x1:x2]
        pil = Image.fromarray(roi[:, :, ::-1])
        w, h = pil.size
        # Preprocessa: scala grigi + contrasto + mediana + upscale + soglia
        img2 = pil.convert('L')
        img2 = ImageEnhance.Contrast(img2).enhance(2.3)
        img2 = img2.filter(ImageFilter.MedianFilter(size=3))
        img2 = img2.resize((w * 4, h * 4), Image.LANCZOS)
        img2 = img2.point(lambda p: 255 if p > 140 else 0)
        cfg  = "--psm 6 -c tessedit_char_whitelist=0123456789:"
        t1   = pytesseract.image_to_string(img2, config=cfg).strip()
        sec  = _parse_eta_secondi(t1)
        if sec is not None:
            return sec
        # Prova invertita
        inv = ImageOps.invert(img2)
        inv = inv.point(lambda p: 255 if p > 140 else 0)
        t2  = pytesseract.image_to_string(inv, config=cfg).strip()
        return _parse_eta_secondi(t2)
    except Exception:
        return None


# ==============================================================================
# Step 3 — Conferma contatore post-marcia
# ==============================================================================

def _leggi_attive_post_marcia(ctx: TaskContext, obiettivo: int,
                               retry: int = 3, sleep_s: float = 1.5) -> int:
    """
    Step 3: legge il contatore slot dopo la marcia con retry.
    Ritorna attive (int >= 0) oppure -1 se OCR fallisce.
    Tradotto da V5 raccolta._leggi_attive_con_retry().
    """
    try:
        from shared.ocr_helpers import leggi_contatore_slot
    except ImportError:
        return -1

    for i in range(retry):
        screen = ctx.device.screenshot()
        if screen is None:
            time.sleep(sleep_s)
            continue
        attive, totale = leggi_contatore_slot(screen, totale_noto=obiettivo)
        if attive >= 0:
            return attive
        ctx.log_msg(f"[POST-MARCIA] OCR contatore N/D (tentativo {i+1}/{retry})")
        time.sleep(sleep_s)
    return -1


# ==============================================================================
# Sequenza UI principale
# ==============================================================================

def _tap_nodo_e_verifica_gather(ctx: TaskContext, tipo: str) -> str:
    """
    Tap nodo → verifica GATHER visibile.
    Ritorna "ok" | "fuori" | "errore".
    NON verifica territorio — viene fatto in _invia_squadra dopo OCR coordinate.
    """
    tap_nodo        = _cfg(ctx, "TAP_NODO")
    template_gather = _cfg(ctx, "TEMPLATE_GATHER")
    soglia          = _cfg(ctx, "TEMPLATE_SOGLIA")
    roi_gather      = _cfg(ctx, "ROI_GATHER")

    ctx.log_msg(f"Raccolta [{tipo}]: tap nodo {tap_nodo}")
    ctx.device.tap(tap_nodo)
    time.sleep(1.0)

    screen = ctx.device.screenshot()
    if not screen:
        return "errore"

    r = ctx.matcher.find_one(screen, template_gather, threshold=soglia, zone=roi_gather)
    ctx.log_msg(f"Raccolta [{tipo}]: pin_gather score={r.score:.3f} → "
                f"{'OK' if r.found else 'NON trovato'}")

    if not r.found:
        ctx.log_msg(f"Raccolta [{tipo}]: GATHER non visibile — retry tap nodo")
        ctx.device.tap(tap_nodo)
        time.sleep(1.5)
        screen2 = ctx.device.screenshot()
        if screen2:
            r2 = ctx.matcher.find_one(screen2, template_gather, threshold=soglia, zone=roi_gather)
            ctx.log_msg(f"Raccolta [{tipo}]: pin_gather retry score={r2.score:.3f} → "
                        f"{'OK' if r2.found else 'NON trovato'}")
            if r2.found:
                screen = screen2
            else:
                ctx.device.key("KEYCODE_BACK")
                time.sleep(0.5)
                return "errore"
        else:
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.5)
            return "errore"

    return "gather_ok", screen   # type: ignore  — ritorna anche screen per uso successivo


def _esegui_marcia(ctx: TaskContext, n_truppe: int,
                   screen_maschera=None) -> tuple[bool, Optional[int]]:
    """
    Sequenza UI: RACCOGLI → SQUADRA → (truppe) → OCR ETA → MARCIA.
    Ritorna (ok, eta_s).
    Step 2: OCR ETA dalla maschera pre-MARCIA.
    """
    tap_raccogli    = _cfg(ctx, "TAP_RACCOGLI")
    tap_squadra     = _cfg(ctx, "TAP_SQUADRA")
    tap_marcia      = _cfg(ctx, "TAP_MARCIA")
    tap_cancella    = _cfg(ctx, "TAP_CANCELLA")
    tap_campo       = _cfg(ctx, "TAP_CAMPO_TESTO")
    tap_ok          = _cfg(ctx, "TAP_OK_TASTIERA")
    template_marcia = _cfg(ctx, "TEMPLATE_MARCIA")
    soglia          = _cfg(ctx, "TEMPLATE_SOGLIA")
    eta_max         = _cfg(ctx, "ETA_MAX_S")

    ctx.log_msg("Raccolta: RACCOGLI → SQUADRA")
    ctx.device.tap(tap_raccogli)
    time.sleep(0.5)
    ctx.device.tap(tap_squadra)
    time.sleep(1.4)

    # Verifica maschera invio aperta
    screen = ctx.device.screenshot()
    if screen:
        maschera = ctx.matcher.find_one(screen, template_marcia, threshold=soglia)
        if maschera.found:
            ctx.log_msg(f"Raccolta: maschera invio aperta score={maschera.score:.3f} → OK")
        else:
            ctx.log_msg(f"Raccolta: maschera NON aperta score={maschera.score:.3f} — retry")
            ctx.device.tap(tap_squadra)
            time.sleep(1.8)
            screen = ctx.device.screenshot()
            if screen:
                m2 = ctx.matcher.find_one(screen, template_marcia, threshold=soglia)
                if not m2.found:
                    ctx.log_msg("Raccolta: maschera ancora non aperta — FALLITO")
                    return False, None
                ctx.log_msg(f"Raccolta: maschera aperta al retry score={m2.score:.3f} → OK")

    # Step 2: OCR ETA dalla maschera (screen appena acquisito)
    eta_s: Optional[int] = None
    if screen is not None:
        eta_raw = _leggi_eta_marcia(ctx, screen)
        if eta_raw is not None and eta_raw <= eta_max:
            eta_s = eta_raw
            ctx.log_msg(f"Raccolta: ETA marcia={eta_s}s ({eta_s//60}m{eta_s%60:02d}s)")
        elif eta_raw is not None:
            ctx.log_msg(f"Raccolta: ETA={eta_raw}s anomalo (>{eta_max}s) — ignorato")
        else:
            ctx.log_msg("Raccolta: ETA marcia non leggibile")

    # Imposta truppe
    if n_truppe and n_truppe > 0:
        ctx.log_msg(f"Raccolta: imposta truppe={n_truppe}")
        ctx.device.tap(tap_cancella)
        time.sleep(0.4)
        ctx.device.tap(tap_campo)
        time.sleep(0.4)
        ctx.device.key("KEYCODE_CTRL_A")
        time.sleep(0.15)
        ctx.device.key("KEYCODE_DEL")
        time.sleep(0.15)
        ctx.device.input_text(str(n_truppe))
        time.sleep(0.25)
        ctx.device.tap(tap_ok)
        time.sleep(0.25)

    ctx.log_msg("Raccolta: tap MARCIA")
    ctx.device.tap(tap_marcia)
    time.sleep(0.8)

    # Verifica maschera chiusa
    screen_post = ctx.device.screenshot()
    if screen_post:
        maschera_post = ctx.matcher.find_one(screen_post, template_marcia, threshold=soglia)
        if maschera_post.found:
            ctx.log_msg(f"Raccolta: maschera ancora aperta score={maschera_post.score:.3f} — retry")
            ctx.device.tap(tap_marcia)
            time.sleep(1.0)
            screen_post2 = ctx.device.screenshot()
            if screen_post2:
                m_post2 = ctx.matcher.find_one(screen_post2, template_marcia, threshold=soglia)
                if m_post2.found:
                    ctx.log_msg("Raccolta: maschera ancora aperta dopo retry — FALLITO")
                    return False, eta_s
        else:
            ctx.log_msg(f"Raccolta: maschera chiusa score={maschera_post.score:.3f} → marcia OK")

    return True, eta_s


def _invia_squadra(ctx: TaskContext, tipo: str,
                   blacklist: Blacklist,
                   blacklist_fuori: BlacklistFuori,
                   cooldown_map: dict,
                   n_truppe: int,
                   tipi_bloccati: set,
                   obiettivo: int) -> tuple[bool, bool, bool]:
    """
    Cerca nodo, verifica blacklist, invia marcia.

    Integra Step 1-5:
      - Step 1: OCR coordinate reali → chiave "X_Y"
      - Step 4+6: nodo fuori territorio → blacklist statica + dinamica
      - Step 5: verifica livello nodo → scarta se sotto soglia
      - Step 2: ETA marcia via _esegui_marcia()
      - Step 3: conferma contatore post-marcia

    Ritorna (marcia_ok, tipo_bloccato, skip_neutro).
    """
    # Sequenza livelli da tentare prima di bloccare il tipo
    livello_base = max(1, min(7, int(
        ctx.config.get("livello", _cfg(ctx, "RACCOLTA_LIVELLO"))
    )))
    if livello_base == 7:
        sequenza_livelli = [7, 6, 5]
    else:
        # livello_base == 6 (o altro): prova base, poi 7, poi 5
        seq = [livello_base, 7, 5]
        seen = set()
        sequenza_livelli = [lv for lv in seq
                            if lv not in seen and not seen.add(lv)]

    cerca_ok = False
    chiave_test = None
    for lv in sequenza_livelli:
        ctx.log_msg(f"Raccolta: tentativo CERCA {tipo} Lv.{lv}")
        ok = _cerca_nodo(ctx, tipo, livello_override=lv)
        if not ok:
            # Tipo NON selezionato — problema UI, inutile cambiare livello
            ctx.log_msg(
                f"Raccolta [{tipo}]: tipo NON selezionato — "
                f"abort sequenza livelli"
            )
            return False, True, False  # tipo_bloccato=True
        # _cerca_nodo OK: ora leggi le coordinate del primo nodo
        # Se la lista risultati è vuota, chiave sarà None
        chiave_test = _leggi_coord_nodo(ctx)
        if chiave_test is not None:
            # Trovato almeno un nodo a questo livello — procedi
            ctx.log_msg(f"Raccolta: nodo trovato a Lv.{lv} — procedo")
            cerca_ok = True
            break
        # Lista vuota a questo livello → prova livello successivo
        ctx.log_msg(
            f"Raccolta: nessun nodo disponibile a Lv.{lv} — "
            f"provo livello successivo"
        )
        # Chiudi pannello lente prima del prossimo tentativo
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.8)

    if not cerca_ok:
        ctx.log_msg(
            f"Raccolta [{tipo}]: nessun nodo trovato su nessun livello — "
            f"tipo bloccato"
        )
        return False, True, False  # tipo_bloccato=True

    # chiave già letta nel loop sopra
    chiave = chiave_test
    # chiave può essere None se OCR fallisce — procediamo senza blacklist

    # Step 6: check blacklist statica fuori territorio (disco) — skip immediato
    if chiave and blacklist_fuori.contiene(chiave):
        ctx.log_msg(f"Raccolta [{tipo}]: nodo {chiave} in blacklist statica fuori — skip")
        # Chiudi lista risultati + lente (doppio BACK per stato pulito)
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.5)
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.5)
        # Ricentra mappa sul castello prima della prossima cerca
        if ctx.navigator is not None:
            ctx.navigator.vai_in_home()
            time.sleep(0.5)
            ctx.navigator.vai_in_mappa()
            time.sleep(1.0)
        return False, False, True   # skip neutro

    # Check blacklist dinamica RAM — nodo già occupato da nostra squadra
    if chiave and blacklist.contiene(chiave):
        eta_prev = blacklist.get_eta(chiave)
        if isinstance(eta_prev, (int, float)) and eta_prev > 0:
            marg    = int(_cfg(ctx, "ETA_MARGINE_S"))
            att_min = int(_cfg(ctx, "ETA_MIN_S"))
            attesa  = int(min(_cfg(ctx, "BLACKLIST_ATTESA_NODO"),
                              max(att_min, eta_prev + marg)))
            ctx.log_msg(f"Raccolta [{tipo}]: nodo {chiave} in blacklist "
                        f"(ETA={int(eta_prev)}s) — cooldown {attesa}s")
        else:
            attesa = int(_cfg(ctx, "BLACKLIST_ATTESA_NODO"))
            ctx.log_msg(f"Raccolta [{tipo}]: nodo {chiave} in blacklist "
                        f"— cooldown {attesa}s (TTL fisso)")
        cooldown_map[tipo] = time.time() + attesa
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.5)
        # Nuova CERCA per trovare nodo diverso
        if not _cerca_nodo(ctx, tipo):
            return False, False, False
        chiave2 = _leggi_coord_nodo(ctx)
        if chiave2 == chiave or (chiave2 and blacklist.contiene(chiave2)):
            ctx.log_msg(f"Raccolta [{tipo}]: secondo nodo ancora in blacklist — tipo bloccato")
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.5)
            return False, True, False
        chiave = chiave2

    # Tap nodo + verifica GATHER (popup lista risultati → popup nodo)
    esito = _tap_nodo_e_verifica_gather(ctx, tipo)
    if isinstance(esito, tuple):
        esito_str, screen_popup = esito
    else:
        esito_str, screen_popup = esito, None

    if esito_str == "errore":
        return False, False, False

    # Step 5: verifica livello nodo via OCR
    if screen_popup is not None:
        livello_nodo = _leggi_livello_nodo(ctx, screen_popup)
        livello_min  = int(_cfg(ctx, "RACCOLTA_LIVELLO_MIN"))
        if livello_nodo != -1 and livello_nodo < livello_min:
            ctx.log_msg(f"Raccolta [{tipo}]: nodo Lv.{livello_nodo} < min {livello_min} "
                        f"— scarto e blacklisto")
            if chiave:
                blacklist.commit(chiave, eta_s=None)
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.5)
            return False, True, False
        elif livello_nodo != -1:
            ctx.log_msg(f"Raccolta [{tipo}]: nodo Lv.{livello_nodo} ✓")

    # Step 4+6: verifica territorio
    if screen_popup is not None and not _nodo_in_territorio(screen_popup, tipo, ctx):
        ctx.log_msg(f"Raccolta [{tipo}]: nodo FUORI territorio — blacklist statica + dinamica")
        if chiave:
            blacklist_fuori.aggiungi(chiave, tipo)   # Step 6: persiste su disco
            blacklist.commit(chiave, eta_s=None)      # Step 4: blacklist dinamica
        # Chiudi popup nodo + ricentra mappa
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.5)
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.5)
        if ctx.navigator is not None:
            ctx.navigator.vai_in_home()
            time.sleep(0.5)
            ctx.navigator.vai_in_mappa()
            time.sleep(1.0)
        return False, False, True   # skip neutro

    # RESERVED
    if chiave:
        blacklist.reserve(chiave)
        ctx.log_msg(f"Raccolta [{tipo}]: nodo {chiave} RESERVED")

    # Esegui marcia (Step 2: ETA inclusa)
    ok, eta_s = _esegui_marcia(ctx, n_truppe)

    if not ok:
        if chiave:
            blacklist.rollback(chiave)
        ctx.log_msg(f"Raccolta [{tipo}]: marcia FALLITA → rollback")
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.5)
        return False, False, False

    # Step 3: lettura contatore post-marcia (solo informativa).
    # La marcia è già confermata visivamente dalla chiusura della maschera.
    # Il contatore in mappa può richiedere qualche secondo per aggiornarsi
    # — non usiamo il fallback OCR come criterio di successo/fallimento.
    time.sleep(1.5)
    attive_dopo = _leggi_attive_post_marcia(ctx, obiettivo)
    if attive_dopo >= 0:
        ctx.log_msg(f"Raccolta [{tipo}]: marcia OK — attive post={attive_dopo}")
    else:
        ctx.log_msg(f"Raccolta [{tipo}]: marcia OK — contatore N/D (marcia confermata visivamente)")

    # COMMITTED con ETA dinamica (Step 2)
    if chiave:
        blacklist.commit(chiave, eta_s=eta_s)
        ttl_log = f"ETA={eta_s}s" if eta_s else f"TTL={_cfg(ctx, 'BLACKLIST_COMMITTED_TTL')}s"
        ctx.log_msg(f"Raccolta [{tipo}]: nodo {chiave} COMMITTED ({ttl_log})")

    return True, False, False


# ==============================================================================
# Squad Summary — conteggio slot attivi reali
# ==============================================================================

# Coordinate pulsante frecce slot (mappa) — tap apre Squad Summary
_TAP_SLOT_BTN    = (877, 126)
# Zona righe Squad Summary — ogni riga ha altezza ~90px a partire da y≈180
# Verifica presenza testo "Gathering" o "Deploying" per riga occupata
# In mancanza di OCR robusto, conta le righe visibili via pixel check
# sulla colonna sinistra dove appare l'immagine del nodo (x≈165, y variabile)
_SUMMARY_ROI     = (140, 160, 820, 520)   # area popup Squad Summary
_SUMMARY_CLOSE   = (795,  68)              # X chiusura popup

def _leggi_slot_da_summary(ctx: TaskContext) -> int:
    """
    Apre il popup Squad Summary (tap frecce slot) e conta le righe occupate.
    Ritorna numero di slot attivi (int >= 0) oppure -1 se popup non aperto.

    Il pulsante frecce (877,126) è visibile SOLO se almeno uno slot è attivo.
    Se non visibile → 0 slot attivi.

    Strategia conteggio: il popup mostra una riga per slot attivo, ciascuna
    con un'immagine nodo sulla sinistra. Contiamo le righe tramite TM su
    pin_gather.png (icona GATHER/frecce nodo) oppure via pixel check.
    In assenza di pin dedicato, usiamo il numero di separatori "Total Squads"
    come proxy — uno per riga.
    """
    template_gather = _cfg(ctx, "TEMPLATE_GATHER")
    soglia          = _cfg(ctx, "TEMPLATE_SOGLIA")

    # Screenshot iniziale — verifica se il pulsante frecce è visibile
    screen = ctx.device.screenshot()
    if screen is None:
        return -1

    # Il pulsante è presente solo se almeno uno slot è attivo
    # Verifica pixel nella zona del pulsante — se schermata mappa con slot:
    # l'area (860,110,900,145) contiene il pulsante frecce
    frame = getattr(screen, "frame", None)
    if frame is not None:
        zona_btn = frame[110:145, 860:900]
        # Pixel non uniformemente scuri → pulsante presente
        media = int(zona_btn.mean())
        if media < 20:
            ctx.log_msg("[SUMMARY] pulsante slot non visibile — 0 slot attivi")
            return 0

    # Tap sul pulsante frecce → apre Squad Summary
    ctx.device.tap(*_TAP_SLOT_BTN)
    time.sleep(1.5)

    screen2 = ctx.device.screenshot()
    if screen2 is None:
        return -1

    # Conta match di pin_gather nella ROI del popup — ogni riga ha un'icona
    # Usiamo find_all() per contare tutte le occorrenze
    try:
        matches = ctx.matcher.find_all(
            screen2, template_gather,
            threshold=soglia,
            zone=_SUMMARY_ROI,
            cluster_px=60,   # cluster 60px per separare righe diverse
        )
        n_slot = len(matches)
        ctx.log_msg(f"[SUMMARY] slot attivi rilevati: {n_slot}")
    except Exception as exc:
        ctx.log_msg(f"[SUMMARY] errore conteggio: {exc} — uso fallback")
        n_slot = -1

    # Chiude popup
    ctx.device.tap(*_SUMMARY_CLOSE)
    time.sleep(0.8)

    return n_slot


# ==============================================================================
# Loop principale invio marce
# ==============================================================================

def _loop_invio_marce(ctx: TaskContext, obiettivo: int,
                       attive_inizio: int,
                       blacklist: Blacklist,
                       blacklist_fuori: BlacklistFuori) -> int:
    """
    Loop invio squadre fino a slot pieni o MAX_FALLIMENTI.

    Gestione risultati di _invia_squadra():
      - ok=True: incrementa inviate, attive_correnti, reset fallimenti_cons,
        break se slot pieni
      - skip_neutro: nessuna modifica contatori
      - tipo_bloccato=True: aggiunge a tipi_bloccati, NO fallimenti++, NO HOME
      - fallimento puro (ok=False, !tipo_bloccato, !skip_neutro):
        fallimenti++, HOME + OCR + MAP, se slot pieni → exit
    """
    max_fallimenti = _cfg(ctx, "RACCOLTA_MAX_FALLIMENTI")
    n_truppe       = _cfg(ctx, "RACCOLTA_TRUPPE")
    deposito_ocr   = getattr(ctx, "_deposito_ocr", {})
    sequenza_base  = _cfg(ctx, "RACCOLTA_SEQUENZA")

    tipi_bloccati: set[str]    = set()
    cooldown_map: dict[str, float] = {}
    skip_neutri_per_tipo: dict[str, int] = {}

    attive_correnti = attive_inizio
    inviate         = 0
    fallimenti_cons = 0
    idx_seq         = 0
    max_iter        = obiettivo * max(2, max_fallimenti) + 5

    for iter_n in range(max_iter):
        if attive_correnti >= obiettivo:
            ctx.log_msg(f"Raccolta: obiettivo raggiunto ({attive_correnti}/{obiettivo})")
            break
        if fallimenti_cons >= max_fallimenti:
            ctx.log_msg(f"Raccolta: troppi fallimenti ({fallimenti_cons}) — abbandono")
            break

        tipi_disponibili = [t for t in _TUTTI_I_TIPI if t not in tipi_bloccati]
        if not tipi_disponibili:
            ctx.log_msg("Raccolta: tutti i tipi bloccati — uscita")
            break

        ora    = time.time()
        pronti = [t for t in tipi_disponibili if cooldown_map.get(t, 0) <= ora]
        if not pronti:
            t_min  = min(cooldown_map.get(t, ora) for t in tipi_disponibili)
            wait_s = max(1, int(t_min - ora))
            ctx.log_msg(f"Raccolta: tutti in cooldown — attendo {wait_s}s")
            time.sleep(wait_s)
            continue

        libere_ora = obiettivo - attive_correnti
        if deposito_ocr:
            sequenza = _calcola_sequenza_allocation(libere_ora, deposito_ocr)
            sequenza = [t for t in sequenza if t not in tipi_bloccati] or                        _calcola_sequenza(libere_ora, sequenza_base, tipi_bloccati)
        else:
            sequenza = _calcola_sequenza(libere_ora, sequenza_base, tipi_bloccati)

        # Interleave: alterna i tipi per evitare attese sul nodo stesso tipo
        sequenza = _interleave(sequenza)

        if not sequenza:
            ctx.log_msg("Raccolta: sequenza vuota — abbandono")
            break

        tipo = sequenza[idx_seq % len(sequenza)]
        idx_seq += 1

        if cooldown_map.get(tipo, 0) > time.time():
            continue
        if tipo in tipi_bloccati:
            continue

        ctx.log_msg(f"Raccolta: invio squadra {attive_correnti + 1}/{obiettivo} → {tipo} "
                    f"(fallimenti_cons={fallimenti_cons}/{max_fallimenti})")

        ok, tipo_bloccato, skip_neutro = _invia_squadra(
            ctx, tipo, blacklist, blacklist_fuori,
            cooldown_map, n_truppe, tipi_bloccati, obiettivo
        )

        # ── CASO ok=True ─────────────────────────────────────────────────
        if ok:
            inviate         += 1
            attive_correnti += 1
            fallimenti_cons  = 0
            skip_neutri_per_tipo[tipo] = 0
            ctx.log_msg(f"Raccolta: squadra confermata ({attive_correnti}/{obiettivo})")
            time.sleep(_cfg(ctx, "DELAY_POST_MARCIA"))
            if attive_correnti >= obiettivo:
                ctx.log_msg(f"Raccolta: slot pieni ({attive_correnti}/{obiettivo}) — uscita")
                break
            continue

        # ── CASO skip_neutro ─────────────────────────────────────────────
        if skip_neutro:
            skip_neutri_per_tipo[tipo] = skip_neutri_per_tipo.get(tipo, 0) + 1
            n_skip = skip_neutri_per_tipo[tipo]
            ctx.log_msg(
                f"Raccolta: skip neutro {tipo} ({n_skip}/2) — "
                f"fallimenti_cons invariato ({fallimenti_cons})"
            )
            if n_skip >= 2:
                tipi_bloccati.add(tipo)
                ctx.log_msg(
                    f"Raccolta: tipo '{tipo}' bloccato dopo {n_skip} skip neutri consecutivi"
                )
                if set(_TUTTI_I_TIPI).issubset(tipi_bloccati):
                    ctx.log_msg("Raccolta: tutti i tipi bloccati — uscita")
                    break
            continue

        # ── CASO tipo_bloccato (CERCA fallita / blacklist / livello basso) ──
        # Nessun HOME, nessun fallimenti++. Solo marcatura e continua.
        if tipo_bloccato:
            tipi_bloccati.add(tipo)
            ctx.log_msg(f"Raccolta: tipo '{tipo}' bloccato per questo ciclo")
            if set(_TUTTI_I_TIPI).issubset(tipi_bloccati):
                ctx.log_msg("Raccolta: tutti i tipi bloccati — uscita")
                break
            continue

        # ── CASO fallimento puro (marcia fallita con rollback) ───────────
        # Torna in HOME, rileggi slot, rientra in mappa.
        fallimenti_cons += 1
        if ctx.navigator is not None:
            ctx.navigator.vai_in_home()
            time.sleep(1.0)
        try:
            from shared.ocr_helpers import leggi_contatore_slot
            screen_home = ctx.device.screenshot()
            if screen_home is not None:
                attive_reali, _ = leggi_contatore_slot(
                    screen_home, totale_noto=obiettivo
                )
                if attive_reali > obiettivo:
                    ctx.log_msg(
                        f"Raccolta: OCR post-rollback anomalo "
                        f"attive={attive_reali}>totale={obiettivo} — ignorato"
                    )
                elif attive_reali >= 0:
                    if attive_reali != attive_correnti:
                        ctx.log_msg(
                            f"Raccolta: [RIALLINEA] attive {attive_correnti}→{attive_reali} "
                            f"(OCR post-rollback da HOME)"
                        )
                        attive_correnti = attive_reali
                    if attive_correnti >= obiettivo:
                        ctx.log_msg(
                            f"Raccolta: slot pieni dopo rollback "
                            f"({attive_correnti}/{obiettivo}) — uscita immediata"
                        )
                        return inviate
        except Exception as exc:
            ctx.log_msg(f"Raccolta: OCR slot post-rollback fallito ({exc})")
        if ctx.navigator is not None:
            ctx.navigator.vai_in_mappa()
            time.sleep(1.5)

    # ── Fine loop: torna in HOME, rileggi slot, log ──────────────────────
    if ctx.navigator is not None:
        ctx.navigator.vai_in_home()
        time.sleep(1.0)
    try:
        from shared.ocr_helpers import leggi_contatore_slot
        screen_home = ctx.device.screenshot()
        if screen_home is not None:
            attive_ocr, _ = leggi_contatore_slot(screen_home, totale_noto=obiettivo)
            if 0 <= attive_ocr <= obiettivo:
                attive_correnti = attive_ocr
    except Exception:
        pass

    ctx.log_msg(
        f"Raccolta: loop completato — {inviate} inviate, "
        f"attive={attive_correnti}/{obiettivo}"
    )
    return inviate


# ==============================================================================
# Task V6
# ==============================================================================

class RaccoltaTask(Task):
    """
    Task periodico (4h) — invio squadre raccoglitrici.
    V6 upgraded: OCR coordinate, ETA dinamica, conferma contatore,
    blacklist statica fuori territorio, verifica livello nodo.
    """

    def name(self) -> str:
        return "raccolta"

    def schedule_type(self) -> str:
        return "periodic"

    def interval_hours(self) -> float:
        return 4.0

    def should_run(self, ctx) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("raccolta")
        return True

    def run(self, ctx: TaskContext,
            attive_inizio: int = 0,
            slot_liberi: int = -1,
            blacklist: Optional[Blacklist] = None) -> TaskResult:

        if not _cfg(ctx, "RACCOLTA_ABILITATA"):
            ctx.log_msg("Raccolta: modulo disabilitato — skip")
            return TaskResult(success=True, message="disabilitato", data={"inviate": 0})

        # Legge max_squadre dall'istanza (instances.json) come obiettivo reale.
        # Fallback a RACCOLTA_OBIETTIVO se non disponibile.
        obiettivo = int(ctx.config.get("max_squadre", _cfg(ctx, "RACCOLTA_OBIETTIVO")))

        if slot_liberi < 0:
            libere = max(0, obiettivo - attive_inizio)
        else:
            libere = slot_liberi

        if libere == 0:
            ctx.log_msg(f"Raccolta: nessuna squadra libera ({attive_inizio}/{obiettivo}) — skip")
            return TaskResult(success=True, message="nessuna squadra libera", data={"inviate": 0})

        # Lettura slot attivi reali via OCR barra contatore.
        # Fix 15/04/2026: psm=6 scale=2 maschera_bianca in ocr_helpers.py
        # risolve bug 3/5 invece di 5/5 (calibrato con calibra_slot_ocr.py).
        if attive_inizio == 0 and slot_liberi < 0 and ctx.device is not None:
            totale_noto = int(ctx.config.get("max_squadre", obiettivo))
            obiettivo   = totale_noto  # usa sempre il totale da instances.json
            try:
                from shared.ocr_helpers import leggi_contatore_slot
                time.sleep(1.5)   # attesa stabilizzazione schermata HOME
                screen_home = ctx.device.screenshot()
                if screen_home is not None:
                    attive_ocr, totale_ocr = leggi_contatore_slot(
                        screen_home, totale_noto=totale_noto)
                    # Sanity check: attive > totale_noto = OCR sicuramente sbagliato
                    # (es. "5" letto come "7"). Fallback conservativo: assumo pieni.
                    if attive_ocr > totale_noto:
                        ctx.log_msg(
                            f"Raccolta: OCR slot anomalo attive={attive_ocr}>totale={totale_noto} "
                            f"— assumo slot pieni, skip conservativo"
                        )
                        return TaskResult(success=True, message="OCR anomalo — skip conservativo",
                                          data={"inviate": 0})
                    if attive_ocr >= 0:
                        attive_inizio = attive_ocr
                        if totale_ocr > 0:
                            obiettivo = totale_ocr
                        libere = max(0, obiettivo - attive_inizio)
                        ctx.log_msg(
                            f"Raccolta: slot OCR — attive={attive_inizio}/{obiettivo} "
                            f"libere={libere}"
                        )
                        if libere == 0:
                            ctx.log_msg("Raccolta: nessuna squadra libera — skip")
                            return TaskResult(success=True, message="nessuna squadra libera",
                                              data={"inviate": 0})
                    else:
                        ctx.log_msg(f"Raccolta: OCR slot fallito — uso default {attive_inizio}/{obiettivo}")
            except Exception as exc:
                ctx.log_msg(f"Raccolta: OCR slot eccezione ({exc}) — uso default")

        # OCR deposito per allocation
        deposito_ocr: dict = {}
        try:
            from shared.ocr_helpers import ocr_risorse
            screen_ris = ctx.device.screenshot() if ctx.device else None
            if screen_ris is not None:
                ris = ocr_risorse(screen_ris)
                deposito_ocr = {
                    "pomodoro": ris.pomodoro,
                    "legno":    ris.legno,
                    "acciaio":  ris.acciaio,
                    "petrolio": ris.petrolio,
                }
                ctx.log_msg(f"Raccolta: deposito OCR pom={ris.pomodoro/1e6:.1f}M "
                            f"leg={ris.legno/1e6:.1f}M acc={ris.acciaio/1e6:.1f}M "
                            f"pet={ris.petrolio/1e6:.1f}M")
        except Exception as exc:
            ctx.log_msg(f"Raccolta: OCR deposito fallito ({exc}) — uso sequenza default")

        ctx.log_msg(f"Raccolta: start — attive={attive_inizio}/{obiettivo} libere={libere}")

        if blacklist is None:
            blacklist = Blacklist(
                committed_ttl=int(_cfg(ctx, "BLACKLIST_COMMITTED_TTL")),
                reserved_ttl=int(_cfg(ctx, "BLACKLIST_RESERVED_TTL")),
            )

        # Step 6: blacklist statica globale fuori territorio
        fuori_dir = _cfg(ctx, "BLACKLIST_FUORI_DIR")
        blacklist_fuori = BlacklistFuori(data_dir=fuori_dir)
        if len(blacklist_fuori) > 0:
            ctx.log_msg(f"Raccolta: blacklist statica globale fuori territorio: "
                        f"{len(blacklist_fuori)} nodi noti")

        ctx._deposito_ocr = deposito_ocr  # type: ignore

        # Loop esterno: MAX_TENTATIVI_CICLO tentativi di riempire gli slot.
        # Ogni tentativo: naviga in mappa → _loop_invio_marce → HOME + OCR check.
        # Uscita anticipata se slot pieni (successo) o vai_in_mappa fallisce.
        MAX_TENTATIVI_CICLO = 3
        tentativi_ciclo = 0
        inviate_totali  = 0
        attive_correnti = attive_inizio

        try:
            while tentativi_ciclo < MAX_TENTATIVI_CICLO:
                tentativi_ciclo += 1

                if tentativi_ciclo > 1:
                    # Rileggi slot da HOME prima di decidere se riprovare
                    if ctx.navigator is not None:
                        ctx.navigator.vai_in_home()
                        time.sleep(1.0)
                    try:
                        from shared.ocr_helpers import leggi_contatore_slot
                        screen_home = ctx.device.screenshot()
                        if screen_home is not None:
                            attive_ocr, _ = leggi_contatore_slot(
                                screen_home, totale_noto=obiettivo
                            )
                            if 0 <= attive_ocr <= obiettivo:
                                attive_correnti = attive_ocr
                                ctx.log_msg(
                                    f"Raccolta: pre-tentativo {tentativi_ciclo} — "
                                    f"attive={attive_correnti}/{obiettivo}"
                                )
                                if attive_correnti >= obiettivo:
                                    ctx.log_msg("Raccolta: slot pieni — chiusura istanza")
                                    break
                    except Exception as exc:
                        ctx.log_msg(f"Raccolta: OCR pre-tentativo fallito ({exc})")

                    # Slot ancora liberi: naviga in mappa per il tentativo successivo
                    if ctx.navigator is not None:
                        if not ctx.navigator.vai_in_mappa():
                            ctx.log_msg(
                                f"Raccolta: vai_in_mappa fallito al tentativo "
                                f"{tentativi_ciclo} — uscita"
                            )
                            break
                    else:
                        ctx.device.key("KEYCODE_MAP")
                        time.sleep(2.0)
                else:
                    # Primo tentativo: navigazione iniziale in mappa
                    ctx.log_msg("Raccolta: navigazione → mappa")
                    if ctx.navigator is not None:
                        if not ctx.navigator.vai_in_mappa():
                            ctx.log_msg("Raccolta: impossibile andare in mappa — abort")
                            return TaskResult(success=False, message="vai_in_mappa fallito",
                                              data={"inviate": 0})
                    else:
                        ctx.device.key("KEYCODE_MAP")
                        time.sleep(2.0)

                # Esegui il loop invio marce
                inviate = _loop_invio_marce(ctx, obiettivo, attive_correnti,
                                             blacklist, blacklist_fuori)
                inviate_totali += inviate

                # Post-loop: rileggi slot da HOME per decidere se continuare
                if ctx.navigator is not None:
                    ctx.navigator.vai_in_home()
                    time.sleep(1.0)
                try:
                    from shared.ocr_helpers import leggi_contatore_slot
                    screen_home = ctx.device.screenshot()
                    if screen_home is not None:
                        attive_ocr, _ = leggi_contatore_slot(
                            screen_home, totale_noto=obiettivo
                        )
                        if 0 <= attive_ocr <= obiettivo:
                            attive_correnti = attive_ocr
                except Exception:
                    pass

                if attive_correnti >= obiettivo:
                    ctx.log_msg(
                        f"Raccolta: slot pieni ({attive_correnti}/{obiettivo}) "
                        f"— chiusura istanza"
                    )
                    break

                ctx.log_msg(
                    f"Raccolta: tentativo {tentativi_ciclo}/{MAX_TENTATIVI_CICLO} "
                    f"completato — slot {attive_correnti}/{obiettivo}"
                )
        except Exception as e:
            ctx.log_msg(f"Raccolta: errore nel loop esterno: {e}")
            return TaskResult(success=False, message=f"errore: {e}",
                              data={"inviate": inviate_totali})
        finally:
            ctx.log_msg("Raccolta: ritorno in home")
            if ctx.navigator is not None:
                ctx.navigator.vai_in_home()
            else:
                ctx.device.key("KEYCODE_HOME")

        slot_pieni = (attive_correnti >= obiettivo)
        ctx.log_msg(
            f"Raccolta: completata — {inviate_totali} squadre totali "
            f"(tentativi={tentativi_ciclo}, slot_pieni={slot_pieni})"
        )
        return TaskResult(
            success=True,
            message=f"{inviate_totali} squadre inviate",
            data={"inviate": inviate_totali, "slot_pieni": slot_pieni},
        )
