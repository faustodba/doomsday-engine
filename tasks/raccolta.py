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
#  FIX 19/04/2026 — sessione consolidamento (RT-23):
#    FIX A — Sequenza logica _invia_squadra() riscritta:
#            CERCA → leggi_coord → check blacklist_fuori (skip_neutro) →
#            check blacklist RAM (retry o tipo_bloccato) → reserve →
#            tap nodo + gather → territorio (skip_neutro se FUORI) →
#            livello nodo (tipo_bloccato se basso) → marcia → commit.
#    FIX B — _reset_to_mappa(ctx, obiettivo) funzione centralizzata:
#            vai_in_home → leggi_contatore_slot → vai_in_mappa.
#            Ritorna attive_reali (-1 se OCR fallisce). Sostituisce tutti
#            i blocchi sparsi di "BACK + HOME + MAPPA".
#    FIX C — Verifica slot HOME dopo ogni marcia confermata (ok=True):
#            _reset_to_mappa() + aggiornamento attive_correnti.
#            Uscita immediata se attive_correnti >= obiettivo.
#    FIX D — idx_seq sostituito da iteratore su sequenza ricalcolata:
#            ogni giro while ricalcola sequenza; for tipo in sequenza:
#            se ok=True → break for → ricalcola al prossimo while.
#    FIX E — Fallback livelli semplificato:
#            base=7 → [7, 6], base=6 → [6, 7]. Rimosso Lv.5.
#    FIX F — Delay stabilizzazione aumentati in _cerca_nodo,
#            _verifica_tipo, _tap_nodo_e_verifica_gather, _esegui_marcia.
#    FIX G — _tap_nodo_e_verifica_gather ritorna _GatherResult dataclass
#            invece di tuple implicita (ok: bool, screen: Optional).
#    FIX H — Debug screenshot su _verifica_tipo con score < 0.20:
#            salva frame in debug_task/raccolta/ per analisi visiva della
#            schermata anomala (Issue #9 petrolio FAU_00: score 0.15
#            stabile = UI alterata da overlay/popup, non rumore casuale).
#    FIX I — _apri_lente_verificata(): apertura lente con verifica
#            post-tap che le icone tipo siano visibili nella ROI LENTE.
#            Se no (maschera bestie, popup "General Notice", etc.) →
#            BACK×2 recovery + retry fino a max_retry=3. Integrato in
#            `_cerca_nodo` sia in apertura primaria che in reset pannello.
#            Risolve trigger visivamente confermato via debug screenshot:
#            FAU_00 dopo marcia cade in maschera beast roster/Level Up,
#            i tap successivi (tipo, livello, CERCA) vanno su UI sbagliata.
#
#  FLUSSO AGGIORNATO (post FIX A):
#    0. Verifica abilitazione + slot liberi (iniettabile nei test)
#    1. Naviga in mappa
#    2. Loop esterno (max 3 tentativi ciclo): ogni tentativo esegue
#       _loop_invio_marce → HOME + OCR slot; uscita se slot pieni.
#    3. _loop_invio_marce: while finché attive < obiettivo:
#       a. Ricalcola sequenza (allocation gap V5) + interleave
#       b. for tipo in sequenza:
#            - salta se tipo bloccato o in cooldown
#            - _invia_squadra(tipo)
#            - ok=True: +1 inviate, _reset_to_mappa, break for → ricalcola
#            - skip_neutro: contatore +1, block tipo se >= 2, continue
#            - tipo_bloccato: block tipo, continue
#            - fallimento puro: fallimenti_cons +1, continue
#    4. _invia_squadra:
#       - per lv in sequenza_livelli:
#           CERCA + leggi coord
#           se chiave in blacklist_fuori → _reset_to_mappa → prova lv successivo
#           se chiave in blacklist RAM → retry CERCA stesso lv; ancora occupato
#             → tipo_bloccato
#           altrimenti → reserve + break (usa questo nodo)
#       - se nessun lv ha dato nodo utile → skip_neutro
#       - tap nodo + gather
#       - territorio IN? sì → livello nodo OK? sì → marcia → commit
#                        no → blacklist_fuori.aggiungi + rollback → skip_neutro
#                        livello basso → blacklist.commit + tipo_bloccato
#    5. Ritorna in home
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
from dataclasses import dataclass
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
    # F3 — maschera invio aperta ma senza squadre disponibili
    "TEMPLATE_NO_SQUADS":   "pin/pin_no_squads.png",
    "SOGLIA_NO_SQUADS":     0.85,
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
    # WU50 — modalità "fuori territorio": permette raccolta su nodi fuori
    # territorio (rifugio piazzato in zona dove tutti i nodi sono fuori).
    # Quando True:
    #   - bypass del check `_nodo_in_territorio` (procede comunque)
    #   - bypass del check `blacklist_fuori.contiene` (legge nodi blacklisted)
    #   - NON aggiunge nodi alla blacklist_fuori (sempre ignorato)
    # Override per-istanza in runtime_overrides.json:
    #   "istanze": { "FAU_05": { "raccolta_fuori_territorio": true } }
    "RACCOLTA_FUORI_TERRITORIO_ABILITATA": False,
    # WU55 — Data collection per analisi OCR slot in MAPPA vs HOME.
    # Quando True: dopo lettura slot HOME (ground truth) + dopo vai_in_mappa,
    # salva crop+screenshot in data/ocr_dataset/ per analisi offline.
    # NON cambia il comportamento del bot (passive shadow OCR in MAPPA).
    "RACCOLTA_OCR_DEBUG": False,
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


def _ocr_debug_collect_map(ctx: TaskContext) -> None:
    """
    WU55 — Data collection: shadow OCR su MAPPA dopo vai_in_mappa.

    Esegue OCR slot in MAPPA usando stesso preprocessing di HOME (per
    confrontare il fail). Salva sample MAPPA con stesso pair_id del
    sample HOME corrispondente. Failsafe: log warning, non blocca task.

    Pre-requisito: ctx._ocr_pair settato dal save_home_sample (in OCR HOME).
    """
    if not bool(_cfg(ctx, "RACCOLTA_OCR_DEBUG")):
        return
    pair = getattr(ctx, "_ocr_pair", None)
    if not pair:
        return
    pid, attive_home, totale_home = pair
    try:
        from shared.ocr_helpers import leggi_contatore_slot
        from shared.ocr_dataset import save_map_sample
        # Attesa stabilizzazione MAPPA
        time.sleep(1.5)
        screen_map = ctx.device.screenshot() if ctx.device else None
        if screen_map is None:
            ctx.log_msg("[OCR-DEBUG] map screenshot None — skip")
            return
        attive_map, totale_map = leggi_contatore_slot(
            screen_map, totale_noto=totale_home,
        )
        ocr_raw = f"{attive_map}/{totale_map}"
        match = (attive_map == attive_home) and (totale_map == totale_home)
        save_map_sample(
            istanza=ctx.instance_name,
            pair_id=pid,
            screen=screen_map,
            ocr_raw=ocr_raw,
            attive=attive_map,
            totale=totale_map,
            extra={
                "trigger":         "_ocr_debug_collect_map",
                "schermata":       "MAP",
                "home_attive":     int(attive_home),
                "home_totale":     int(totale_home),
                "match_home":      bool(match),
            },
        )
        marker = "✓" if match else "✗"
        ctx.log_msg(
            f"[OCR-DEBUG] map sample pair={pid} home={attive_home}/{totale_home} "
            f"map={attive_map}/{totale_map} {marker}"
        )
        # One-shot: dopo aver salvato la coppia, resetto pair per evitare
        # multipli sample MAP per lo stesso HOME (multi-tentativi loop).
        ctx._ocr_pair = None  # type: ignore
    except Exception as exc:
        ctx.log_msg(f"[OCR-DEBUG] collect map fail: {exc}")


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
# Debug — salvataggio screenshot su anomalie _verifica_tipo
# ==============================================================================

