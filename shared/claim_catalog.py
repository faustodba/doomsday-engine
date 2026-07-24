# ==============================================================================
#  DOOMSDAY ENGINE V6 — shared/claim_catalog.py
#
#  Catalogo AUTO-APPRESO dei claim gratuiti nell'hub "Event Center" (icona
#  rotante in alto a destra su HOME, alterna label "Event Center"/"Water
#  War"/"Arms Race"/ecc. a seconda dell'evento in vetrina — stesso tap
#  target indipendentemente dalla label mostrata).
#
#  22/07/2026 — REDESIGN (2 iterazioni dopo la v1 a coordinate fisse):
#  1a v1 catalogava le voci per POSIZIONE fissa (profondità scroll + tap
#  coords) calibrata a mano su FAU_00. Osservazione dell'utente: la STESSA
#  voce può comparire in posizioni diverse su istanze diverse (o nel tempo,
#  con eventi che ruotano) — le coordinate fisse non sono un'identità
#  affidabile.
#
#  Fix 1: l'identità di una voce è l'IMMAGINE (non OCR, troppo rumoroso:
#  "Survival Preparations" letto come "> a Survival Preparat"). La
#  POSIZIONE (profondità scroll + Y del pallino) resta solo
#  un'informazione EFFIMERA per il tap del giro corrente — mai una cache
#  attendibile tra run diversi o istanze diverse.
#
#  Fix 2 (22/07 sera, richiesta utente dopo validazione cross-istanza su
#  FAU_01): l'immagine-identità si legge dalla RIGA SIDEBAR stessa (icona
#  + etichetta, visibili PRIMA di aprire), non dal titolo del sottomenu
#  aperto. Motivo: per le voci già note come NON claimabili non serve mai
#  aprire il sottomenu — costo di tempo puro senza beneficio (~4-8s per
#  voce, su una sidebar con più voci note-non-claimabili che nuove). Si
#  apre SOLO se: (a) la riga non è riconosciuta (mai vista, serve aprire
#  per verificare il widget CLAIM), oppure (b) è nota E claimabile (serve
#  aprire per cliccare).
#
#  Flusso: OGNI run (già schedulato 1×/giorno per istanza via
#  task_setup.json "daily") scansiona l'intera sidebar per profondità di
#  scroll, trova pallini rossi GENERICI, per ognuno RICONOSCE la riga
#  (icona+etichetta, crop dalla STESSA screenshot del rilevamento pallino
#  — zero screenshot extra) contro tutte le righe già viste:
#    - Riga nota e claimabile      → apri, verifica/clicca il claim.
#    - Riga nota e non claimabile  → skip, NESSUN tap di apertura.
#    - Riga mai vista              → apri, verifica il widget CLAIM già
#      noto (mai un tap esplorativo su qualcosa di ignoto) → impara il
#      risultato E salva il crop riga per riconoscerla la prossima volta,
#      su QUALUNQUE istanza (catalogo condiviso dev+prod).
#
#  Persistenza: data/claim_titles/<id>.png (crop riga sidebar) +
#  data/claim_catalog_learned.json (id → {claimable, label, ...}).
# ==============================================================================

from __future__ import annotations

import json
import os
import time

import numpy as np


# ------------------------------------------------------------------
# Geometria hub / sidebar (calibrata live su FAU_00 22/07/2026)
# ------------------------------------------------------------------

TAP_HOME_ICON:   tuple[int, int]             = (895, 68)
HOME_BADGE_ROI:  tuple[int, int, int, int]   = (935, 45, 960, 68)
TAP_HUB_BACK:    tuple[int, int]             = (30, 30)

