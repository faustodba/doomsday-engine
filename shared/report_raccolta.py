# ==============================================================================
#  DOOMSDAY ENGINE V6 - shared/report_raccolta.py                       WU199
#
#  OCR + storage per il tab "Report" della schermata Messaggi (Gathering
#  Report). Sistema di lettura NUOVO e indipendente da produzione_corrente/
#  _leggi_risorse (main.py) — non li sostituisce, li affianca. Fonte dati
#  molto più precisa: ogni riga del report elenca una marcia di raccolta
#  realmente completata, con coordinata nodo, tipo+livello, timestamp e
#  quantità esatta raccolta (+ eventuale bonus).
#
#  SCOPERTA CALIBRAZIONE (09/07/2026, FAU_05 live, screenshot reali):
#    - Ogni riga occupa 2 righe di testo: header (coordinata/tipo/livello/
#      timestamp) + valore (icona+quantità base, bonus verde tra parentesi
#      opzionale, valore "donazione alleanza" a destra).
#    - Stride verticale tra righe consecutive: 79.5px (misurato via profilo
#      di luminosità riga-per-riga su screenshot 960x540 — una stima ad
#      occhio iniziale di 75px causava drift cumulativo e OCR spazzatura
#      dalla 3a riga in poi).
#    - IMPORTANTE: la griglia fissa (header a multipli esatti di 79.5px da
#      un'origine fissa) vale SOLO per la lista non scrollata. Lo swipe di
#      scroll è libero (no "snap to row" del gioco) — dopo uno swipe la
#      prima riga visibile atterra a un offset qualsiasi, non necessariamente
#      un multiplo dello stride. Verificato: OCR con griglia fissa su
#      screenshot scrollati → tutte le righe None (offset scivolato di
#      10-60px). Fix: `_trova_anchor_riga()` rileva dinamicamente la Y della
#      prima riga header pulita via profilo di luminosità (stessa tecnica di
#      calibrazione), poi applica lo stride noto da lì.
#    - Cascade OCR: RAW (RGB, no threshold) è SEMPRE superiore a binv150 su
#      questa schermata — il testo del bonus è verde, e la sua luminanza in
#      scala di grigi (~150) cade esattamente sulla soglia di binarizzazione
#      150 usata altrove nel codebase, perdendo il bonus in modo incoerente.
#      Estrazione via regex (tollera prefissi/suffissi spazzatura residui
#      del raw) invece di richiedere match esatto stringa intera.
#    - Tipo nodo: stesse etichette inglesi dei template TMPL_TIPO esistenti
#      (Field/Sawmill/Steel Mill/Oil Refinery) — mapping diretto.
#
#  Il tab Report è un LOG, non una coda di reward: le risorse raccolte
#  finiscono in magazzino automaticamente al rientro squadra. "Read and
#  claim all"/"Delete read" non hanno effetto sulle righe già visualizzate;
#  solo "Delete" (bottone contestuale, riga selezionata) svuota l'intero
#  report in un colpo solo, verificato live su FAU_05 E FAU_00 (nessun
#  popup di conferma — su FAU_00, istanza più avanzata, il menu Report ha
#  un albero di categorie aggiuntivo — Battle/Group Battles/Jungle Crisis/
#  Zombie/Scout/Other — ma il pannello dati e "Delete" si comportano
#  identici). Il chiamante deve quindi leggere TUTTO prima di cancellare
#  (pattern write-ahead: mai distruggere la fonte prima che i dati siano
#  al sicuro su disco) — tranne in modalità solo_reset, dove si cancella
#  senza leggere per design (vedi esegui_report_raccolta sotto).
#
#  INTEGRAZIONE (09/07/2026): NON è un Task schedulato indipendente —
#  `esegui_report_raccolta()` viene chiamata direttamente da
#  main.py::_leggi_risorse() (closure on_home_ready di attendi_home),
#  subito dopo la conferma della lettura risorse castello. Gira quindi una
#  volta per istanza per ciclo, allo stesso punto del boot in cui si
#  aggiorna produzione_corrente — non compete per uno slot nello scheduler
#  dei task periodici.
#
#  Storage: data/report_raccolta_dataset.jsonl (append-only, globale con
#  campo instance — stesso pattern di cap_nodi_dataset.py).
#  Dedup: chiave (instance, coordinata, ts_raccolta) — un nodo non può
#  essere raccolto dalla stessa istanza due volte nello stesso minuto.
#  Necessaria perché lo scroll di lettura può rileggere righe già viste
#  (overlap tra due screenshot consecutivi) e perché un retry dopo un
#  "Delete" fallito non deve duplicare righe già persistite.
# ==============================================================================

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = os.environ.get(
        "TESSERACT_EXE", r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    )
    _TESSERACT_OK = True
