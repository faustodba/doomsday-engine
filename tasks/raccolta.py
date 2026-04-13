# ==============================================================================
#  DOOMSDAY ENGINE V6 — tasks/raccolta.py                           Step 21
#
#  Invio squadre raccoglitrici ai nodi risorse sulla mappa.
#
#  FIX 12/04/2026:
#    - _leggi_coordinate_nodo: ctx.matcher.find() → ctx.matcher.find_one()
#      firma corretta: find_one(screenshot, template_name, threshold)
#      ritorna MatchResult, non (cx,cy) — estratto .cx/.cy se found
#    - _esegui_marcia: stessa correzione firma matcher (2 occorrenze)
#    - _invia_squadra: stessa correzione firma matcher (1 occorrenza)
#    - Tutti i ctx.matcher.find() sostituiti con find_one() + controllo .found
#
#  STRATEGIA V6:
#    Il loop marce di V5 dipende pesantemente da ADB diretto, VerificaUI,
#    debug, OCR, allocation, config globale — non è portabile 1:1 in V6.
#    In V6 viene implementato il "cuore" testabile della raccolta:
#      • Blacklist nodi (RESERVED/COMMITTED, TTL, pulizia scaduti)
#      • Selezione tipo risorsa dalla sequenza
#      • Logica slot (conta attive vs obiettivo)
#      • Flusso UI via ctx.device (tap, key, screenshot) — zero ADB diretto
#      • Config interamente via ctx.config con fallback ai default
#
#  FLUSSO (semplificato V6 — fedele alla logica V5):
#    0. Verifica abilitazione + slot liberi (iniettabile nei test)
#    1. Naviga in mappa
#    2. Loop: finché attive < obiettivo e fallimenti < MAX_FALLIMENTI:
#       a. Seleziona tipo dalla sequenza (round-robin + blacklist)
#       b. Cerca nodo (LENTE → tipo × 2 → livello → CERCA)
#       c. Leggi coordinate nodo via matcher
#       d. Verifica blacklist → RESERVED → _esegui_marcia
#       e. Se OK → COMMITTED in blacklist + attive++
#       f. Se fail → fallimenti++
#    3. Ritorna in home, ritorna inviate
#
#  COORDINATE DEFAULT (960x540):
#    TAP_LENTE          = (334, 13)
#    TAP_NODO           = (480, 270)
#    TAP_RACCOGLI       = (662, 410)
#    TAP_SQUADRA        = (480, 410)
#    TAP_MARCIA         = (480, 448)
#    TAP_CANCELLA       = (390, 340)
#    TAP_CAMPO_TESTO    = (480, 340)
#    TAP_OK_TASTIERA    = (480, 380)
#    TEMPLATE_GATHER    = "pin/pin_gather.png"
#    TEMPLATE_MARCIA    = "pin/pin_marcia.png"
#
#  CONFIG (ctx.config — chiavi con fallback ai default):
#    RACCOLTA_ABILITATA          bool   default True
#    RACCOLTA_SEQUENZA           list   default ["campo","segheria","petrolio","acciaio"]
#    RACCOLTA_OBIETTIVO          int    default 4   (slot totali da riempire)
#    RACCOLTA_MAX_FALLIMENTI     int    default 3
#    RACCOLTA_TRUPPE             int    default 0   (0 = default gioco)
#    RACCOLTA_LIVELLO            int    default 6
#    BLACKLIST_COMMITTED_TTL     int    default 120 (secondi)
#    BLACKLIST_RESERVED_TTL      int    default 45  (secondi)
#    BLACKLIST_ATTESA_NODO       int    default 120
# ==============================================================================

from __future__ import annotations

import time
import threading
from typing import Optional

from core.task import Task, TaskContext, TaskResult

# ------------------------------------------------------------------------------
# Default costanti
# ------------------------------------------------------------------------------