# Verifica apertura hub (22/07 — trovato dal vivo: il tap sull'icona HOME a
# volte non apre l'hub, es. animazione banner in corso; senza verifica il
# task scansionava alla cieca la schermata sbagliata per 6 profondità
# prima del recovery finale, ~105s sprecati senza fare danni ma senza
# fare nulla di utile). Icona back-arrow in alto a sx, presente identica
# su OGNI sottotab dell'hub (score 1.0 su 4 sottotab diversi testati),
# assente su HOME/altri menu (score ~0.53).
PIN_HUB_OPEN:    str = "pin/pin_event_center_hub_open.png"
HUB_OPEN_ZONE:   tuple[int, int, int, int]   = (5, 10, 55, 55)
HUB_OPEN_SOGLIA: float = 0.85
HUB_OPEN_MAX_RETRY: int = 3

# Scroll sidebar: molte voci sono sotto la piega. RESET riporta sempre in
# cima (overshoot sicuro, il rebound si ferma da solo a inizio lista), FWD
# rivela un blocco più in basso. Wait 1.5s tra swipe: verificato dal vivo
# che 0.6s catturava lo screenshot a metà animazione (0/3 badge rilevati),
# 1.5s risolve (REGOLA DELAY UI, .claude/CLAUDE.md).
SIDEBAR_SCROLL_RESET_N: int = 4
SIDEBAR_SCROLL_RESET:   tuple[int, int, int, int, int] = (105, 250, 105, 450, 500)
SIDEBAR_SCROLL_FWD:     tuple[int, int, int, int, int] = (105, 450, 105, 250, 600)
MAX_SCROLL_DEPTH:       int = 6
ROW_TAP_X:              int = 105

# Rilevamento pallini rossi generico: blob HSV filtrato per colonna X (dove
# il gioco disegna sempre i badge numerici) e area minima (scarta il
# rumore di icone con tinte rosse/arancioni nell'artwork — calibrato live:
# badge reali area>=150 in colonna x=185-215, rumore icone area<80).
SIDEBAR_ZONE_ROI:  tuple[int, int, int, int] = (0, 60, 220, 520)
BADGE_COLUMN_X:    tuple[int, int]           = (185, 215)
BADGE_MIN_AREA:    int                       = 150
BADGE_RED_S_MIN:   int                       = 100
BADGE_RED_V_MIN:   int                       = 100
BADGE_RED_MIN_FRAC: float                    = 0.08

# Identità RIGA sidebar (icona+etichetta, immagine — non OCR, non il
# titolo del sottomenu aperto): crop centrato sulla Y del pallino trovato,
# larghezza piena colonna sidebar. Calibrato live: badge tipico centrato
# sulla riga, righe adiacenti tipicamente >55-60px di distanza (2 righe
# non si sovrappongono in un crop di 50px), validato visivamente su
# "Titan Approaches" (icona+etichetta pulite, nessun bleed da righe vicine).
ROW_CROP_X:        tuple[int, int]            = (0, 220)
ROW_CROP_HALF_H:    int                        = 25
ROW_MATCH_THRESHOLD: float                     = 0.82
CLAIM_TEMPLATE:      str                      = "pin/pin_login_rewards_claim.png"
CLAIM_ZONE:          tuple[int, int, int, int] = (780, 150, 925, 520)
CLAIM_THRESHOLD:      float                   = 0.80
CLAIM_TAP_CLOSE_SAFE: tuple[int, int]         = (100, 450)
MAX_CLAIMS_PER_VOCE:  int                     = 10

# Rivalutazione periodica (23/07/2026, richiesta utente dopo osservazione
# live: "Login Rewards" ha pallino rosso ma resta skippata per sempre).
# Alcune voci sono CICLICHE (si rinnovano ogni giorno — Login Rewards è il
# caso noto) mentre altre hanno stato davvero fisso (Match Predictions:
# sempre non-claim, è una feature di scommessa; Titan Approaches: sempre
# un'azione di combattimento). "claimable" deciso una volta al primo
# incontro e mai più rivalutato è strutturalmente sbagliato per le prime:
# se il primo incontro capita in un giorno senza nulla da reclamare,
# restano bloccate "non claimabili" per sempre anche nei giorni in cui il
# premio torna disponibile. Niente whitelist per distinguere i due casi
# (richiesta esplicita utente: "non ha senso") — più semplice e generale
# ridare a OGNI voce non-claimabile una possibilità di essere riverificata
# dopo N giorni, indipendentemente dal perché era stata segnata così.
RIVALUTAZIONE_GIORNI: int = 2