except ImportError:
    _TESSERACT_OK = False

_lock = threading.Lock()

# ------------------------------------------------------------------------------
# Calibrazione geometria righe (960x540, vedi header per dettagli misurazione)
# ------------------------------------------------------------------------------
HEADER_Y0    = 170     # top prima riga header visibile subito sotto la tab bar
VALUE_Y0     = 197     # top prima riga valore (offset +27 dall'header)
ROW_STRIDE   = 79.5    # distanza tra header di righe consecutive
ROW_H_HEADER = 16
ROW_H_VALUE  = 38
_PAD_HEADER  = 4       # margine verticale crop header, assorbe jitter anchor dinamico
ROWS_PER_PAGE = 4       # righe complete visibili senza scroll

ROI_COORD_X      = (330, 450)
ROI_TIPO_X       = (460, 730)
ROI_TS_X         = (770, 950)
ROI_VAL_BASE_X   = (365, 630)
ROI_VAL_ALLEANZA_X = (800, 930)

# WU199octies (10/07): verifica POSITIVA di report vuoto — testo "No mail
# received" mostrato dal gioco solo quando la lista è genuinamente vuota.
# Sostituisce il check precedente (len(leggi_pagina())==0), che è un
# controllo per ASSENZA: se l'ancora riga fallisce a rilevare l'header per
# qualunque motivo (schermata non stabilizzata, popup residuo, timing),
# leggi_pagina() ritorna comunque 0 righe — falso positivo, "sembra"
# vuoto senza che lo sia davvero. Il testo esplicito non ha questo rischio.
ROI_NO_MAIL = (330, 220, 950, 280)

# WU199nonies (10/07): verifica che il tab Report sia REALMENTE attivo
# prima di qualunque azione (lettura o Delete). Bug reale osservato live
# su FAU_03: il tap su TAP_TAB_REPORT non veniva mai verificato — se
# falliva/non registrava, il tab restava su Alliance (stato in cui lo
# lasciamo deliberatamente a fine di ogni run precedente, vedi WU199bis
# sotto TAP_TAB_ALLIANCE) e Read-claim-all + Delete-read colpivano i
# messaggi Alliance invece del report raccolta — azione distruttiva su
# dati sbagliati. "Sort Mail" esiste SOLO sul tab Report, quindi la sua
# presenza via OCR è una sentinella affidabile.
ROI_TAB_LABEL = (95, 62, 260, 82)

# Ricerca dinamica ancora riga (vedi nota "IMPORTANTE" sopra)
_SCAN_Y0        = 160
_SCAN_Y1        = 460
_SCAN_X0, _SCAN_X1 = 330, 900
_BANDA_H_MIN    = 8    # altezza minima banda testo per essere considerata header
_BANDA_H_MAX    = 20   # altezza massima (oltre = probabile riga valore, più alta)
_SOGLIA_LUMIN   = 140
_SOGLIA_PX      = 5

_CFG_LINE   = "--psm 7"
_CFG_DIGITS = "--psm 7 -c tessedit_char_whitelist=0123456789,(+)"

# Mapping tipo — stesse etichette inglesi dei template TMPL_TIPO in raccolta.py
_TIPO_MAP = {
    "field":       "campo",
    "sawmill":     "segheria",
    "steel mill":  "acciaio",
    "oil refinery": "petrolio",
}

# WU199quinquies (10/07/2026): capacità nominale massima per (tipo, livello)
# — vedi memoria reference_capacita_nodi.md, validata 30/04 su OCR popup
# gather. Usata come sanity check su quantita_base: la base NON PUÒ MAI
# superare la capacità nominale del nodo. Scoperto su dataset reale che
# l'icona risorsa (a sinistra del numero nel crop valore) a volte "bleeda"
# nel crop OCR e viene letta come una cifra spuria prependuta al numero
# corretto — sempre "5" per campo, sempre "2" per segheria (deterministico
# per forma icona, non rumore casuale). Es. reali: 51,320,000 invece di
# 1,320,000 (campo L7), 21,200,000 invece di 1,200,000 (segheria L6).
_CAPACITA_MAX = {
    ("campo", 6):    1_200_000, ("campo", 7):    1_320_000,
    ("segheria", 6): 1_200_000, ("segheria", 7): 1_320_000,
    ("acciaio", 6):    600_000, ("acciaio", 7):    660_000,
    ("petrolio", 6):    240_000, ("petrolio", 7):   264_000,
}