def _salva_debug_verifica(ctx: TaskContext, screen, tipo: str, score: float) -> None:
    """
    Salva screenshot quando _verifica_tipo fallisce con score molto basso.
    Utile per capire cosa mostra il gioco quando il template non matcha
    (overlay, popup, maschera alternativa, ecc.).

    Output: debug_task/raccolta/verifica_{istanza}_{tipo}_{ts}_score{N}.png
    Gitignore esclude *.png quindi non finisce in git.
    """
    try:
        import cv2
        from datetime import datetime as _dt
        frame = getattr(screen, "frame", None)
        if frame is None:
            return
        root = Path(__file__).resolve().parents[1]
        out_dir = root / "debug_task" / "raccolta"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts       = _dt.now().strftime("%Y%m%d_%H%M%S")
        istanza  = getattr(ctx, "instance_name", "UNK")
        score_i  = int(max(0.0, min(1.0, score)) * 1000)
        filename = f"verifica_{istanza}_{tipo}_{ts}_score{score_i:03d}.png"
        filepath = out_dir / filename
        cv2.imwrite(str(filepath), frame)
        ctx.log_msg(f"[DEBUG] screenshot salvato: debug_task/raccolta/{filename}")
    except Exception as exc:
        ctx.log_msg(f"[DEBUG] salvataggio screenshot fallito: {exc}")


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
    """
    Verifica visiva che il tipo sia selezionato nel pannello lente.
    FIX F 19/04/2026: delay stabilizzazione aumentati
      - sleep iniziale (pre-flush): 0.5 → 0.8
      - sleep tra flush e live:     0.2 → 0.5

    FIX 19/04/2026 RT-24: se score < 0.20 salva screenshot debug per
    analisi visiva della schermata anomala (Issue #9 petrolio FAU_00).
    Score 0.15 stabile indica UI alterata (overlay/popup) — il salvataggio
    consente di identificare cosa realmente appare sullo schermo.
    """
    tmpl_tipo = _cfg(ctx, "TMPL_TIPO").get(tipo)
    if not tmpl_tipo:
        return True
    soglia = _cfg(ctx, "SOGLIA_TIPO")
    roi    = _cfg(ctx, "ROI_LENTE")
    time.sleep(0.8)                   # FIX F: 0.5 → 0.8
    ctx.device.screenshot()           # flush frame cached
    time.sleep(1.0)                   # Slow-PC: 0.5 → 1.0 (stabilizza pre-match tipo)
    screen = ctx.device.screenshot()  # frame live
    if not screen:
        return True
    r = ctx.matcher.find_one(screen, tmpl_tipo, threshold=soglia, zone=roi)
    ctx.log_msg(f"Raccolta: [VERIFICA] tipo {tipo} score={r.score:.3f} → "
                f"{'OK' if r.found else 'NON selezionato'}")

    # DEBUG: salva screenshot su score molto basso (UI verosimilmente alterata)
    if not r.found and r.score < 0.20:
        _salva_debug_verifica(ctx, screen, tipo, r.score)

    return r.found


def _apri_lente_verificata(ctx: TaskContext, max_retry: int = 3) -> bool:
    """
    Apre la lente con verifica post-tap che le icone tipo siano visibili
    nella ROI lente. Se non visibile (siamo in maschera bestie, popup
    "General Notice", o altra UI imprevista) → BACK × 2 recovery + retry.

    FIX 19/04/2026: introdotto per gestire il caso in cui il tap (38,325)
    NON apre la lente ma cade su una bestia visibile sulla mappa o è
    intercettato da un popup. Verificato visivamente via debug screenshot:
    FAU_00 catturato nella maschera "beast roster"/"Level Up" dopo il tap.
    Risolve il trigger dell'effetto a catena Issue #9.

    Pre-check: se la lente è già aperta (marker visibile), non rifà il tap
    (eviterebbe toggle chiudi/riapri).

    Ritorna True se la lente è aperta (marker pin_field visibile in ROI),
    False se dopo max_retry tentativi la verifica fallisce.
    """
    tap_lente     = _cfg(ctx, "TAP_LENTE")
    marker_tmpl   = _cfg(ctx, "TMPL_TIPO").get("campo", "pin/pin_field.png")
    marker_soglia = 0.60
    roi           = _cfg(ctx, "ROI_LENTE")

    def _lente_aperta() -> bool:
        screen = ctx.device.screenshot()
        if screen is None:
            return False
        try:
            r = ctx.matcher.find_one(screen, marker_tmpl,
                                      threshold=marker_soglia, zone=roi)
            return r is not None and r.found
        except Exception:
            return False

    # Pre-check: se la lente è già aperta, skip tap (eviterebbe toggle)
    if _lente_aperta():
        ctx.log_msg("[LENTE] già aperta, skip tap")
        return True

    for tentativo in range(1, max_retry + 1):
        ctx.device.tap(tap_lente)
        time.sleep(1.5)
        if _lente_aperta():
            if tentativo > 1:
                ctx.log_msg(f"[LENTE] aperta al tent {tentativo}/{max_retry}")
            return True
        ctx.log_msg(
            f"[LENTE] tap NON ha aperto la lente (tent {tentativo}/{max_retry}) "
            f"— BACK×2 recovery"
        )
        # Doppio BACK per uscire da popup/beast mask/level-up/ecc.
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.8)
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.8)
    ctx.log_msg(f"[LENTE] apertura lente fallita dopo {max_retry} tentativi")
    return False


def _cerca_nodo(ctx: TaskContext, tipo: str,
                livello_override: int = 0) -> bool:
    """
    LENTE → tap tipo × 2 → verifica tipo → livello → CERCA.
    Ritorna True se CERCA eseguita correttamente.
    Se livello_override > 0 sovrascrive il livello di default.

    FIX F 19/04/2026: delay stabilizzazione aumentati
      - dopo tap(tap_lente):          0.8 → 1.5
      - dopo doppio tap(tap_icona):   1.2 → 1.8
      - tap meno livello delay:       0.15 → 0.2
      - tap piu livello delay:        0.2 → 0.25

    FIX 19/04/2026 RT-24: apertura lente verificata via
    `_apri_lente_verificata()` prima di tap_icona. Evita che tap (38,325)
    finisca sulla mappa (bestie) o su popup, con successivo tap_icona su
    UI sbagliata (effetto a catena Issue #9).
    """
    coord_lv    = _cfg(ctx, "COORD_LIVELLO").get(tipo, _cfg(ctx, "COORD_LIVELLO")["campo"])
    # Livello nodo dall'istanza (instances.json → livello), fallback a RACCOLTA_LIVELLO
    livello     = max(1, min(7, int(ctx.config.get("livello", _cfg(ctx, "RACCOLTA_LIVELLO")))))
    if livello_override > 0:
        livello = max(1, min(7, livello_override))
    delay_cerca = _cfg(ctx, "DELAY_CERCA")
    tap_icona   = _cfg(ctx, "TAP_ICONA_TIPO").get(tipo, _cfg(ctx, "TAP_ICONA_TIPO")["campo"])

    ctx.log_msg(f"Raccolta: LENTE → {tipo} Lv.{livello}")
    # FIX RT-24: apertura lente verificata con recovery BACK se finisce su
    # bestie/popup. Se dopo 3 tentativi la lente non si apre → abort tipo.
    if not _apri_lente_verificata(ctx):
        ctx.log_msg(f"Raccolta: impossibile aprire lente per {tipo} — abort")
        return False

    ctx.device.tap(tap_icona)
    ctx.device.tap(tap_icona)
    time.sleep(1.8)                   # FIX F: 1.2 → 1.8

    if not _verifica_tipo(ctx, tipo):
        ctx.log_msg(f"Raccolta: tipo {tipo} NON selezionato — retry tap icona")
        ctx.device.tap(tap_icona)
        time.sleep(1.5)
        if not _verifica_tipo(ctx, tipo):
            ctx.log_msg(f"Raccolta: tipo {tipo} ancora NON selezionato — reset pannello")
            ctx.device.key("KEYCODE_BACK")
            time.sleep(2.0)
            # FIX RT-24: anche qui usa _apri_lente_verificata
            if not _apri_lente_verificata(ctx):
                ctx.log_msg(f"Raccolta: riapertura lente fallita dopo reset — abort")
                return False
            ctx.device.tap(tap_icona)
            ctx.device.tap(tap_icona)
            time.sleep(1.8)           # FIX F: coerenza con doppio tap sopra
            if not _verifica_tipo(ctx, tipo):
                ctx.log_msg(f"Raccolta: tipo {tipo} NON selezionato dopo reset — abort")
                ctx.device.key("KEYCODE_BACK")
                time.sleep(0.5)
                return False

    # auto-WU11 (26/04 ottimizzazione anti-reset): leggi livello già
    # impostato nel pannello. Se == target → skip reset (7× meno + piu ×
    # (target-1)) e tap CERCA diretto. Risparmio: ~1.4s/raccolta + meno
    # tap stress UI. Se OCR fallisce (-1) o livello diverso → procedura
    # standard classica.
    livello_panel = _leggi_livello_panel(ctx, tipo)
    if livello_panel == livello:
        ctx.log_msg(
            f"Raccolta: pannello già su Lv.{livello_panel} == target — "
            f"skip reset"
        )
    elif livello_panel == -1:
        # OCR fallito: NON sappiamo dove siamo → reset+conta classico (sicuro)
        ctx.log_msg(
            f"Raccolta: OCR livello pannello fallito — reset standard "
            f"(7 meno + {livello - 1} piu)"
        )
        for _ in range(7):
            ctx.device.tap(coord_lv["meno"])
            time.sleep(0.2)
        time.sleep(0.3)
        for _ in range(livello - 1):
            ctx.device.tap(coord_lv["piu"])
            time.sleep(0.25)
    else:
        # WU67 (29/04): OCR letto → aggiusta solo del delta (saving 5-12 tap).
        # Pre-fix: SEMPRE 7 meno + N piu (7..13 tap, 1.5-3s).
        # Post-fix: |delta| tap nella direzione giusta (1..6 tap, 0.2-1.5s).
        delta = livello - livello_panel
        if delta > 0:
            ctx.log_msg(
                f"Raccolta: pannello su Lv.{livello_panel} → +{delta} tap "
                f"piu per target Lv.{livello}"
            )
            for _ in range(delta):
                ctx.device.tap(coord_lv["piu"])
                time.sleep(0.25)
        else:  # delta < 0
            ctx.log_msg(
                f"Raccolta: pannello su Lv.{livello_panel} → {abs(delta)} tap "
                f"meno per target Lv.{livello}"
            )
            for _ in range(abs(delta)):
                ctx.device.tap(coord_lv["meno"])
                time.sleep(0.2)

    ctx.device.tap(coord_lv["search"])
    time.sleep(delay_cerca)
    ctx.log_msg(f"Raccolta: CERCA eseguita per {tipo} Lv.{livello}")
    return True


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
    time.sleep(1.5)                   # Slow-PC: 1.3 → 1.5

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