_DEFAULTS: dict = {
    # Coordinate UI (960x540) — da V5 config.py
    "TAP_LENTE":            (38,  325),   # icona lente grande in mappa
    "TAP_NODO":             (480, 280),   # centro nodo dopo CERCA
    "TAP_RACCOGLI":         (230, 390),   # pulsante RACCOGLI nel popup nodo
    "TAP_SQUADRA":          (700, 185),   # selezione squadra
    "TAP_MARCIA":           (727, 476),   # pulsante MARCIA
    "TAP_CANCELLA":         (527, 469),   # pulsante CANCELLA truppe
    "TAP_CAMPO_TESTO":      (748,  75),   # campo testo truppe
    "TAP_OK_TASTIERA":      (480, 380),   # OK tastiera
    # Icone tipo risorsa nella lente (da V5 config.py)
    "TAP_ICONA_TIPO": {
        "campo":    (410, 450),
        "segheria": (535, 450),
        "acciaio":  (672, 490),
        "petrolio": (820, 490),
    },
    # Coordinate livello per tipo (meno, piu, search) — 960x540 (V5 raccolta.py)
    "COORD_LIVELLO": {
        "campo":    {"meno": (294, 295), "piu": (519, 293), "search": (413, 352)},
        "segheria": {"meno": (419, 295), "piu": (644, 293), "search": (538, 352)},
        "acciaio":  {"meno": (556, 295), "piu": (781, 293), "search": (675, 352)},
        "petrolio": {"meno": (701, 295), "piu": (890, 293), "search": (791, 352)},
    },
    # Template
    "TEMPLATE_GATHER":  "pin/pin_gather.png",
    "TEMPLATE_MARCIA":  "pin/pin_marcia.png",
    "TEMPLATE_SOGLIA":  0.75,
    # Logica raccolta
    "RACCOLTA_ABILITATA":       True,
    "RACCOLTA_SEQUENZA":        ["campo", "segheria", "petrolio", "acciaio"],
    "RACCOLTA_OBIETTIVO":       4,
    "RACCOLTA_MAX_FALLIMENTI":  3,
    "RACCOLTA_TRUPPE":          0,
    "RACCOLTA_LIVELLO":         6,
    # Blacklist
    "BLACKLIST_COMMITTED_TTL":  120,
    "BLACKLIST_RESERVED_TTL":   45,
    "BLACKLIST_ATTESA_NODO":    120,
    # Ritardi (secondi)
    "DELAY_POST_MARCIA":        2.0,
    "DELAY_CERCA":              1.5,
}

_TUTTI_I_TIPI = ["campo", "segheria", "petrolio", "acciaio"]


def _cfg(ctx: TaskContext, key: str):
    """Legge ctx.config con fallback al default di modulo."""
    return ctx.config.get(key, _DEFAULTS[key])


# ==============================================================================
# Blacklist nodi — pura, zero I/O, thread-safe
# ==============================================================================

class Blacklist:
    """
    Blacklist nodi con stati RESERVED / COMMITTED e TTL indipendenti.

    Formato interno:
      chiave : "X_Y"  (es. "712_535")
      valore : {"ts": float, "state": "RESERVED"|"COMMITTED", "eta_s": float|None}
    """

    def __init__(self, committed_ttl: int = 120, reserved_ttl: int = 45):
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.committed_ttl = committed_ttl
        self.reserved_ttl  = reserved_ttl

    def _pulisci(self) -> None:
        """Rimuove i nodi scaduti. Chiamare dentro lock."""
        ora = time.time()
        scaduti = []
        for k, v in self._data.items():
            ttl = (self.committed_ttl
                   if v.get("state") == "COMMITTED"
                   else self.reserved_ttl)
            if ora - v.get("ts", 0) > ttl:
                scaduti.append(k)
        for k in scaduti:
            del self._data[k]

    def contiene(self, chiave: str) -> bool:
        """True se il nodo è in blacklist (non scaduto)."""
        if not chiave:
            return False
        with self._lock:
            self._pulisci()
            return chiave in self._data

    def reserve(self, chiave: str) -> None:
        """Prenota il nodo in stato RESERVED (TTL breve)."""
        if not chiave:
            return
        with self._lock:
            self._data[chiave] = {"ts": time.time(), "state": "RESERVED", "eta_s": None}

    def commit(self, chiave: str, eta_s: Optional[float] = None) -> None:
        """Conferma il nodo in stato COMMITTED (TTL lungo)."""
        if not chiave:
            return
        with self._lock:
            self._data[chiave] = {"ts": time.time(), "state": "COMMITTED",
                                   "eta_s": eta_s}

    def rollback(self, chiave: str) -> None:
        """Rilascia il nodo dalla blacklist."""
        if not chiave:
            return
        with self._lock:
            self._data.pop(chiave, None)

    def get_eta(self, chiave: str) -> Optional[float]:
        """Ritorna eta_s del nodo COMMITTED, o None."""
        with self._lock:
            v = self._data.get(chiave)
            return v.get("eta_s") if isinstance(v, dict) else None

    def get_state(self, chiave: str) -> Optional[str]:
        """Ritorna lo stato del nodo: 'RESERVED'|'COMMITTED'|None."""
        with self._lock:
            v = self._data.get(chiave)
            return v.get("state") if isinstance(v, dict) else None

    def snapshot(self) -> dict:
        """Copia immutabile del dizionario interno (per test)."""
        with self._lock:
            self._pulisci()
            return dict(self._data)

    def __len__(self) -> int:
        with self._lock:
            self._pulisci()
            return len(self._data)