_RE_COORD  = re.compile(r"(?<!\d)(\d{3})(?!\d).*?(?<!\d)(\d{3})(?!\d)")
_RE_LV     = re.compile(r"[Ll][vV]\D{0,3}(\d)")
_RE_TS     = re.compile(r"(\d{4})/(\d{2})/(\d{2})\D+(\d{2}):(\d{2})")
_RE_NUM    = re.compile(r"\d{1,3}(?:,\d{3})+")
_RE_BONUS  = re.compile(r"\(\+([\d,]+)\)")


@dataclass
class ReportRow:
    coordinata:      str            # "701_530"
    tipo:            Optional[str]  # "campo"|"segheria"|"acciaio"|"petrolio"|None se non riconosciuto
    livello:         int            # -1 se non letto
    ts_raccolta:     Optional[str]  # ISO 8601 (assunto UTC, coerente col resto della telemetria)
    quantita_base:   int            # -1 se OCR fallita
    quantita_bonus:  int            # 0 se assente
    valore_alleanza: int            # -1 se OCR fallita


def _ocr_raw(frame: np.ndarray, roi: tuple, cfg: str) -> str:
    """WU199: upscale 3x prima dell'OCR (pattern standard del codebase,
    es. _ocr_coord_box in raccolta.py) — senza, cifre singole vengono
    confuse (7→2, 6→0 osservati su campione reale FAU_05), il testo su
    questa schermata è piccolo e l'upscale migliora nettamente la resa."""
    x1, y1, x2, y2 = roi
    crop = frame[y1:y2, x1:x2]
    crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    try:
        with _lock:
            return pytesseract.image_to_string(rgb, config=cfg).strip()
    except Exception:
        return ""


