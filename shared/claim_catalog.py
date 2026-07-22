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
#  Fix: l'identità di una voce è ora l'IMMAGINE DEL TITOLO (crop del
#  titolo del sottomenu, es. "Login Rewards"), riconosciuta via template
#  matching (stesso principio già validato per il pulsante CLAIM — non
#  serve OCR, troppo rumoroso: "Survival Preparations" letto come "> a
#  Survival Preparat"). La POSIZIONE (profondità scroll + Y del pallino)
#  resta solo un'informazione EFFIMERA per il tap del giro corrente — mai
#  una cache attendibile tra run diversi o istanze diverse.
#
#  Flusso: OGNI run (già schedulato 1×/giorno per istanza via
#  task_setup.json "daily") scansiona l'intera sidebar per profondità di
#  scroll, trova pallini rossi GENERICI, per ognuno tappa e RICONOSCE il
#  titolo via template matching contro tutti i titoli già visti:
#    - Titolo noto e claimabile   → verifica/clicca il claim.
#    - Titolo noto e non claimabile → skip immediato (mai più verificato).
#    - Titolo mai visto           → verifica il widget CLAIM già noto
#      (mai un tap esplorativo su qualcosa di ignoto) → impara il
#      risultato E salva il crop del titolo per riconoscerlo la prossima
#      volta, su QUALUNQUE istanza (catalogo condiviso dev+prod).
#
#  Persistenza: data/claim_titles/<id>.png (crop titolo) +
#  data/claim_catalog_learned.json (id → {claimable, label, ...}).
# ==============================================================================

from __future__ import annotations

import json
import os
import time


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

# Identità titolo (immagine, non OCR) + claim
TITLE_CROP_ZONE:    tuple[int, int, int, int] = (40, 15, 500, 55)
TITLE_MATCH_THRESHOLD: float                  = 0.85
CLAIM_TEMPLATE:      str                      = "pin/pin_login_rewards_claim.png"
CLAIM_ZONE:          tuple[int, int, int, int] = (780, 150, 925, 520)
CLAIM_THRESHOLD:      float                   = 0.80
CLAIM_TAP_CLOSE_SAFE: tuple[int, int]         = (100, 450)
MAX_CLAIMS_PER_VOCE:  int                     = 10


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
# Identità voce — immagine del titolo (NON posizione, NON OCR testo)
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


def carica_crop_titoli() -> dict:
    """{id: frame_bgr_titolo} — carica tutti i template titolo noti
    (seed verificati a mano + appresi in discovery) per il riconoscimento."""
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


def salva_crop_titolo(titolo_id: str, frame) -> None:
    """Salva il crop titolo (zona TITLE_CROP_ZONE) come nuovo template
    riconoscibile in futuro, su qualunque istanza (catalogo condiviso)."""
    import cv2
    os.makedirs(_TITLES_DIR, exist_ok=True)
    x0, y0, x1, y1 = TITLE_CROP_ZONE
    crop = frame[y0:y1, x0:x1]
    cv2.imwrite(os.path.join(_TITLES_DIR, f"{titolo_id}.png"), crop)


def riconosci_titolo(frame, crops: dict) -> tuple[str | None, float]:
    """Confronta il titolo del sottomenu corrente (crop di
    TITLE_CROP_ZONE) contro tutti i template titolo noti. Ritorna
    (id, score) del migliore se >= soglia, altrimenti (None, best_score)."""
    import cv2
    x0, y0, x1, y1 = TITLE_CROP_ZONE
    crop = frame[y0:y1, x0:x1]
    best_id, best_score = None, 0.0
    for tid, tmpl in crops.items():
        if tmpl.shape[:2] != crop.shape[:2]:
            continue
        res = cv2.matchTemplate(crop, tmpl, cv2.TM_CCOEFF_NORMED)
        score = float(res.max())
        if score > best_score:
            best_id, best_score = tid, score
    if best_id is not None and best_score >= TITLE_MATCH_THRESHOLD:
        return best_id, best_score
    return None, best_score


def prossimo_id(crops: dict) -> str:
    n = len(crops) + 1
    while f"t{n:03d}" in crops:
        n += 1
    return f"t{n:03d}"


def ts_ora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