# ==============================================================================
# Selezione sequenza risorse
# ==============================================================================

def _calcola_sequenza(obiettivo: int, sequenza_base: list[str],
                       tipi_bloccati: set[str]) -> list[str]:
    """
    Genera la sequenza di tipi da inviare, escludendo i tipi bloccati.
    Round-robin sulla sequenza_base × obiettivo (con padding sicuro).
    """
    disponibili = [t for t in sequenza_base if t not in tipi_bloccati]
    if not disponibili:
        disponibili = [t for t in _TUTTI_I_TIPI if t not in tipi_bloccati]
    if not disponibili:
        return []
    n = max(obiettivo * 3, 10)
    return (disponibili * (n // len(disponibili) + 1))[:n]


# ==============================================================================
# Operazioni UI via ctx.device — zero ADB diretto
# ==============================================================================

def _cerca_nodo(ctx: TaskContext, tipo: str) -> None:
    """
    Esegue: LENTE → tap tipo × 2 → imposta livello → CERCA.
    Tutte le azioni via ctx.device.tap/key.
    """
    tap_lente   = _cfg(ctx, "TAP_LENTE")
    coord_lv    = _cfg(ctx, "COORD_LIVELLO").get(tipo, _cfg(ctx, "COORD_LIVELLO")["campo"])
    livello     = max(1, min(7, int(_cfg(ctx, "RACCOLTA_LIVELLO"))))
    delay_cerca = _cfg(ctx, "DELAY_CERCA")

    tap_icona = _cfg(ctx, "TAP_ICONA_TIPO").get(tipo, _cfg(ctx, "TAP_ICONA_TIPO")["campo"])

    ctx.log_msg(f"Raccolta: LENTE → {tipo} Lv.{livello}")
    ctx.device.tap(tap_lente)
    time.sleep(0.5)

    # Seleziona tipo × 2 (tap sull'icona del tipo nella lente)
    ctx.device.tap(tap_icona)
    ctx.device.tap(tap_icona)
    time.sleep(1.2)

    # Reset livello: 6× tap MENO (porta a Lv.1)
    for _ in range(6):
        ctx.device.tap(coord_lv["meno"])
    # Sale al livello target: (livello-1) × tap PIU
    for _ in range(livello - 1):
        ctx.device.tap(coord_lv["piu"])

    # CERCA
    ctx.device.tap(coord_lv["search"])
    time.sleep(delay_cerca)
    ctx.log_msg(f"Raccolta: CERCA eseguita per {tipo} Lv.{livello}")


def _leggi_coordinate_nodo(ctx: TaskContext) -> Optional[tuple[int, int]]:
    """
    Legge le coordinate del nodo trovato dalla CERCA.
    Usa ctx.matcher.find_one(screenshot, template_name, threshold).
    Ritorna (cx, cy) o None se non trovato.

    FIX 12/04/2026: era ctx.matcher.find(template, screen, soglia) —
    firma errata, find() non esiste su TemplateMatcher.
    Corretto in find_one(screen, template, soglia) che ritorna MatchResult.
    """
    screen = ctx.device.screenshot()
    if not screen:
        return None
    template_gather = _cfg(ctx, "TEMPLATE_GATHER")
    soglia          = _cfg(ctx, "TEMPLATE_SOGLIA")

    result = ctx.matcher.find_one(screen, template_gather, threshold=soglia)
    if not result.found:
        ctx.log_msg(
            f"Raccolta: pin_gather score={result.score:.3f} < soglia={soglia} — nodo non trovato"
        )
        return None
    return (result.cx, result.cy)


def _esegui_marcia(ctx: TaskContext, n_truppe: int) -> tuple[bool, Optional[float]]:
    """
    Sequenza UI: RACCOGLI → SQUADRA → (truppe) → MARCIA.
    Ritorna (ok, eta_s).

    FIX 12/04/2026: ctx.matcher.find() → ctx.matcher.find_one() (2 occorrenze).
    """
    tap_raccogli    = _cfg(ctx, "TAP_RACCOGLI")
    tap_squadra     = _cfg(ctx, "TAP_SQUADRA")
    tap_marcia      = _cfg(ctx, "TAP_MARCIA")
    tap_cancella    = _cfg(ctx, "TAP_CANCELLA")
    tap_campo       = _cfg(ctx, "TAP_CAMPO_TESTO")
    tap_ok          = _cfg(ctx, "TAP_OK_TASTIERA")
    template_marcia = _cfg(ctx, "TEMPLATE_MARCIA")
    soglia          = _cfg(ctx, "TEMPLATE_SOGLIA")

    ctx.log_msg("Raccolta: RACCOGLI → SQUADRA")
    ctx.device.tap(tap_raccogli)
    time.sleep(0.5)
    ctx.device.tap(tap_squadra)
    time.sleep(1.4)

    # Verifica maschera invio aperta
    screen = ctx.device.screenshot()
    if screen:
        maschera = ctx.matcher.find_one(screen, template_marcia, threshold=soglia)
        if not maschera.found:
            ctx.log_msg("Raccolta: maschera invio NON aperta — retry")
            ctx.device.tap(tap_squadra)
            time.sleep(1.8)
            screen = ctx.device.screenshot()
            maschera2 = ctx.matcher.find_one(screen, template_marcia, threshold=soglia) if screen else None
            if maschera2 is None or not maschera2.found:
                ctx.log_msg("Raccolta: maschera invio ancora non aperta — FALLITO")
                return False, None

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

    # Tap MARCIA
    ctx.log_msg("Raccolta: tap MARCIA")
    ctx.device.tap(tap_marcia)
    time.sleep(0.8)

    # Verifica maschera chiusa (marcia partita)
    screen_post = ctx.device.screenshot()
    if screen_post:
        maschera_post = ctx.matcher.find_one(screen_post, template_marcia, threshold=soglia)
        if maschera_post.found:
            ctx.log_msg("Raccolta: maschera ancora aperta dopo MARCIA — retry")
            ctx.device.tap(tap_marcia)
            time.sleep(1.0)
            screen_post2 = ctx.device.screenshot()
            if screen_post2:
                maschera_post2 = ctx.matcher.find_one(screen_post2, template_marcia, threshold=soglia)
                if maschera_post2.found:
                    ctx.log_msg("Raccolta: maschera ancora aperta dopo retry — FALLITO")
                    return False, None
    return True, None


def _invia_squadra(ctx: TaskContext, tipo: str, blacklist: Blacklist,
                    cooldown_map: dict, n_truppe: int,
                    tipi_bloccati: set) -> tuple[bool, bool]:
    """
    Cerca nodo, verifica blacklist, invia marcia.

    Ritorna (marcia_ok, tipo_bloccato):
      marcia_ok     = True se la marcia è partita
      tipo_bloccato = True se il tipo deve essere aggiunto a tipi_bloccati

    FIX 12/04/2026: ctx.matcher.find() → ctx.matcher.find_one() (1 occorrenza
    nella verifica gather visibile).
    """
    _cerca_nodo(ctx, tipo)

    coord = _leggi_coordinate_nodo(ctx)
    if coord is None:
        ctx.log_msg(f"Raccolta [{tipo}]: coordinate non leggibili — skip")
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.4)
        return False, False

    cx, cy = coord
    chiave = f"{cx}_{cy}"

    # Verifica blacklist
    if blacklist.contiene(chiave):
        ctx.log_msg(f"Raccolta [{tipo}]: nodo ({cx},{cy}) in blacklist — riprovo CERCA")
        chiave_primo = chiave
        _cerca_nodo(ctx, tipo)
        coord2 = _leggi_coordinate_nodo(ctx)

        if coord2 is None or f"{coord2[0]}_{coord2[1]}" == chiave_primo:
            attesa = _cfg(ctx, "BLACKLIST_ATTESA_NODO")
            eta_prev = blacklist.get_eta(chiave_primo)
            if isinstance(eta_prev, (int, float)) and eta_prev > 0:
                attesa = int(min(attesa, max(8, eta_prev + 5)))
            ctx.log_msg(f"Raccolta [{tipo}]: nodo COMMITTED riproposto → cooldown {attesa}s")
            cooldown_map[tipo] = time.time() + attesa
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.4)
            return False, True

        cx2, cy2 = coord2
        chiave = f"{cx2}_{cy2}"
        if blacklist.contiene(chiave):
            ctx.log_msg(f"Raccolta [{tipo}]: nuovo nodo ({cx2},{cy2}) anche in blacklist — abbandono")
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.4)
            return False, False

    # Tap nodo
    tap_nodo = _cfg(ctx, "TAP_NODO")
    ctx.log_msg(f"Raccolta [{tipo}]: tap nodo ({cx},{cy})")
    ctx.device.tap(tap_nodo)
    time.sleep(0.7)

    # Verifica gather visibile
    screen_popup    = ctx.device.screenshot()
    template_gather = _cfg(ctx, "TEMPLATE_GATHER")
    soglia          = _cfg(ctx, "TEMPLATE_SOGLIA")

    if screen_popup:
        gather = ctx.matcher.find_one(screen_popup, template_gather, threshold=soglia)
        if not gather.found:
            ctx.log_msg(f"Raccolta [{tipo}]: GATHER non visibile dopo tap nodo — retry")
            ctx.device.tap(tap_nodo)
            time.sleep(1.0)
            screen_popup2 = ctx.device.screenshot()
            if screen_popup2:
                gather2 = ctx.matcher.find_one(screen_popup2, template_gather, threshold=soglia)
                if not gather2.found:
                    ctx.log_msg(f"Raccolta [{tipo}]: GATHER ancora non visibile — rollback")
                    ctx.device.key("KEYCODE_BACK")
                    time.sleep(0.4)
                    blacklist.rollback(chiave)
                    return False, False

    # RESERVED
    blacklist.reserve(chiave)
    ctx.log_msg(f"Raccolta [{tipo}]: nodo ({cx},{cy}) RESERVED")

    # Esegui marcia
    ok, eta_s = _esegui_marcia(ctx, n_truppe)

    if ok:
        blacklist.commit(chiave, eta_s)
        ctx.log_msg(f"Raccolta [{tipo}]: marcia OK → nodo ({cx},{cy}) COMMITTED")
        return True, False
    else:
        blacklist.rollback(chiave)
        ctx.log_msg(f"Raccolta [{tipo}]: marcia FALLITA → rollback nodo ({cx},{cy})")
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.5)
        return False, False