def _trova_anchor_riga(frame: np.ndarray) -> Optional[int]:
    """
    Rileva dinamicamente la Y di inizio della prima riga header "pulita"
    (altezza banda testo tra _BANDA_H_MIN e _BANDA_H_MAX) visibile nel
    frame corrente. None se non trovata (frame vuoto o nessuna riga
    header integra nella finestra di scan — es. tutta la vista sono righe
    valore troncate).
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    region = gray[_SCAN_Y0:_SCAN_Y1, _SCAN_X0:_SCAN_X1]
    bright = (region > _SOGLIA_LUMIN).sum(axis=1)

    banda_start = None
    for y, b in enumerate(bright):
        is_text = b > _SOGLIA_PX
        if is_text and banda_start is None:
            banda_start = y
        elif not is_text and banda_start is not None:
            altezza = y - banda_start
            if _BANDA_H_MIN <= altezza <= _BANDA_H_MAX:
                return banda_start + _SCAN_Y0
            banda_start = None
    return None


def _estrai_riga(frame: np.ndarray, hy: int, vy: int) -> Optional[ReportRow]:
    """OCR di una riga (header a Y=hy, valore a Y=vy) già posizionata dal
    chiamante. Ritorna None se la zona coordinata non contiene cifre
    (riga vuota o fuori dai bordi validi del frame).

    WU199: crop header con padding verticale (+/-4px). Senza padding, un
    anchor rilevato dinamicamente con jitter di 1px (es. 171 invece di 170)
    tronca gli apici dei caratteri quel tanto che basta a far leggere "7"
    come "/" ("Lv 7"→"tv /") — livello perso. Verificato caso reale FAU_05.
    """
    if not _TESSERACT_OK or hy < 0 or vy + ROW_H_VALUE > frame.shape[0]:
        return None

    pad = _PAD_HEADER
    hy0, hy1 = max(0, hy - pad), hy + ROW_H_HEADER + pad

    coord_txt = _ocr_raw(frame, (ROI_COORD_X[0], hy0, ROI_COORD_X[1], hy1), _CFG_LINE)
    m_coord = _RE_COORD.search(coord_txt)
    if not m_coord:
        return None  # riga vuota — fine lista

    coordinata = f"{m_coord.group(1)}_{m_coord.group(2)}"

    tipo_txt = _ocr_raw(frame, (ROI_TIPO_X[0], hy0, ROI_TIPO_X[1], hy1), _CFG_LINE)
    tipo = None
    for label, nome in _TIPO_MAP.items():
        if label in tipo_txt.lower():
            tipo = nome
            break
    m_lv = _RE_LV.search(tipo_txt)
    livello = int(m_lv.group(1)) if m_lv else -1

    ts_txt = _ocr_raw(frame, (ROI_TS_X[0], hy0, ROI_TS_X[1], hy1), _CFG_LINE)
    m_ts = _RE_TS.search(ts_txt)
    ts_raccolta = None
    if m_ts:
        y, mo, d, hh, mm = (int(g) for g in m_ts.groups())
        try:
            ts_raccolta = datetime(y, mo, d, hh, mm, tzinfo=timezone.utc).isoformat()
        except ValueError:
            ts_raccolta = None

    val_txt = _ocr_raw(frame, (ROI_VAL_BASE_X[0], vy, ROI_VAL_BASE_X[1], vy + ROW_H_VALUE), _CFG_DIGITS)
    numeri = _RE_NUM.findall(val_txt)
    # WU199: quando il bonus è presente, il testo grezzo contiene 2 gruppi
    # con virgole di migliaia — es. "240,000(+20,400)" → ["240,000","20,400"].
    # Il PRIMO è sempre la quantità base; eventuale rumore residuo (es. "49")
    # non ha virgole quindi non matcha mai _RE_NUM, quindi non c'è bisogno
    # di scartare il primo elemento (bug precedente: usava l'ultimo, che
    # con bonus presente restituiva il bonus invece della base).
    quantita_base = int(numeri[0].replace(",", "")) if numeri else -1
    m_bonus = _RE_BONUS.search(val_txt)
    quantita_bonus = int(m_bonus.group(1).replace(",", "")) if m_bonus else 0

    all_txt = _ocr_raw(frame, (ROI_VAL_ALLEANZA_X[0], vy, ROI_VAL_ALLEANZA_X[1], vy + ROW_H_VALUE), _CFG_DIGITS)
    numeri_all = _RE_NUM.findall(all_txt)
    valore_alleanza = int(numeri_all[0].replace(",", "")) if numeri_all else -1

    # WU199quinquies: riga inaffidabile (tipo non riconosciuto, o base oltre
    # la capacità nominale nota — vedi _CAPACITA_MAX sopra) → invalidiamo
    # quantita_base per farla scartare da registra_righe() (stesso path già
    # usato per OCR fallita: non persistita, non marcata come vista, ritenta
    # al prossimo giro in una posizione di scroll diversa).
    if tipo is None:
        quantita_base = -1
    else:
        cap_max = _CAPACITA_MAX.get((tipo, livello))
        if cap_max is not None and quantita_base > cap_max:
            quantita_base = -1

    return ReportRow(
        coordinata=coordinata, tipo=tipo, livello=livello,
        ts_raccolta=ts_raccolta, quantita_base=quantita_base,
        quantita_bonus=quantita_bonus, valore_alleanza=valore_alleanza,
    )


def leggi_pagina(frame: np.ndarray) -> list[ReportRow]:
    """
    API pubblica: OCR di tutte le righe visibili nella "pagina" corrente
    (fino a ROWS_PER_PAGE), qualunque sia l'offset di scroll.

    1. Rileva l'ancora (Y prima riga header pulita) dinamicamente.
    2. Applica lo stride noto (79.5px) per calcolare le righe successive.
    3. Si ferma alla prima riga vuota (fine lista reale in questa pagina).

    Ritorna lista vuota se l'ancora non è rilevabile (frame vuoto, oppure
    scroll fermato a metà riga senza alcun header integro visibile — raro,
    il chiamante tratterà come "nessuna riga nuova" per questa pagina).
    """
    if not _TESSERACT_OK:
        return []

    anchor = _trova_anchor_riga(frame)
    if anchor is None:
        return []

    value_offset = VALUE_Y0 - HEADER_Y0  # +27, costante indipendente dallo scroll
    righe: list[ReportRow] = []
    for i in range(ROWS_PER_PAGE):
        hy = int(anchor + i * ROW_STRIDE)
        vy = hy + value_offset
        row = _estrai_riga(frame, hy, vy)
        if row is None:
            break
        righe.append(row)
    return righe


# ------------------------------------------------------------------------------
# Storage JSONL + dedup (pattern cap_nodi_dataset.py)
# ------------------------------------------------------------------------------

def _root_dir() -> Path:
    root = os.environ.get("DOOMSDAY_ROOT")
    return Path(root) if root else Path(os.getcwd())


def _dataset_path() -> Path:
    p = _root_dir() / "data" / "report_raccolta_dataset.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _chiave(instance: str, row: ReportRow) -> str:
    return f"{instance}|{row.coordinata}|{row.ts_raccolta}"


def carica_chiavi_esistenti(instance: str) -> set[str]:
    """Chiavi già persistite per l'istanza — usato per il dedup pre-append.

    Best-effort: file assente/corrotto → set vuoto (nessun dedup, ma
    l'append comunque non duplica su un file mai scritto prima).
    """
    chiavi: set[str] = set()
    path = _dataset_path()
    if not path.exists():
        return chiavi
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("instance") == instance:
                    chiavi.add(f"{rec['instance']}|{rec['coordinata']}|{rec.get('ts_raccolta')}")
    except Exception:
        pass
    return chiavi


def registra_righe(instance: str, righe: list[ReportRow],
                   chiavi_esistenti: set[str]) -> int:
    """
    Append righe NUOVE (non in chiavi_esistenti) su JSONL. Aggiorna
    chiavi_esistenti in-place (permette chiamate multiple nello stesso run
    senza duplicare tra una pagina di scroll e la successiva).

    Ritorna il numero di righe effettivamente scritte.

    WU199: righe con quantita_base<=0 vengono SCARTATE senza marcarle come
    viste: restano dedup-eligible per un prossimo passaggio (in produzione
    lo scroll successivo o il run seguente le ripropone quasi sempre in una
    posizione diversa). Se le marcassimo come "viste" qui, resterebbero
    perse per sempre con dati spazzatura persistiti. Due cause note (vedi
    _estrai_riga):
    - OCR fallita, tipicamente l'ultima riga di pagina quando il pannello
      valore è tagliato dalla barra pulsanti — limite fisico del layout.
    - WU199quinquies: tipo non riconosciuto, o base oltre la capacità
      nominale nota (_CAPACITA_MAX) — tipico bleed dell'icona risorsa nel
      crop del valore, letta come cifra spuria prependuta al numero corretto.
    """
    nuove = []
    for row in righe:
        if row.ts_raccolta is None:
            continue  # timestamp illeggibile: scartata, non persistibile in modo dedup-sicuro
        if row.quantita_base <= 0:
            continue  # OCR valore fallita (es. riga tagliata da barra pulsanti): ritenta al prossimo giro
        chiave = _chiave(instance, row)
        if chiave in chiavi_esistenti:
            continue
        chiavi_esistenti.add(chiave)
        nuove.append(row)

    if not nuove:
        return 0

    lines = []
    ts_ocr = datetime.now(timezone.utc).isoformat()
    for row in nuove:
        record = {
            "ts_ocr": ts_ocr,
            "instance": instance,
            "coordinata": row.coordinata,
            "tipo": row.tipo,
            "livello": row.livello,
            "ts_raccolta": row.ts_raccolta,
            "quantita_base": row.quantita_base,
            "quantita_bonus": row.quantita_bonus,
            "quantita_totale": (row.quantita_base if row.quantita_base > 0 else 0)
                                + row.quantita_bonus,
            "valore_alleanza": row.valore_alleanza,
        }
        lines.append(json.dumps(record, ensure_ascii=False))

    try:
        with _lock:
            with _dataset_path().open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
    except Exception:
        return 0

    return len(nuove)


# ------------------------------------------------------------------------------
# Chiamata diretta da main.py::_leggi_risorse() — non un Task schedulato
# ------------------------------------------------------------------------------

TAP_ICONA_MESSAGGI = (928, 430)   # stessa coordinata di MessaggiConfig (tasks/messaggi.py)
TAP_TAB_REPORT     = (71, 34)
TAP_TAB_ALLIANCE   = (198, 34)    # stessa coordinata di MessaggiConfig.tap_tab_alliance
TAP_CLOSE          = (930, 36)    # X chiusura overlay messaggi, stessa di MessaggiConfig
SWIPE_DA           = (650, 430)
SWIPE_A            = (650, 150)
SWIPE_DURATA_MS    = 800
WAIT_OPEN          = 3.0   # WU199undecies (10/07): allineato a MessaggiConfig
                            # (tasks/messaggi.py, fix 18/06 "wait_tab 2.0→3.0"
                            # per lo stesso identico problema di tab non
                            # confermato) invece di un valore stimato a mano
WAIT_TAB           = 3.0   # idem — era 2.0s, insufficiente in alcuni casi live
                            # (FAU_03, FAU_08 — tab non confermato al primo giro)
WAIT_SCROLL        = 1.3
WAIT_DELETE        = 1.5
WAIT_RESTORE_TAB   = 1.5
WAIT_CLOSE         = 1.5
MAX_PAGINE         = 15   # cap sicurezza modalità lettura completa (non usato in solo_reset)

# WU199sexies (10/07/2026): toggle "Sort Mail" in alto a sinistra del tab
# Report — verificato live su FAU_10 che NON riordina le righe (ipotesi
# iniziale errata), ma cambia vista: OFF = "Gathering Report" diretto come
# unico elemento in lista (quello che vogliamo), ON = vista a categorie
# (Battle/Group Battles/Jungle Crisis/Zombie/Scout/Other, Gathering Report
# annidato sotto "Other"). Manteniamo sempre OFF. Rilevamento stato via
# luminosità: il cursore chiaro del toggle sta a sinistra quando OFF, si
# sposta a destra quando ON — confrontiamo due piccole ROI invece di un
# singolo pixel per robustezza al rumore JPEG/compressione ADB.
TAP_SORT_MAIL      = (54, 71)
_TOGGLE_ROI_L      = (22, 62, 45, 80)   # box sinistra cursore (x1,y1,x2,y2)
_TOGGLE_ROI_R      = (62, 62, 85, 80)   # box destra cursore
WAIT_TOGGLE        = 1.5

# WU199sexies: sostituito il "Delete" diretto con "Read and claim all" +
# "Delete read" su richiesta utente (2 tap invece di 1). Verificato live
# 10/07 su FAU_10 che "Delete read" da solo produce lo stesso risultato di
# "Delete" (conferma "you're about to delete all read mails in the current
# tab" → OK → "No mail received") — un solo elemento mail "Gathering
# Report" che accumula tutto, quindi nessuna differenza pratica rispetto a
# Delete diretto, ma "Read and claim all" prima garantisce che eventuali
# reward vengano comunque marcati/reclamati per sicurezza.
TAP_READ_CLAIM_ALL = (50, 508)
TAP_DELETE_READ    = (200, 508)
TAP_CONFIRM_OK     = (588, 380)   # popup conferma "Delete read"
WAIT_READ_CLAIM    = 1.5
WAIT_DELETE_CONFIRM = 1.5


def _sort_mail_toggle_on(frame: np.ndarray) -> bool:
    """True se il toggle 'Sort Mail' è ON (vista a categorie). Confronto
    di luminosità media tra le due metà del cursore — vedi nota WU199sexies
    sopra le costanti _TOGGLE_ROI_L/_TOGGLE_ROI_R."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    l = gray[_TOGGLE_ROI_L[1]:_TOGGLE_ROI_L[3], _TOGGLE_ROI_L[0]:_TOGGLE_ROI_L[2]]
    r = gray[_TOGGLE_ROI_R[1]:_TOGGLE_ROI_R[3], _TOGGLE_ROI_R[0]:_TOGGLE_ROI_R[2]]
    if l.size == 0 or r.size == 0:
        return False
    return float(r.mean()) > float(l.mean())


def _assicura_sort_mail_off(device, log) -> None:
    """Tocca il toggle Sort Mail SOLO se rilevato ON — mai un tap alla
    cieca (rischio di accenderlo invece di spegnerlo). Best-effort: uno
    screenshot fallito qui non blocca il resto del flusso.

    WU199decies (10/07): log esplicito in OGNI caso (non solo quando tocca
    qualcosa) — utente ha notato che il check era silenzioso quando trovava
    già OFF, nessuna traccia visibile che fosse stato eseguito davvero."""
    screen = device.screenshot()
    if screen is None:
        log("[REPORT-RACCOLTA] Sort Mail — screenshot None, check saltato")
        return
    if _sort_mail_toggle_on(screen.frame):
        log("[REPORT-RACCOLTA] Sort Mail ON — riporto a OFF")
        device.tap(TAP_SORT_MAIL)
        time.sleep(WAIT_TOGGLE)
    else:
        log("[REPORT-RACCOLTA] Sort Mail già OFF — nessuna azione")


def _tab_report_attivo(frame: np.ndarray) -> bool:
    """True se il tab Report è realmente quello attivo a schermo — vedi
    nota WU199nonies sopra ROI_TAB_LABEL. OCR del testo "Sort Mail",
    presente solo su questo tab."""
    txt = _ocr_raw(frame, ROI_TAB_LABEL, _CFG_LINE).lower()
    return "sort" in txt or "mail" in txt


def _report_vuoto_confermato(frame: np.ndarray) -> bool:
    """Verifica POSITIVA (non per assenza) che il report sia vuoto — vedi
    nota WU199octies sopra ROI_NO_MAIL."""
    txt = _ocr_raw(frame, ROI_NO_MAIL, _CFG_LINE).lower()
    return "no mail" in txt or "mail received" in txt


def _elimina_report_letto(device) -> bool:
    """Read and claim all + Delete read (vedi nota WU199sexies). Ritorna
    True SOLO se il testo "No mail received" è confermato via OCR — non
    la semplice assenza di righe lette (rischio falso positivo, vedi
    WU199octies)."""
    device.tap(TAP_READ_CLAIM_ALL)
    time.sleep(WAIT_READ_CLAIM)
    device.tap(TAP_DELETE_READ)
    time.sleep(WAIT_DELETE_CONFIRM)
    device.tap(TAP_CONFIRM_OK)
    time.sleep(WAIT_DELETE)
    screen_post = device.screenshot()
    if screen_post is None:
        return False
    return _report_vuoto_confermato(screen_post.frame)


def esegui_report_raccolta(ctx, log_fn=None, solo_reset: bool = True) -> dict:
    """
    Va da HOME (assunta già stabile — chiamata da on_home_ready) al tab
    Report e:
      - solo_reset=True  (default, fase di test corrente): naviga e tocca
        subito "Read and claim all" + "Delete read" (WU199sexies — vedi
        costanti sopra), nessuna lettura OCR. Serve a riportare ogni
        istanza a un report vuoto/piccolo come baseline pulita, senza
        rischiare tempi lunghi di scroll su backlog storici mai letti
        (osservato: giorni di dati su FAU_05/FAU_00 prima del primo test).
      - solo_reset=False (fase futura, non ancora abilitata di default):
        legge tutte le pagine, persiste su JSONL con dedup, cancella SOLO
        se la fine lista è confermata (vedi leggi_pagina/registra_righe
        sopra e la nota write-ahead nell'header del modulo).

    Ritorna un dict di riepilogo (mai solleva eccezioni — best-effort,
    non deve mai far fallire il boot dell'istanza).
    """
    log = log_fn or (lambda m: None)
    device = ctx.device
    esito = {"solo_reset": solo_reset, "nuove": 0, "viste": 0, "pagine": 0,
             "fine_lista_raggiunta": False, "delete_ok": None, "errore": None}

    try:
        log("[REPORT-RACCOLTA] apro messaggi → tab Report")
        device.tap(TAP_ICONA_MESSAGGI)
        time.sleep(WAIT_OPEN)
        device.tap(TAP_TAB_REPORT)
        time.sleep(WAIT_TAB)

        # WU199nonies — MAI procedere (lettura o Delete) senza conferma
        # positiva del tab. Un retry singolo assorbe animazioni lente;
        # se anche il retry fallisce, abort in sicurezza (nessuna azione
        # distruttiva su un tab sconosciuto/sbagliato).
        screen_tab = device.screenshot()
        tab_ok = screen_tab is not None and _tab_report_attivo(screen_tab.frame)
        if not tab_ok:
            log("[REPORT-RACCOLTA] tab Report non confermato — retry tap")
            device.tap(TAP_TAB_REPORT)
            time.sleep(WAIT_TAB)
            screen_tab = device.screenshot()
            tab_ok = screen_tab is not None and _tab_report_attivo(screen_tab.frame)

        if not tab_ok:
            esito["errore"] = "tab_report_non_confermato"
            log("[REPORT-RACCOLTA] [WARN] tab Report non raggiunto dopo retry — "
                "abort, nessuna azione eseguita")
            device.tap(TAP_TAB_ALLIANCE)
            time.sleep(WAIT_RESTORE_TAB)
            device.tap(TAP_CLOSE)
            time.sleep(WAIT_CLOSE)
            log(f"[REPORT-RACCOLTA] completato: {esito}")
            return esito

        _assicura_sort_mail_off(device, log)

        if solo_reset:
            log("[REPORT-RACCOLTA] modalità solo_reset — Read+Delete diretto, nessuna lettura")
            esito["delete_ok"] = _elimina_report_letto(device)
        else:
            chiavi = carica_chiavi_esistenti(ctx.instance_name)
            pagine = 0
            chiavi_pagina_precedente = None
            while pagine < MAX_PAGINE:
                screen = device.screenshot()
                if screen is None:
                    log("[REPORT-RACCOLTA] screenshot None — abort lettura")
                    break
                righe_pagina = leggi_pagina(screen.frame)
                esito["viste"] += len(righe_pagina)
                nuove_pagina = registra_righe(ctx.instance_name, righe_pagina, chiavi)
                esito["nuove"] += nuove_pagina
                pagine += 1
                log(f"[REPORT-RACCOLTA] pagina {pagine} — {len(righe_pagina)} righe, "
                    f"{nuove_pagina} nuove")

                if 0 < len(righe_pagina) < ROWS_PER_PAGE:
                    esito["fine_lista_raggiunta"] = True
                    break

                # WU199duodecies (11/07): lo scroll non ha prodotto contenuto
                # diverso dalla pagina precedente (stesso giro di lettura) —
                # segnale LOCALE che siamo fisicamente in fondo alla lista
                # (il gioco non scrolla oltre). Sostituisce il vecchio check
                # "pagina piena ma tutta già nota nello storico globale", che
                # poteva scattare anche a metà lista rileggendo una riga nota
                # da tempo, non necessariamente il vero fondo — osservato live
                # 11/07: fermava la lettura troppo presto, Delete quasi mai
                # raggiunto. Chiave (coordinata, ts_raccolta): stabile anche
                # con rumore OCR sulle quantità.
                chiavi_pagina = {(r.coordinata, r.ts_raccolta) for r in righe_pagina}
                if (chiavi_pagina_precedente is not None
                        and chiavi_pagina == chiavi_pagina_precedente
                        and len(righe_pagina) > 0):
                    esito["fine_lista_raggiunta"] = True
                    log("[REPORT-RACCOLTA] scroll fermo (stessa pagina di prima) "
                        "— fondo lista confermato")
                    break
                chiavi_pagina_precedente = chiavi_pagina

                device.swipe(SWIPE_DA[0], SWIPE_DA[1], SWIPE_A[0], SWIPE_A[1],
                            duration_ms=SWIPE_DURATA_MS)
                time.sleep(WAIT_SCROLL)
            esito["pagine"] = pagine

            if esito["fine_lista_raggiunta"]:
                esito["delete_ok"] = _elimina_report_letto(device)

        # WU199bis (09/07/2026) — il gioco RICORDA l'ultimo tab aperto in
        # Messaggi (verificato live: riaprendo da HOME si torna su Report,
        # non su Alliance). Senza questo tap, la prossima esecuzione di
        # MessaggiTask trova il tab Report ancora attivo — _rileva_tab_attivo()
        # riconosce solo Alliance/System, ritorna None → "schermata non
        # aperta" → abort, salta il claim ricompense. Riportiamo su Alliance
        # prima di chiudere, così lo stato resta quello che messaggi.py si
        # aspetta di trovare.
        device.tap(TAP_TAB_ALLIANCE)
        time.sleep(WAIT_RESTORE_TAB)

        device.tap(TAP_CLOSE)
        time.sleep(WAIT_CLOSE)

    except Exception as exc:
        esito["errore"] = str(exc)
        log(f"[REPORT-RACCOLTA] [WARN] eccezione: {exc}")
        try:
            device.tap(TAP_TAB_ALLIANCE)
            time.sleep(WAIT_RESTORE_TAB)
            device.tap(TAP_CLOSE)
            time.sleep(WAIT_CLOSE)
        except Exception:
            pass

    log(f"[REPORT-RACCOLTA] completato: {esito}")
    return esito