def _salva_debug_panel(label: str, frame, roi, bw, x1: int, y1: int,
                        x2: int, y2: int, tipo: str, instance: str,
                        log_fn=None) -> None:
    """
    Salva 3 immagini di debug per OCR livello pannello:
      - <ts>_<inst>_<tipo>_<label>_full.png   = screenshot completo + box ROI rosso
      - <ts>_<inst>_<tipo>_<label>_roi.png    = solo ROI a risoluzione originale
      - <ts>_<inst>_<tipo>_<label>_roi_bw.png = ROI preprocessato (5x + binario)
    Cartella: debug_task/livello_panel/

    Cap MAX_DEBUG_FILES per evitare accumulo (Issue #59 lesson learned).
    Le immagini più vecchie vengono eliminate quando il cap viene raggiunto.
    """
    MAX_DEBUG_FILES = 60   # 20 set da 3 file
    try:
        import cv2
        import numpy as np
        from datetime import datetime as _dt
        from pathlib import Path as _P
        out_dir = _P(__file__).resolve().parents[1] / "debug_task" / "livello_panel"
        out_dir.mkdir(parents=True, exist_ok=True)
        # Cap rotazione: cancella i file più vecchi se sopra il cap
        existing = sorted(out_dir.glob("*.png"), key=lambda p: p.stat().st_mtime)
        while len(existing) >= MAX_DEBUG_FILES:
            try:
                existing[0].unlink()
                existing.pop(0)
            except Exception:
                break
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"{ts}_{instance}_{tipo}_{label}"
        # Full + box rosso
        full = frame.copy()
        cv2.rectangle(full, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.imwrite(str(out_dir / f"{prefix}_full.png"), full)
        # ROI raw
        cv2.imwrite(str(out_dir / f"{prefix}_roi.png"), roi)
        # ROI preprocessed (PIL → numpy)
        try:
            arr = np.array(bw)
            cv2.imwrite(str(out_dir / f"{prefix}_roi_bw.png"), arr)
        except Exception:
            pass
        if log_fn is not None:
            log_fn(f"[LV-PANEL-DBG] salvati 3 file in debug_task/livello_panel/{prefix}_*.png")
    except Exception as exc:
        if log_fn is not None:
            log_fn(f"[LV-PANEL-DBG] save fallito: {exc}")


def _leggi_livello_panel(ctx: TaskContext, tipo: str) -> int:
    """
    auto-WU11 (26/04 anti-reset): legge il livello correntemente impostato
    nel pannello LENTE (numero visualizzato tra i bottoni "-" e "+").
    ROI calcolata dinamicamente come midpoint(meno, piu) ± 30×20px.

    Usato in _cerca_nodo per evitare il reset (7× meno + piu × (target-1))
    quando il pannello mostra già il livello richiesto.

    Debug 26/04: log dettagliato (ROI coords, testo grezzo, valore parsed)
    + screenshot di verifica solo su FAILURE (debug_task/livello_panel/),
    cap 60 file (20 set × 3 immagini) con rotazione FIFO.

    Ritorna int 1-7 se leggibile, -1 se OCR fallisce o valore fuori range.
    """
    instance = getattr(ctx, "instance_name", "?")
    try:
        import pytesseract
        import os
        from PIL import Image
        pytesseract.pytesseract.tesseract_cmd = os.environ.get(
            "TESSERACT_EXE",
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        )
        coord_lv = _cfg(ctx, "COORD_LIVELLO").get(
            tipo, _cfg(ctx, "COORD_LIVELLO")["campo"]
        )
        # auto-WU13 (26/04 ROI fix verificata su screenshot reali):
        # il testo "Level: X" è ~30px SOPRA i bottoni - / +.
        # Pre-fix: my = midpoint(meno.y, piu.y) ≈ 294 → ROI catturava
        # solo la barra slider tra i bottoni, OCR sempre stringa vuota.
        # Post-fix: my = meno.y - 30 (~265) + ROI larga 140px per
        # contenere "Level: X" intero, psm 7 (single line) + regex.
        mx = (coord_lv["meno"][0] + coord_lv["piu"][0]) // 2
        my = coord_lv["meno"][1] - 30
        x1, y1, x2, y2 = mx - 70, my - 15, mx + 70, my + 15
        screen = ctx.device.screenshot()
        if screen is None:
            ctx.log_msg(f"[LV-PANEL] {tipo} screenshot None — abort")
            return -1
        frame = getattr(screen, "frame", None)
        if frame is None:
            ctx.log_msg(f"[LV-PANEL] {tipo} frame None — abort")
            return -1
        roi = frame[y1:y2, x1:x2]
        pil = Image.fromarray(roi[:, :, ::-1])
        w, h = pil.size
        big = pil.resize((w * 4, h * 4), Image.LANCZOS)
        bw = big.convert("L").point(lambda p: 255 if p > 130 else 0)
        cfg_ocr = ("--psm 7 -c tessedit_char_whitelist="
                   "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789:. ")
        testo_raw = pytesseract.image_to_string(bw, config=cfg_ocr).strip()
        m = _re.search(r"[Ll]evel\s*:?\s*(\d+)", testo_raw)
        if m is None:
            # Fallback: cerca solo cifra isolata (in caso "Level:" non leggibile)
            m = _re.search(r"\b(\d)\b", testo_raw)
        ctx.log_msg(
            f"[LV-PANEL] {tipo} ROI=({x1},{y1},{x2},{y2}) "
            f"OCR='{testo_raw!r}' match={m.group(1) if m else None}"
        )
        if not m:
            # DEBUG DISATTIVATO 26/04/2026 — ROI fix verificata su screenshot
            # reali (auto-WU13). Per riabilitare: decommenta la chiamata sotto.
            # _salva_debug_panel("nomatch", frame, roi, bw, x1, y1, x2, y2,
            #                    tipo, instance, log_fn=ctx.log_msg)
            return -1
        val = int(m.group(1))
        if 1 <= val <= 7:
            return val
        # Valore fuori range → debug (DISATTIVATO, decommenta per riabilitare)
        # _salva_debug_panel(f"oor{val}", frame, roi, bw, x1, y1, x2, y2,
        #                    tipo, instance, log_fn=ctx.log_msg)
        return -1
    except Exception as exc:
        ctx.log_msg(f"[LV-PANEL] {tipo} eccezione: {exc}")
        return -1


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
            # WU55 — data collection HOME sample post-marcia
            if bool(_cfg(ctx, "RACCOLTA_OCR_DEBUG")):
                try:
                    from shared.ocr_dataset import new_pair_id, save_home_sample
                    pid = new_pair_id()
                    save_home_sample(
                        istanza=ctx.instance_name,
                        pair_id=pid,
                        screen=screen,
                        ocr_raw=f"{attive}/{totale}",
                        attive=attive,
                        totale=totale,
                        extra={"trigger": "_leggi_attive_post_marcia",
                               "schermata": "HOME", "retry": i},
                    )
                    ctx._ocr_pair = (pid, attive, totale)  # type: ignore
                    ctx.log_msg(f"[OCR-DEBUG] home post-marcia pair={pid} {attive}/{totale}")
                except Exception as exc:
                    ctx.log_msg(f"[OCR-DEBUG] save post-marcia fail: {exc}")
            return attive
        ctx.log_msg(f"[POST-MARCIA] OCR contatore N/D (tentativo {i+1}/{retry})")
        time.sleep(sleep_s)
    return -1


# ==============================================================================
# FIX G 19/04/2026 — _GatherResult: firma coerente per _tap_nodo_e_verifica_gather
# ==============================================================================

@dataclass
class _GatherResult:
    """
    Risultato di _tap_nodo_e_verifica_gather().
    ok     = True se popup nodo è stato aperto con pin_gather visibile.
    screen = screenshot del popup (per uso successivo: territorio, livello).
    """
    ok: bool
    screen: Optional[object] = None


# ==============================================================================
# FIX B 19/04/2026 — _reset_to_mappa: funzione centralizzata reset UI
# ==============================================================================

def _reset_to_mappa(ctx: TaskContext, obiettivo: int) -> int:
    """
    Porta il sistema in posizione iniziale pulita dopo qualsiasi percorso
    di scarto (blacklist fuori, tipo_bloccato, skip_neutro, fallimento).

    Sequenza: vai_in_home() → leggi_contatore_slot() → vai_in_mappa()

    Ritorna: attive_reali (int >= 0) oppure -1 se OCR fallisce o
             ctx.navigator è None.
    """
    if ctx.navigator is None:
        return -1
    ctx.navigator.vai_in_home()
    time.sleep(1.0)
    attive = -1
    try:
        from shared.ocr_helpers import leggi_contatore_slot
        screen = ctx.device.screenshot()
        if screen is not None:
            att, _ = leggi_contatore_slot(screen, totale_noto=obiettivo)
            if 0 <= att <= obiettivo:
                attive = att
    except Exception:
        pass
    ctx.navigator.vai_in_mappa()
    time.sleep(1.5)
    # WU55 — shadow OCR MAP appaiata al HOME post-marcia (ctx._ocr_pair settato
    # da _leggi_attive_post_marcia). Skip silente se pair=None (fallimento/scarto).
    _ocr_debug_collect_map(ctx)
    return attive


def _aggiorna_slot_in_mappa(ctx: TaskContext, obiettivo: int,
                              attive_pre: int) -> int:
    """
    WU55 28/04/2026 — Refactor: legge slot DIRETTAMENTE in mappa post-marcia
    OK, senza vai_in_home → vai_in_mappa. Risparmio ~10-15s per marcia.

    Affidabilità validata: 97.2% MAP coincide con HOME (35/36 sample post-marcia
    nel dataset OCR WU55, tag rollback `wu55-pre-refactor-mappa`).

    Guardrail Scenario E (popup overlay scuro): se OCR MAP ritorna `(0, N)` da
    pre-check vuoto MA `attive_pre >= 1`, è ambiguo (potrebbe essere falso
    positivo). Fallback singolo a HOME per disambiguare.

    Sanity check: se `attive > obiettivo` (es. "5" letto come "7") → assume
    obiettivo (slot pieni, conservativo, già documentato CLAUDE.md).

    Args:
        ctx:        TaskContext con navigator/device.
        obiettivo:  totale slot noto (max squadre).
        attive_pre: attive prima dell'invio marcia (>=0 atteso).

    Returns:
        attive (int 0..obiettivo) — slot occupati dopo la marcia.
        -1 se ctx.navigator None oppure OCR completamente fallito.

    Rollback: `git checkout wu55-pre-refactor-mappa -- tasks/raccolta.py`
    """
    if ctx.navigator is None:
        return -1

    try:
        from shared.ocr_helpers import leggi_contatore_slot
    except ImportError:
        return -1

    # Stabilizzazione mappa post-tap (chiusura maschera marcia → mappa pulita)
    time.sleep(1.5)
    screen_map = ctx.device.screenshot() if ctx.device else None
    if screen_map is None:
        ctx.log_msg("[SLOT-MAP] screenshot None — fallback _reset_to_mappa")
        return _reset_to_mappa(ctx, obiettivo)

    attive_map, totale_map = leggi_contatore_slot(
        screen_map, totale_noto=obiettivo
    )

    # Sanity check: attive > totale = OCR sbagliato (es. "4" letto "7")
    if 0 <= attive_map and attive_map > obiettivo:
        ctx.log_msg(
            f"[SLOT-MAP] OCR anomalo attive={attive_map}>obiettivo={obiettivo} "
            f"— assume slot pieni (conservativo)"
        )
        return obiettivo

    # Guardrail Scenario E: MAP (0, N) MA attive_pre >= 1 → ambiguo
    # (popup overlay che oscura contatore, falso positivo "no counter")
    if attive_map == 0 and attive_pre >= 1:
        ctx.log_msg(
            f"[SLOT-MAP] MAP=(0,{totale_map}) ma attive_pre={attive_pre} "
            f"— Scenario E ambiguo → fallback HOME singolo"
        )
        return _reset_to_mappa(ctx, obiettivo)

    # WU68 (29/04 sera) — Sanity check deterministico: bot ha appena
    # confermato l'invio di +1 squadra, quindi `attive_pre` rappresenta il
    # totale atteso post-marcia (= attive_pre_marcia + 1). Reale dovrebbe
    # essere ≥ attive_pre. Eccezione: 1 squadra rientrata durante la marcia
    # (~15-20s, raro). Se OCR MAP < attive_pre → sospetto bug OCR (es. "5"
    # letto come "4", opposto del pattern 4↔7 già coperto da cross-validation
    # in ocr_helpers, che scatta solo per attive>totale). Fallback HOME
    # singolo per disambiguare:
    #   - bug OCR ("5"→"4") → HOME ground-truth corregge a 5
    #   - rientro reale → HOME conferma 4
    # Bug osservato 29/04 sera: 5/5 letto come 4/5 → bot inviava 6° squadra
    # fittizia. Costo fix: ~13-15s solo nei casi sospetti (~2-3%).
    if 0 <= attive_map < attive_pre:
        ctx.log_msg(
            f"[SLOT-MAP] sanity: attive_map={attive_map} < attive_pre={attive_pre} "
            f"— sospetto bug OCR (just sent +1, atteso ≥{attive_pre}) → fallback HOME"
        )
        return _reset_to_mappa(ctx, obiettivo)

    # Lettura accettabile in mappa
    if 0 <= attive_map <= obiettivo:
        ctx.log_msg(
            f"[SLOT-MAP] OCR MAP attive={attive_map}/{obiettivo} (pre={attive_pre})"
        )
        return attive_map

    # OCR fallito (-1, -1) → fallback HOME conservativo
    ctx.log_msg(
        f"[SLOT-MAP] OCR fallito ({attive_map},{totale_map}) — fallback HOME"
    )
    return _reset_to_mappa(ctx, obiettivo)


# ==============================================================================
# Sequenza UI principale
# ==============================================================================

def _tap_nodo_e_verifica_gather(ctx: TaskContext, tipo: str) -> _GatherResult:
    """
    Tap nodo → verifica pin_gather visibile.
    Ritorna _GatherResult(ok=True, screen=screen) se popup aperto
    oppure _GatherResult(ok=False) in caso di errore.
    NON verifica territorio — viene fatto nel chiamante dopo OCR coordinate.

    FIX F 19/04/2026: delay stabilizzazione aumentati
      - dopo tap nodo:        1.0 → 1.5
      - dopo retry tap nodo:  1.5 → 2.0
    FIX G 19/04/2026: return _GatherResult dataclass invece di tuple/str.
    """
    tap_nodo        = _cfg(ctx, "TAP_NODO")
    template_gather = _cfg(ctx, "TEMPLATE_GATHER")
    soglia          = _cfg(ctx, "TEMPLATE_SOGLIA")
    roi_gather      = _cfg(ctx, "ROI_GATHER")

    ctx.log_msg(f"Raccolta [{tipo}]: tap nodo {tap_nodo}")
    ctx.device.tap(tap_nodo)
    time.sleep(1.5)                   # FIX F: 1.0 → 1.5

    screen = ctx.device.screenshot()
    if not screen:
        return _GatherResult(ok=False)

    r = ctx.matcher.find_one(screen, template_gather, threshold=soglia, zone=roi_gather)
    ctx.log_msg(f"Raccolta [{tipo}]: pin_gather score={r.score:.3f} → "
                f"{'OK' if r.found else 'NON trovato'}")

    if not r.found:
        ctx.log_msg(f"Raccolta [{tipo}]: GATHER non visibile — retry tap nodo")
        ctx.device.tap(tap_nodo)
        time.sleep(2.0)               # FIX F: 1.5 → 2.0
        screen2 = ctx.device.screenshot()
        if screen2:
            r2 = ctx.matcher.find_one(screen2, template_gather, threshold=soglia, zone=roi_gather)
            ctx.log_msg(f"Raccolta [{tipo}]: pin_gather retry score={r2.score:.3f} → "
                        f"{'OK' if r2.found else 'NON trovato'}")
            if r2.found:
                return _GatherResult(ok=True, screen=screen2)
            else:
                ctx.device.key("KEYCODE_BACK")
                time.sleep(0.5)
                return _GatherResult(ok=False)
        else:
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.5)
            return _GatherResult(ok=False)

    return _GatherResult(ok=True, screen=screen)