_DATA_DIR      = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_TITLES_DIR    = os.path.join(_DATA_DIR, "claim_titles")
_LEARNED_PATH  = os.path.join(_DATA_DIR, "claim_catalog_learned.json")


# ------------------------------------------------------------------
# Pallini rossi — rilevamento generico posizionale (STEP 2, pre-filtro)
# ------------------------------------------------------------------

def frazione_pallino_rosso(frame, roi: tuple[int, int, int, int]) -> float:
    """Frazione di pixel rossi (pallino notifica) in una ROI data. Usato
    per lo STEP 0/1 (icona HOME) dove la posizione è fissa per design di
    gioco (l'icona HOME non scorre)."""
    import cv2
    x0, y0, x1, y1 = roi
    sub = frame[y0:y1, x0:x1]
    if sub.size == 0:
        return 0.0
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0]; s = hsv[..., 1]; v = hsv[..., 2]
    red = ((h <= 8) | (h >= 172)) & (s > BADGE_RED_S_MIN) & (v > BADGE_RED_V_MIN)
    return float(red.mean())


def trova_pallini_sidebar(frame) -> list[tuple[int, int]]:
    """Trova tutti i pallini rossi nella colonna sidebar, filtrando il
    rumore delle icone (area minima + colonna X dei badge). Ritorna
    centroidi (x,y) in coordinate ASSOLUTE frame — solo per il tap di
    QUESTO giro, mai una posizione da fidarsi in futuro (vedi docstring
    modulo)."""
    import cv2
    x0, y0, x1, y1 = SIDEBAR_ZONE_ROI
    roi = frame[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0]; s = hsv[..., 1]; v = hsv[..., 2]
    mask = (((h <= 8) | (h >= 172)) & (s > BADGE_RED_S_MIN) & (v > BADGE_RED_V_MIN)).astype("uint8") * 255
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < BADGE_MIN_AREA:
            continue
        cx = centroids[i][0] + x0
        cy = centroids[i][1] + y0
        if BADGE_COLUMN_X[0] <= cx <= BADGE_COLUMN_X[1]:
            out.append((int(cx), int(cy)))
    return out


# ------------------------------------------------------------------
# Identità voce — immagine della RIGA sidebar (NON posizione, NON OCR,
# NON il titolo del sottomenu — riconosciuta PRIMA di aprire, vedi
# docstring modulo)
# ------------------------------------------------------------------