# ==============================================================================
# Loop principale invio marce
# ==============================================================================

def _loop_invio_marce(ctx: TaskContext, obiettivo: int,
                       attive_inizio: int, blacklist: Blacklist) -> int:
    """
    Loop invio squadre fino a slot pieni o MAX_FALLIMENTI.
    Ritorna il numero di squadre effettivamente inviate.
    """
    sequenza_base  = _cfg(ctx, "RACCOLTA_SEQUENZA")
    max_fallimenti = _cfg(ctx, "RACCOLTA_MAX_FALLIMENTI")
    n_truppe       = _cfg(ctx, "RACCOLTA_TRUPPE")

    tipi_bloccati: set[str] = set()
    cooldown_map: dict[str, float] = {}

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
            ctx.log_msg("Raccolta: tutti i tipi bloccati — abbandono")
            break

        ora = time.time()
        pronti = [t for t in tipi_disponibili if cooldown_map.get(t, 0) <= ora]
        if not pronti:
            t_min  = min(cooldown_map.get(t, ora) for t in tipi_disponibili)
            wait_s = max(1, int(t_min - ora))
            ctx.log_msg(f"Raccolta: tutti in cooldown — attendo {wait_s}s")
            time.sleep(wait_s)
            continue

        sequenza = _calcola_sequenza(obiettivo - attive_correnti, sequenza_base,
                                      tipi_bloccati)
        if not sequenza:
            ctx.log_msg("Raccolta: sequenza vuota — abbandono")
            break

        tipo = sequenza[idx_seq % len(sequenza)]
        idx_seq += 1

        if cooldown_map.get(tipo, 0) > time.time():
            continue
        if tipo in tipi_bloccati:
            continue

        ctx.log_msg(f"Raccolta: invio squadra {attive_correnti + 1}/{obiettivo} → {tipo}")
        ok, tipo_bloccato = _invia_squadra(ctx, tipo, blacklist, cooldown_map,
                                            n_truppe, tipi_bloccati)
        if ok:
            inviate         += 1
            attive_correnti += 1
            fallimenti_cons  = 0
            time.sleep(_cfg(ctx, "DELAY_POST_MARCIA"))
        else:
            if tipo_bloccato:
                tipi_bloccati.add(tipo)
            fallimenti_cons += 1

    ctx.log_msg(f"Raccolta: loop completato — {inviate} squadre inviate")
    return inviate