def _esegui_marcia(ctx: TaskContext, n_truppe: int,
                   screen_maschera=None) -> tuple[bool, Optional[int]]:
    """
    Sequenza UI: RACCOGLI → SQUADRA → (truppe) → OCR ETA → MARCIA.
    Ritorna (ok, eta_s).
    Step 2: OCR ETA dalla maschera pre-MARCIA.

    FIX F 19/04/2026: delay stabilizzazione aumentati
      - dopo tap_raccogli:       0.5 → 0.8
      - dopo tap_squadra:        1.4 → 1.8
      - dopo retry tap_squadra:  1.8 → 2.2
      - dopo tap_marcia:         0.8 → 1.2
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

    # WU69 — flag "maschera non aperta" per pattern detection slot pieni.
    # Reset all'inizio di ogni invio. Settato a True solo se "maschera ancora
    # non aperta" e pin_no_squads NON trovato. Il caller (_loop_invio_marce)
    # conta gli streak e se >= 2 deduce slot pieni → break + flag.
    ctx._raccolta_mask_not_opened = False  # type: ignore[attr-defined]

    ctx.log_msg("Raccolta: RACCOGLI → SQUADRA")
    ctx.device.tap(tap_raccogli)
    time.sleep(0.8)                   # FIX F: 0.5 → 0.8
    ctx.device.tap(tap_squadra)
    time.sleep(1.8)                   # FIX F: 1.4 → 1.8

    # Verifica maschera invio aperta
    screen = ctx.device.screenshot()
    if screen:
        maschera = ctx.matcher.find_one(screen, template_marcia, threshold=soglia)
        if maschera.found:
            ctx.log_msg(f"Raccolta: maschera invio aperta score={maschera.score:.3f} → OK")
        else:
            ctx.log_msg(f"Raccolta: maschera NON aperta score={maschera.score:.3f} — retry")
            ctx.device.tap(tap_squadra)
            time.sleep(2.2)           # FIX F: 1.8 → 2.2
            screen = ctx.device.screenshot()
            if screen:
                m2 = ctx.matcher.find_one(screen, template_marcia, threshold=soglia)
                if not m2.found:
                    # F3: prima di FALLITO, check pin_no_squads (maschera
                    # aperta ma senza squadre disponibili -> uscita raccolta)
                    m_ns = ctx.matcher.find_one(
                        screen, _cfg(ctx, "TEMPLATE_NO_SQUADS"),
                        threshold=_cfg(ctx, "SOGLIA_NO_SQUADS"),
                    )
                    if m_ns.found:
                        ctx.log_msg(
                            f"Raccolta: rilevato 'No Squads' score={m_ns.score:.3f} — "
                            f"nessuna squadra disponibile"
                        )
                        ctx.device.key("KEYCODE_BACK")
                        time.sleep(0.3)
                        ctx._raccolta_no_squads = True
                        return False, None
                    # WU69 — segnale "maschera non si apre" (slot pieni candidato).
                    # Solo se NON è "No Squads" e la maschera non si è aperta a
                    # nessuno dei 2 tentativi → segnale al loop di tracciare lo
                    # streak. 2 streak su tipi diversi → conclude slot pieni.
                    ctx._raccolta_mask_not_opened = True  # type: ignore[attr-defined]
                    ctx.log_msg("Raccolta: maschera ancora non aperta — FALLITO")
                    return False, None
                ctx.log_msg(f"Raccolta: maschera aperta al retry score={m2.score:.3f} → OK")

    # Check pin_no_squads anche con maschera aperta: se l'overlay
    # "No Squads" è visibile nonostante la maschera, non ci sono
    # squadre disponibili → uscita immediata dal processo raccolta.
    if screen is not None:
        m_ns = ctx.matcher.find_one(
            screen, _cfg(ctx, "TEMPLATE_NO_SQUADS"),
            threshold=_cfg(ctx, "SOGLIA_NO_SQUADS"),
        )
        if m_ns.found:
            ctx.log_msg(
                f"Raccolta: rilevato 'No Squads' score={m_ns.score:.3f} "
                f"(maschera aperta) — nessuna squadra disponibile"
            )
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.3)
            ctx._raccolta_no_squads = True
            return False, None

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
    time.sleep(1.5)                   # Slow-PC: 1.2 → 1.5

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
    FIX A 19/04/2026 — Sequenza logica riscritta:

      1. _cerca_nodo(tipo, livello) + _leggi_coord_nodo
         → se chiave in blacklist_fuori → _reset_to_mappa → prova lv successivo
         → se chiave in blacklist RAM → retry CERCA stesso lv; ancora
           occupato → tipo_bloccato
         → altrimenti: break (usa questo nodo)
         → se nessun lv ha dato nodo utile → skip_neutro
      2. blacklist.reserve(chiave) — prenota PRIMA del tap
      3. _tap_nodo_e_verifica_gather(tipo)
         → se fallisce: rollback + _reset_to_mappa → fallimento puro
      4. _nodo_in_territorio(screen)
         → FUORI: blacklist_fuori.aggiungi + rollback + _reset_to_mappa
                  → skip_neutro
      5. _leggi_livello_nodo(screen)
         → < MIN: blacklist.commit + _reset_to_mappa → tipo_bloccato
      6. _esegui_marcia(n_truppe)
         → se fallisce: rollback + _reset_to_mappa → fallimento puro
      7. blacklist.commit(chiave, eta_s) → ok=True

    FIX E 19/04/2026: sequenza_livelli semplificata (rimosso Lv.5)
      base=7 → [7, 6], base=6 → [6, 7]

    Ritorna (marcia_ok, tipo_bloccato, skip_neutro).
    """
    # FIX E: sequenza livelli [base, 7] o [7, 6] — rimosso Lv.5
    livello_base = max(1, min(7, int(
        ctx.config.get("livello", _cfg(ctx, "RACCOLTA_LIVELLO"))
    )))
    if livello_base == 7:
        sequenza_livelli = [7, 6]
    else:
        # livello_base == 6 (o altro base): prova base, poi 7
        seq = [livello_base, 7]
        seen: set[int] = set()
        sequenza_livelli = [lv for lv in seq
                            if lv not in seen and not seen.add(lv)]

    # ─── Step 1-2: CERCA + leggi coord + check blacklist ──────────────────
    chiave: Optional[str] = None
    chiave_test: Optional[str] = None

    for lv in sequenza_livelli:
        ctx.log_msg(f"Raccolta: tentativo CERCA {tipo} Lv.{lv}")
        ok = _cerca_nodo(ctx, tipo, livello_override=lv)
        if not ok:
            # Tipo NON selezionato — problema UI, inutile cambiare livello
            ctx.log_msg(
                f"Raccolta [{tipo}]: tipo NON selezionato — abort sequenza livelli"
            )
            return False, True, False  # tipo_bloccato

        chiave_test = _leggi_coord_nodo(ctx)

        # ── Lista risultati vuota: prova livello successivo ────────────
        if chiave_test is None:
            ctx.log_msg(
                f"Raccolta: nessun nodo disponibile a Lv.{lv} — "
                f"provo livello successivo"
            )
            _reset_to_mappa(ctx, obiettivo)
            continue

        # ── Blacklist FUORI (disco): prova livello successivo ──────────
        # WU50: bypass se modalità fuori_territorio attiva → considera ammesso
        _fuori_terr_ok = bool(_cfg(ctx, "RACCOLTA_FUORI_TERRITORIO_ABILITATA"))
        if blacklist_fuori.contiene(chiave_test) and not _fuori_terr_ok:
            ctx.log_msg(
                f"Raccolta [{tipo}] Lv.{lv}: nodo {chiave_test} "
                f"in blacklist fuori — provo livello successivo"
            )
            _reset_to_mappa(ctx, obiettivo)
            continue

        # ── Blacklist DINAMICA (RAM): retry CERCA stesso livello ──────
        if blacklist.contiene(chiave_test):
            eta_prev = blacklist.get_eta(chiave_test)
            if isinstance(eta_prev, (int, float)) and eta_prev > 0:
                marg    = int(_cfg(ctx, "ETA_MARGINE_S"))
                att_min = int(_cfg(ctx, "ETA_MIN_S"))
                attesa  = int(min(_cfg(ctx, "BLACKLIST_ATTESA_NODO"),
                                  max(att_min, eta_prev + marg)))
                ctx.log_msg(
                    f"Raccolta [{tipo}]: nodo {chiave_test} in blacklist RAM "
                    f"(ETA={int(eta_prev)}s) — cooldown {attesa}s, retry CERCA"
                )
            else:
                attesa = int(_cfg(ctx, "BLACKLIST_ATTESA_NODO"))
                ctx.log_msg(
                    f"Raccolta [{tipo}]: nodo {chiave_test} in blacklist RAM "
                    f"— cooldown {attesa}s (TTL fisso), retry CERCA"
                )
            cooldown_map[tipo] = time.time() + attesa

            # Retry CERCA per nodo diverso allo stesso livello
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.5)
            if not _cerca_nodo(ctx, tipo, livello_override=lv):
                ctx.log_msg(
                    f"Raccolta [{tipo}]: CERCA retry fallita — tipo bloccato"
                )
                return False, True, False
            chiave2 = _leggi_coord_nodo(ctx)
            if chiave2 is None or chiave2 == chiave_test or blacklist.contiene(chiave2):
                ctx.log_msg(
                    f"Raccolta [{tipo}]: secondo nodo ancora occupato "
                    f"— tipo bloccato"
                )
                _reset_to_mappa(ctx, obiettivo)
                return False, True, False
            # WU50: bypass se modalità fuori_territorio attiva
            if blacklist_fuori.contiene(chiave2) and not _fuori_terr_ok:
                ctx.log_msg(
                    f"Raccolta [{tipo}]: secondo nodo {chiave2} "
                    f"in blacklist fuori — skip neutro"
                )
                _reset_to_mappa(ctx, obiettivo)
                return False, False, True
            chiave_test = chiave2
            # Cade nel blocco "nodo OK" sotto

        # ── Nodo utile trovato ─────────────────────────────────────────
        chiave = chiave_test
        ctx.log_msg(f"Raccolta: nodo trovato a Lv.{lv} — procedo")
        break

    if chiave is None:
        # Tutti i livelli hanno restituito lista vuota o blacklist_fuori
        ctx.log_msg(
            f"Raccolta [{tipo}]: nessun nodo utile su livelli "
            f"{sequenza_livelli} — skip neutro"
        )
        _reset_to_mappa(ctx, obiettivo)
        return False, False, True

    # ─── Step 2b: RESERVE prima del tap (FIX A) ─────────────────────────
    blacklist.reserve(chiave)
    ctx.log_msg(f"Raccolta [{tipo}]: nodo {chiave} RESERVED")

    # ─── Step 3: tap nodo + verifica gather ─────────────────────────────
    gather_result = _tap_nodo_e_verifica_gather(ctx, tipo)
    if not gather_result.ok:
        ctx.log_msg(f"Raccolta [{tipo}]: tap nodo fallito — rollback")
        blacklist.rollback(chiave)
        _reset_to_mappa(ctx, obiettivo)
        return False, False, False
    screen_popup = gather_result.screen

    # ─── Step 4: verifica territorio (PRIMA del livello per early abort) ─
    # WU50: in modalità fuori_territorio bypass del check (procede comunque
    # senza blacklist + senza rollback). Caso d'uso: castle in zona dove
    # tutti i nodi sono fuori territorio.
    _fuori_terr_ok = bool(_cfg(ctx, "RACCOLTA_FUORI_TERRITORIO_ABILITATA"))
    if (screen_popup is not None and not _fuori_terr_ok
            and not _nodo_in_territorio(screen_popup, tipo, ctx)):
        ctx.log_msg(
            f"Raccolta [{tipo}]: nodo {chiave} FUORI territorio — "
            f"blacklist fuori + rollback"
        )
        blacklist_fuori.aggiungi(chiave, tipo)
        blacklist.rollback(chiave)
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.5)
        _reset_to_mappa(ctx, obiettivo)
        return False, False, True  # skip neutro
    elif _fuori_terr_ok and screen_popup is not None:
        # Log diagnostico (one-shot per nodo): sappiamo se IN o FUORI ma
        # andiamo avanti comunque. Utile per analisi performance senza buff.
        try:
            in_terr = _nodo_in_territorio(screen_popup, tipo, ctx)
            ctx.log_msg(
                f"Raccolta [{tipo}]: modalità fuori_territorio attiva — "
                f"nodo {chiave} {'IN' if in_terr else 'FUORI'} territorio (procedo)"
            )
        except Exception:
            pass

    # ─── Step 5: verifica livello nodo ──────────────────────────────────
    if screen_popup is not None:
        livello_nodo = _leggi_livello_nodo(ctx, screen_popup)
        livello_min  = int(_cfg(ctx, "RACCOLTA_LIVELLO_MIN"))
        if livello_nodo != -1 and livello_nodo < livello_min:
            ctx.log_msg(
                f"Raccolta [{tipo}]: nodo Lv.{livello_nodo} < min {livello_min} "
                f"— blacklist + tipo bloccato"
            )
            blacklist.commit(chiave, eta_s=None)
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.5)
            _reset_to_mappa(ctx, obiettivo)
            return False, True, False
        elif livello_nodo != -1:
            ctx.log_msg(f"Raccolta [{tipo}]: nodo Lv.{livello_nodo} ✓")

    # ─── Step 6: esegui marcia ──────────────────────────────────────────
    ok, eta_s = _esegui_marcia(ctx, n_truppe)
    if not ok:
        ctx.log_msg(f"Raccolta [{tipo}]: marcia FALLITA — rollback")
        blacklist.rollback(chiave)
        _reset_to_mappa(ctx, obiettivo)
        return False, False, False

    # Lettura contatore post-marcia (solo informativa — marcia già
    # confermata visivamente dalla chiusura della maschera).
    time.sleep(1.5)
    attive_dopo = _leggi_attive_post_marcia(ctx, obiettivo)
    if attive_dopo >= 0:
        ctx.log_msg(f"Raccolta [{tipo}]: marcia OK — attive post={attive_dopo}")
    else:
        ctx.log_msg(
            f"Raccolta [{tipo}]: marcia OK — contatore N/D "
            f"(marcia confermata visivamente)"
        )

    # ─── Step 7: COMMIT con ETA dinamica ────────────────────────────────
    blacklist.commit(chiave, eta_s=eta_s)
    ttl_log = f"ETA={eta_s}s" if eta_s else f"TTL={_cfg(ctx, 'BLACKLIST_COMMITTED_TTL')}s"
    ctx.log_msg(f"Raccolta [{tipo}]: nodo {chiave} COMMITTED ({ttl_log})")

    # auto-WU14 step2: hook produzione — incrementa truppe raccolta inviate
    try:
        if hasattr(ctx, "state") and ctx.state and ctx.state.produzione_corrente:
            ctx.state.produzione_corrente.incrementa_truppe(1)
    except Exception as exc:
        ctx.log_msg(f"[PROD] hook raccolta: {exc}")

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
                       blacklist_fuori: Optional[BlacklistFuori] = None) -> int:
    """
    Loop invio squadre fino a slot pieni o MAX_FALLIMENTI.

    FIX C 19/04/2026: dopo ogni ok=True → _reset_to_mappa per leggere
                      slot reali da HOME e aggiornare attive_correnti.
    FIX D 19/04/2026: idx_seq sostituito da iteratore sulla sequenza
                      ricalcolata ad ogni giro while; se ok=True → break
                      dal for → ricalcola al prossimo giro.

    Gestione risultati di _invia_squadra():
      - ok=True: incrementa inviate, _reset_to_mappa, aggiorna attive_correnti,
        break se slot pieni o comunque ricalcola sequenza
      - skip_neutro: contatore +1, block tipo se >= 2, continue
      - tipo_bloccato: aggiunge a tipi_bloccati, continue
      - fallimento puro: fallimenti_cons +1, continue
    """
    # FIX B/C: blacklist_fuori ora opzionale per facilità test
    if blacklist_fuori is None:
        blacklist_fuori = BlacklistFuori(
            data_dir=_cfg(ctx, "BLACKLIST_FUORI_DIR")
        )

    max_fallimenti = _cfg(ctx, "RACCOLTA_MAX_FALLIMENTI")
    n_truppe       = int(ctx.config.get("truppe", _cfg(ctx, "RACCOLTA_TRUPPE")))
    deposito_ocr   = getattr(ctx, "_deposito_ocr", {})
    sequenza_base  = _cfg(ctx, "RACCOLTA_SEQUENZA")

    # Issue #26 — target allocazione risorse da ctx.config (frazioni 0-1).
    # Chiavi in formato "tipo" (campo/segheria/petrolio/acciaio) per matching
    # con _RATIO_TARGET_DEFAULT in _calcola_sequenza_allocation.
    ratio_cfg = {
        "campo":    float(getattr(ctx.config, "ALLOCAZIONE_POMODORO", 0.35)),
        "segheria": float(getattr(ctx.config, "ALLOCAZIONE_LEGNO",    0.35)),
        "petrolio": float(getattr(ctx.config, "ALLOCAZIONE_PETROLIO", 0.20)),
        "acciaio":  float(getattr(ctx.config, "ALLOCAZIONE_ACCIAIO",  0.10)),
    }

    tipi_bloccati: set[str]              = set()
    cooldown_map: dict[str, float]       = {}
    skip_neutri_per_tipo: dict[str, int] = {}

    attive_correnti = attive_inizio
    inviate         = 0
    fallimenti_cons = 0
    # WU69 — streak fallimenti "maschera non aperta" consecutivi (slot pieni
    # detection deterministica via pattern UI: la maschera non si apre se gli
    # slot squadra sono tutti occupati, indipendentemente da OCR slot iniziale).
    mask_not_opened_streak = 0
    SOGLIA_MASK_STREAK     = 2  # >= 2 fallimenti su tipi diversi → slot pieni

    # Safety: limite totale invii per evitare loop infiniti
    max_invii    = obiettivo * max(2, max_fallimenti) + 5
    invii_totali = 0

    while (attive_correnti < obiettivo
           and fallimenti_cons < max_fallimenti
           and invii_totali < max_invii):

        # ── Check: tutti i tipi bloccati? ──
        if set(_TUTTI_I_TIPI).issubset(tipi_bloccati):
            ctx.log_msg("Raccolta: tutti i tipi bloccati — uscita")
            break

        # ── Check: tutti i tipi disponibili in cooldown? → attendi ──
        tipi_disponibili = [t for t in _TUTTI_I_TIPI if t not in tipi_bloccati]
        ora = time.time()
        pronti = [t for t in tipi_disponibili if cooldown_map.get(t, 0) <= ora]
        if not pronti and tipi_disponibili:
            t_min  = min(cooldown_map.get(t, ora) for t in tipi_disponibili)
            wait_s = max(1, int(t_min - ora))
            ctx.log_msg(f"Raccolta: tutti i tipi in cooldown — attendo {wait_s}s")
            time.sleep(wait_s)
            continue

        # ── FIX D: ricalcola sequenza ad ogni iterazione ──
        libere_ora = obiettivo - attive_correnti
        if deposito_ocr:
            sequenza = _calcola_sequenza_allocation(libere_ora, deposito_ocr,
                                                     ratio_target=ratio_cfg)
            sequenza = [t for t in sequenza if t not in tipi_bloccati] or \
                       _calcola_sequenza(libere_ora, sequenza_base, tipi_bloccati)
        else:
            sequenza = _calcola_sequenza(libere_ora, sequenza_base, tipi_bloccati)

        # Interleave: alterna tipi per evitare attese sullo stesso nodo
        sequenza = _interleave(sequenza)

        if not sequenza:
            ctx.log_msg("Raccolta: sequenza vuota — abbandono")
            break

        # ── FIX D: itera sulla sequenza in ordine — consuma tipo per tipo ──
        # Se ok=True → break dal for → ricalcola sequenza al prossimo while
        for tipo in sequenza:
            if attive_correnti >= obiettivo:
                break
            if fallimenti_cons >= max_fallimenti:
                break
            if invii_totali >= max_invii:
                break
            if tipo in tipi_bloccati:
                continue
            if cooldown_map.get(tipo, 0) > time.time():
                continue

            invii_totali += 1
            ctx.log_msg(
                f"Raccolta: invio squadra {attive_correnti + 1}/{obiettivo} "
                f"→ {tipo} (fallimenti_cons={fallimenti_cons}/{max_fallimenti})"
            )

            ok, tipo_bloccato, skip_neutro = _invia_squadra(
                ctx, tipo, blacklist, blacklist_fuori,
                cooldown_map, n_truppe, tipi_bloccati, obiettivo
            )

            # F3 — uscita immediata dal for tipo se rilevato "No Squads".
            # NON reset del flag qui: il while esterno (in RaccoltaTask.run)
            # controllerà il flag dopo _loop_invio_marce per uscire dal ciclo.
            if getattr(ctx, "_raccolta_no_squads", False):
                ctx.log_msg("Raccolta: 'No Squads' — uscita immediata loop")
                break

            # ── CASO ok=True ─────────────────────────────────────────
            if ok:
                inviate         += 1
                attive_pre_marcia = attive_correnti
                attive_correnti += 1
                fallimenti_cons  = 0
                mask_not_opened_streak = 0  # WU69 — reset streak su invio OK
                skip_neutri_per_tipo[tipo] = 0
                ctx.log_msg(
                    f"Raccolta: squadra confermata ({attive_correnti}/{obiettivo})"
                )
                time.sleep(_cfg(ctx, "DELAY_POST_MARCIA"))

                # WU55 28/04: verifica slot direttamente in mappa (no più
                # vai_in_home → OCR → vai_in_mappa). Risparmio ~10-15s/marcia.
                # Guardrail Scenario E: se MAP=(0,N) ma attive_pre>=1 →
                # fallback HOME singolo (popup overlay ambiguità).
                # Rollback: git checkout wu55-pre-refactor-mappa -- tasks/raccolta.py
                attive_reali = _aggiorna_slot_in_mappa(
                    ctx, obiettivo, attive_pre_marcia + 1
                )
                if attive_reali >= 0:
                    if attive_reali != attive_correnti:
                        ctx.log_msg(
                            f"Raccolta: [RIALLINEA] attive "
                            f"{attive_correnti}→{attive_reali} "
                            f"(OCR post-marcia in MAPPA)"
                        )
                    attive_correnti = attive_reali
                ctx.log_msg(
                    f"Raccolta: slot post-marcia OCR="
                    f"{attive_correnti}/{obiettivo}"
                )

                if attive_correnti >= obiettivo:
                    ctx.log_msg(
                        f"Raccolta: slot pieni ({attive_correnti}/{obiettivo}) "
                        f"— uscita"
                    )
                    break  # esce dal for; il while terminerà
                # FIX D: esce dal for per ricalcolare sequenza al prossimo while
                break

            # ── CASO skip_neutro ─────────────────────────────────────
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
                        f"Raccolta: tipo '{tipo}' bloccato dopo {n_skip} "
                        f"skip neutri consecutivi"
                    )
                    if set(_TUTTI_I_TIPI).issubset(tipi_bloccati):
                        ctx.log_msg("Raccolta: tutti i tipi bloccati — uscita")
                        break
                continue  # prossimo tipo nella sequenza

            # ── CASO tipo_bloccato ───────────────────────────────────
            if tipo_bloccato:
                tipi_bloccati.add(tipo)
                ctx.log_msg(
                    f"Raccolta: tipo '{tipo}' bloccato per questo ciclo"
                )
                if set(_TUTTI_I_TIPI).issubset(tipi_bloccati):
                    ctx.log_msg("Raccolta: tutti i tipi bloccati — uscita")
                    break
                continue

            # ── CASO fallimento puro ─────────────────────────────────
            # _reset_to_mappa già chiamato dentro _invia_squadra
            fallimenti_cons += 1

            # WU69 — pattern detection slot pieni: se "maschera non aperta" è
            # il sintomo specifico (flag settato in _esegui_marcia), incrementa
            # streak. >= SOGLIA su tipi diversi consecutivi = slot pieni
            # deterministico (la maschera non si apre se tutti gli slot squadra
            # sono occupati, indipendentemente dal valore letto via OCR).
            if getattr(ctx, "_raccolta_mask_not_opened", False):
                mask_not_opened_streak += 1
                ctx.log_msg(
                    f"Raccolta: maschera_not_opened streak="
                    f"{mask_not_opened_streak}/{SOGLIA_MASK_STREAK}"
                )
                if mask_not_opened_streak >= SOGLIA_MASK_STREAK:
                    ctx.log_msg(
                        f"Raccolta: {mask_not_opened_streak} fallimenti maschera "
                        f"consecutivi su tipi diversi → slot pieni dedotti, "
                        f"uscita immediata"
                    )
                    ctx._raccolta_slot_pieni = True  # type: ignore[attr-defined]
                    break  # esce dal for; il while terminerà
            else:
                # Fallimento per altra causa (es. nodo perso, marcia errata) →
                # reset streak (lo streak deve essere puro "mask_not_opened")
                mask_not_opened_streak = 0
            continue

        # F3 — dopo il for: se flag No Squads True, esci anche dal while
        # interno. Il chiamante (RaccoltaTask.run) leggerà il flag e uscirà
        # dal while esterno. Senza questo break, il while qui rientrerebbe,
        # il for ri-detecterebbe No Squads, loop finché invii_totali >= max.
        if getattr(ctx, "_raccolta_no_squads", False):
            break

    # ── Fine while: log finale slot da HOME ──
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

    Nota: schedule_type "periodic" è mantenuto per retrocompatibilità;
    in produzione main.py tratta RaccoltaTask come always-run (interval=0).
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

        # Issue #64 — sync con rifornimento: se l'ultima spedizione rifornimento
        # è ancora in volo, gli slot squadra OCR risulterebbero occupati. Wait
        # SEMPRE fino al rientro per leggere slot reali (no soglia, no skip).
        # Cap safety 600s (10 min) per evitare blocco indefinito su ts corrotto.
        # Issue futura #65: quando wait>60s, anticipare task post-raccolta nel
        # tempo morto e tornare a raccolta dopo aver verificato il rientro.
        try:
            if hasattr(ctx, "state") and ctx.state is not None:
                rif_state = getattr(ctx.state, "rifornimento", None)
                eta_iso = getattr(rif_state, "eta_rientro_ultima", None) if rif_state else None
                if eta_iso:
                    from datetime import datetime as _dt, timezone as _tz
                    ts_rientro = _dt.fromisoformat(eta_iso)
                    wait_s = (ts_rientro - _dt.now(_tz.utc)).total_seconds()
                    if wait_s > 0:
                        actual_wait = min(wait_s + 2, 600.0)  # cap 10 min safety
                        ctx.log_msg(
                            f"Raccolta: attendo rientro rifornimento (eta={wait_s:.0f}s, "
                            f"wait_effettivo={actual_wait:.0f}s)"
                        )
                        time.sleep(actual_wait)
        except Exception as exc:
            ctx.log_msg(f"[WARN] check eta_rientro_rifornimento: {exc}")

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
                        # WU55 — data collection HOME (ground truth)
                        if bool(_cfg(ctx, "RACCOLTA_OCR_DEBUG")):
                            try:
                                from shared.ocr_dataset import (
                                    new_pair_id, save_home_sample,
                                )
                                pid = new_pair_id()
                                save_home_sample(
                                    istanza=ctx.instance_name,
                                    pair_id=pid,
                                    screen=screen_home,
                                    ocr_raw=f"{attive_ocr}/{totale_ocr}",
                                    attive=attive_ocr,
                                    totale=totale_ocr,
                                    extra={"trigger": "_leggi_slot_da_home", "schermata": "HOME"},
                                )
                                ctx._ocr_pair = (pid, attive_ocr, totale_ocr)  # type: ignore
                                ctx.log_msg(f"[OCR-DEBUG] home sample salvato pair={pid}")
                            except Exception as exc:
                                ctx.log_msg(f"[OCR-DEBUG] save home fail: {exc}")
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

                    # WU55 — data collection MAP (shadow OCR)
                    _ocr_debug_collect_map(ctx)
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

                # WU55 — data collection MAP (shadow OCR, no decisione)
                _ocr_debug_collect_map(ctx)

                # Esegui il loop invio marce
                inviate = _loop_invio_marce(ctx, obiettivo, attive_correnti,
                                             blacklist, blacklist_fuori)
                inviate_totali += inviate

                # F3 — No Squads rilevato in _loop_invio_marce:
                # esci dal while esterno per evitare retry su gioco senza squadre
                if getattr(ctx, "_raccolta_no_squads", False):
                    ctx.log_msg("Raccolta: No Squads confermato — chiusura istanza")
                    ctx._raccolta_no_squads = False   # reset per prossima esecuzione
                    break

                # WU69 — slot pieni dedotti via pattern "maschera non aperta"
                # ripetuto su tipi diversi: esci dal while esterno (no retry).
                # Saving rispetto a comportamento pre-fix: ~60-90s per ciclo
                # patologico (3 tentativi × 20-30s ognuno → 1 invio + uscita).
                if getattr(ctx, "_raccolta_slot_pieni", False):
                    ctx.log_msg("Raccolta: slot pieni dedotti — chiusura istanza")
                    ctx._raccolta_slot_pieni = False  # reset per prossima esecuzione
                    attive_correnti = obiettivo  # forza stato "pieno" per stato finale
                    break

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
        # Output telemetria — Issue #53 Step 3
        out_data = {
            "inviate":          inviate_totali,
            "slot_pieni":       slot_pieni,
            "slot_attive":      int(attive_correnti),
            "slot_totali":      int(obiettivo),
            "tentativi_ciclo":  int(tentativi_ciclo),
        }
        try:
            tipologie_bloccate = list(getattr(ctx.state, "raccolta_tipologie_bloccate", []) or [])
            if tipologie_bloccate:
                out_data["tipologie_bloccate"] = tipologie_bloccate
        except Exception:
            pass
        return TaskResult(
            success=True,
            message=f"{inviate_totali} squadre inviate",
            data=out_data,
        )


# ==============================================================================
# RaccoltaChiusuraTask — re-run raccolta in chiusura tick
# ==============================================================================
#
# Issue #62 (26/04/2026) — esegue stessa logica di RaccoltaTask come ULTIMO
# task del tick per chiudere il ciclo con slot pieni: durante l'esecuzione
# degli altri task (donazione, store, arena, ds, ecc.) possono essersi
# liberati slot squadra (marce concluse, attacchi finiti, ecc.). Riprovare
# la raccolta a fine tick massimizza il throughput nodi/giorno.
#
# Sottoclasse di RaccoltaTask: eredita run() e tutta la logica. Differisce
# solo nel `name()` per non collidere con la prima registrazione (RaccoltaTask
# priority bassa) e mantenere log/state distinguibili. should_run() usa lo
# stesso flag "raccolta" — abilitazione coerente.
#
# Se non ci sono slot liberi, run() esce in <2s con "nessuna squadra libera".

class RaccoltaChiusuraTask(RaccoltaTask):
    """Re-run di RaccoltaTask come ultimo task del tick (chiusura slot pieni)."""

    def name(self) -> str:
        return "raccolta_chiusura"