def carica_catalogo() -> dict:
    """{id: {claimable, label, first_seen, last_seen}}."""
    try:
        with open(_LEARNED_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def salva_catalogo(catalogo: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    tmp = _LEARNED_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _LEARNED_PATH)


def carica_crop_righe() -> dict:
    """{id: frame_bgr_riga} — carica tutti i crop riga noti (seed
    verificati a mano + appresi in discovery) per il riconoscimento."""
    import cv2
    out = {}
    if not os.path.isdir(_TITLES_DIR):
        return out
    for fname in os.listdir(_TITLES_DIR):
        if not fname.lower().endswith(".png"):
            continue
        tid = os.path.splitext(fname)[0]
        img = cv2.imread(os.path.join(_TITLES_DIR, fname))
        if img is not None:
            out[tid] = img
    return out


def ritaglia_riga(frame, by: int):
    """Crop della riga sidebar (icona+etichetta) centrato sulla Y del
    pallino — stessa zona usata sia per salvare che per riconoscere,
    così un crop salvato ora e uno letto in futuro sono sempre
    confrontabili (stessa shape)."""
    x0, x1 = ROW_CROP_X
    y0 = max(0, by - ROW_CROP_HALF_H)
    y1 = by + ROW_CROP_HALF_H
    return frame[y0:y1, x0:x1]


def salva_crop_riga(riga_id: str, frame, by: int) -> None:
    """Salva il crop della riga sidebar (icona+etichetta, centrato sulla Y
    del pallino) come nuovo template riconoscibile in futuro, su
    qualunque istanza (catalogo condiviso) — SENZA bisogno di aprire il
    sottomenu per le prossime volte che questa riga viene incontrata."""
    import cv2
    os.makedirs(_TITLES_DIR, exist_ok=True)
    crop = ritaglia_riga(frame, by)
    cv2.imwrite(os.path.join(_TITLES_DIR, f"{riga_id}.png"), crop)


def _preprocess_riga_match(img):
    """Preprocessing per il confronto riga (24/07/2026 — richiesta utente
    dopo duplicati nel catalogo: la stessa voce veniva salvata più volte
    perché il match a pixel grezzi risentiva del colore di sfondo riga
    (chiaro se selezionata/tappata, scuro se deselezionata) e della
    colonna badge rosso (185-215px, presente/assente a seconda del
    conteggio non ancora reclamato). Fix: taglia la colonna badge
    (mantiene solo 0-180px), poi estrae i soli contorni (Canny) e li
    dilata 3x3 — confronta la SAGOMA di icona+testo, non i colori dello
    sfondo, quindi resistente a selezione/badge."""
    import cv2
    sub = img[:, 0:180]
    gray = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    kernel = np.ones((3, 3), np.uint8)
    return cv2.dilate(edges, kernel, iterations=1)


def riconosci_riga(frame, by: int, crops: dict) -> tuple[str | None, float]:
    """Confronta la riga sidebar al pallino (bx,by) — crop dalla STESSA
    screenshot già usata per trova_pallini_sidebar, zero screenshot extra
    — contro tutte le righe già viste. Preprocessa entrambe le immagini
    (vedi _preprocess_riga_match) per ignorare sfondo/badge e confrontare
    solo la sagoma icona+testo. Ritorna (id, score) del migliore
    se >= soglia, altrimenti (None, best_score)."""
    import cv2
    crop = ritaglia_riga(frame, by)
    crop_prep = _preprocess_riga_match(crop)
    best_id, best_score = None, 0.0
    for tid, tmpl in crops.items():
        if tmpl.shape[:2] != crop.shape[:2]:
            continue
        tmpl_prep = _preprocess_riga_match(tmpl)
        res = cv2.matchTemplate(crop_prep, tmpl_prep, cv2.TM_CCOEFF_NORMED)
        score = float(res.max())
        if score > best_score:
            best_id, best_score = tid, score
    if best_id is not None and best_score >= ROW_MATCH_THRESHOLD:
        return best_id, best_score
    return None, best_score


def prossimo_id(crops: dict) -> str:
    n = len(crops) + 1
    while f"t{n:03d}" in crops:
        n += 1
    return f"t{n:03d}"


def ts_ora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def deve_rivalutare(dati: dict) -> bool:
    """True se una voce nota NON-claimabile ha superato RIVALUTAZIONE_GIORNI
    dall'ultima verifica REALE (apertura + controllo widget CLAIM) — non va
    confuso con last_seen, che si aggiorna ad ogni semplice avvistamento
    nella sidebar durante lo scan, apertura o no. Fallback su first_seen per
    le entry scritte prima dell'introduzione di last_checked
    (retrocompatibilità — altrimenti resterebbero bloccate per sempre)."""
    import calendar
    ultimo = dati.get("last_checked") or dati.get("first_seen")
    if not ultimo:
        return True
    try:
        t_ultimo = calendar.timegm(time.strptime(ultimo, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return True
    giorni_trascorsi = (time.time() - t_ultimo) / 86400.0
    return giorni_trascorsi >= RIVALUTAZIONE_GIORNI