# ==============================================================================
# Task V6
# ==============================================================================

class RaccoltaTask(Task):
    """
    Task periodico (4h) che invia squadre raccoglitrici ai nodi risorse.
    Implementa il loop marce con blacklist RESERVED/COMMITTED, selezione
    tipo round-robin e recovery fallimenti.
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
        """
        Esegue la raccolta risorse.

        Parametri iniettabili per i test:
          attive_inizio : squadre già attive al momento dell'invocazione
          slot_liberi   : slot liberi (-1 = usa RACCOLTA_OBIETTIVO - attive_inizio)
          blacklist     : istanza Blacklist (creata internamente se None)
        """
        if not _cfg(ctx, "RACCOLTA_ABILITATA"):
            ctx.log_msg("Raccolta: modulo disabilitato — skip")
            return TaskResult(success=True, message="disabilitato", data={"inviate": 0})

        obiettivo = int(_cfg(ctx, "RACCOLTA_OBIETTIVO"))

        if slot_liberi < 0:
            libere = max(0, obiettivo - attive_inizio)
        else:
            libere = slot_liberi

        if libere == 0:
            ctx.log_msg(f"Raccolta: nessuna squadra libera ({attive_inizio}/{obiettivo}) — skip")
            return TaskResult(success=True, message="nessuna squadra libera", data={"inviate": 0})

        ctx.log_msg(f"Raccolta: start — attive={attive_inizio}/{obiettivo} libere={libere}")

        if blacklist is None:
            blacklist = Blacklist(
                committed_ttl=int(_cfg(ctx, "BLACKLIST_COMMITTED_TTL")),
                reserved_ttl=int(_cfg(ctx, "BLACKLIST_RESERVED_TTL")),
            )

        ctx.log_msg("Raccolta: navigazione → mappa")
        ctx.device.key("KEYCODE_MAP")
        time.sleep(2.0)

        inviate = 0
        try:
            inviate = _loop_invio_marce(ctx, obiettivo, attive_inizio, blacklist)
        except Exception as e:
            ctx.log_msg(f"Raccolta: errore nel loop marce: {e}")
            return TaskResult(success=False, message=f"errore: {e}", data={"inviate": inviate})
        finally:
            ctx.log_msg("Raccolta: ritorno in home")
            ctx.device.key("KEYCODE_HOME")

        ctx.log_msg(f"Raccolta: completata — {inviate}/{libere} squadre inviate")
        return TaskResult(success=True, message=f"{inviate} squadre inviate", data={"inviate": inviate})
