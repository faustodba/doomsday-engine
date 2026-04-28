# ==============================================================================
#  DOOMSDAY ENGINE V6 — tasks/raccolta_fast.py                          WU57
#
#  Variante FAST del task raccolta: sequenza tap ottimizzata con
#  verifiche solo essenziali (1-shot, no retry intermedi).
#  Verifica finale post-marcia conferma success della singola marcia
#  via OCR slot HOME. Recovery: BACK + vai_in_mappa + retry singolo.
#
#  ATTIVAZIONE: tipologia istanza = "raccolta_fast" (alternativa a
#  "raccolta_only" o "full"). Selezionata in main.py al boot tick istanza.
#
#  DESIGN (concordato con utente):
#    - Delay conservativi rispetto a standard ma ridotti
#    - Skip OCR livello pannello (sempre reset standard meno×7+più×N-1)
#    - Skip OCR livello nodo (accetta livello che troviamo)
#    - 1-shot verifiche tipo + popup gather + maschera marcia (no retry)
#    - Mantiene: lente verificata, territorio (gratis), no_squads (informativa)
#    - Pre-batch: leggi slot HOME → calcola N marce (1-5)
#    - Post-marcia: OCR slot conferma incremento; se non incrementa → recovery
#
#  STIMA velocità: ~50% più veloce di RaccoltaTask standard (4 marce ~70s
#  invece di ~140s, no errori).
#
#  RIUSO: tutti gli helper di tasks/raccolta.py vengono importati e riusati.
#  Niente duplicazione codice. Logica modificata solo nei punti del flow fast.
# ==============================================================================

from __future__ import annotations

import time
from typing import Optional

from core.task import Task, TaskContext, TaskResult


# ── Helpers riusati da raccolta.py ──────────────────────────────────────────
# Importi differiti dentro run() per evitare circular imports e per
# semplificare test isolati con mock.

_DEFAULTS_FAST: dict = {
    # Delay UI ottimizzati (conservativi).
    # Convenzione: < standard ma > 0.5x per stabilità.
    "FAST_DELAY_TAP_ICONA":    1.2,   # standard 1.8 (-33%)
    "FAST_DELAY_CERCA":         0.8,   # standard 1.5 (-47%)
    "FAST_DELAY_TAP_NODO":      1.5,   # standard 1.5 (uguale, popup essenziale)
    "FAST_DELAY_RACCOGLI":      0.8,   # standard 0.8 (uguale)
    "FAST_DELAY_SQUADRA":       1.2,   # standard 1.8 (-33%)
    "FAST_DELAY_MARCIA":        1.2,   # standard 1.5 (-20%)
    "FAST_DELAY_POST_MARCIA":   2.5,   # nuovo: stabilizzazione UI post-MARCIA
    "FAST_RECOVERY_RETRY":      1,     # max 1 retry recovery per marcia
}


def _fcfg(ctx: TaskContext, key: str):
    """Legge config FAST con fallback ai default modulo."""
    return ctx.config.get(key, _DEFAULTS_FAST[key])


# ==============================================================================
#  RaccoltaFastTask — task principale
# ==============================================================================

class RaccoltaFastTask(Task):
    """
    Variante FAST di RaccoltaTask. Selezione via tipologia istanza
    'raccolta_fast'. Stessa interfaccia Task standard.
    """

    @property
    def name(self) -> str:
        return "raccolta_fast"

    @property
    def schedule_type(self) -> str:
        return "always"

    @property
    def interval_hours(self) -> float:
        return 0.0

    def should_run(self, ctx: TaskContext) -> bool:
        # Stesso check di RaccoltaTask: device + matcher + navigator necessari
        return (
            ctx.device is not None
            and ctx.matcher is not None
            and ctx.navigator is not None
        )

    def run(self, ctx: TaskContext,
            slot_liberi: int = -1) -> TaskResult:
        """
        Flow:
          1. HOME → leggi slot (OCR già funziona) → calcola libere
          2. vai_in_mappa
          3. Loop libere: per ogni marcia
             a. CERCA fast (lente + tipo 1-shot + reset standard livello)
             b. leggi coord nodo
             c. tap nodo + popup gather 1-shot
             d. territorio check (gratis)
             e. RACCOGLI/SQUADRA/MARCIA fast (no retry intermedi)
             f. POST-MARCIA OCR HOME → confronto con attive_pre
                - Se incrementato → ok, prossima marcia
                - Se NO → recovery (BACK fino HOME + vai_in_mappa) + retry 1×
          4. Final: OCR HOME → riepilogo
        """
        # Import differito helper raccolta standard
        from tasks.raccolta import (
            _cerca_nodo, _leggi_coord_nodo, _tap_nodo_e_verifica_gather,
            _nodo_in_territorio, _reset_to_mappa,
            _aggiorna_slot_in_mappa,        # WU55 28/04 — legge slot in mappa
            _leggi_attive_post_marcia, Blacklist, BlacklistFuori, _cfg,
        )
        from shared.ocr_helpers import leggi_contatore_slot

        if not ctx.config.task_abilitato("raccolta_fast"):
            ctx.log_msg("RaccoltaFast: disabilitato — skip")
            return TaskResult(success=True, message="disabilitato",
                              data={"inviate": 0, "fast": True})

        # ── Step 0: navigazione HOME + lettura slot pre-batch ─────────────
        if not ctx.navigator.vai_in_home():
            return TaskResult(success=False, message="vai_in_home fallito",
                              data={"inviate": 0, "fast": True})

        time.sleep(1.0)  # stabilizzazione HOME

        obiettivo = int(ctx.config.get("max_squadre", _cfg(ctx, "RACCOLTA_OBIETTIVO")))
        n_truppe  = int(ctx.config.get("truppe", _cfg(ctx, "RACCOLTA_TRUPPE")) or 0)

        attive_inizio = -1
        if slot_liberi < 0:
            screen_home = ctx.device.screenshot()
            if screen_home is not None:
                attive_inizio, totale_ocr = leggi_contatore_slot(
                    screen_home, totale_noto=obiettivo)
                if totale_ocr > 0:
                    obiettivo = totale_ocr
            if attive_inizio < 0:
                ctx.log_msg("RaccoltaFast: OCR slot HOME fallito — skip task")
                return TaskResult(success=True, message="OCR slot HOME fallito",
                                  data={"inviate": 0, "fast": True})
            libere = max(0, obiettivo - attive_inizio)
        else:
            libere = slot_liberi
            attive_inizio = max(0, obiettivo - libere)

        if libere == 0:
            ctx.log_msg(f"RaccoltaFast: nessuna squadra libera ({attive_inizio}/{obiettivo}) — skip")
            return TaskResult(success=True, message="nessuna squadra libera",
                              data={"inviate": 0, "fast": True})

        ctx.log_msg(f"RaccoltaFast: start — attive={attive_inizio}/{obiettivo} libere={libere}")

        # ── Init blacklist + sequenza tipi ─────────────────────────────────
        blacklist       = Blacklist(
            committed_ttl=int(_cfg(ctx, "BLACKLIST_COMMITTED_TTL")),
            reserved_ttl=int(_cfg(ctx, "BLACKLIST_RESERVED_TTL")),
        )
        blacklist_fuori = BlacklistFuori(data_dir=_cfg(ctx, "BLACKLIST_FUORI_DIR"))
        sequenza_tipi   = list(_cfg(ctx, "RACCOLTA_SEQUENZA"))

        # Naviga in mappa una volta
        ctx.log_msg("RaccoltaFast: naviga → mappa")
        if not ctx.navigator.vai_in_mappa():
            return TaskResult(success=False, message="vai_in_mappa fallito",
                              data={"inviate": 0, "fast": True})

        # ── Loop marce ─────────────────────────────────────────────────────
        attive_corrente = attive_inizio
        inviate         = 0
        recovery_count  = 0
        marce_fallite   = 0
        idx_tipo        = 0
        recovery_retry_max = int(_fcfg(ctx, "FAST_RECOVERY_RETRY"))
        ts_start_batch  = time.time()

        for n_marcia in range(libere):
            tipo = sequenza_tipi[idx_tipo % len(sequenza_tipi)]
            ctx.log_msg(f"RaccoltaFast: ─── marcia {n_marcia+1}/{libere} tipo={tipo} ───")

            ok_marcia = self._tenta_marcia(
                ctx, tipo, n_truppe, blacklist, blacklist_fuori, obiettivo)

            if not ok_marcia:
                marce_fallite += 1
                ctx.log_msg(f"RaccoltaFast: marcia fallita — recovery")
                # Recovery: BACK fino HOME + vai_in_mappa
                if not self._recovery_marcia(ctx):
                    ctx.log_msg("RaccoltaFast: recovery fallito — abort batch")
                    break
                recovery_count += 1
                # Retry: prova ancora questa marcia (max 1 volta)
                if recovery_retry_max >= 1:
                    ctx.log_msg(f"RaccoltaFast: retry marcia {n_marcia+1} dopo recovery")
                    ok_marcia = self._tenta_marcia(
                        ctx, tipo, n_truppe, blacklist, blacklist_fuori, obiettivo)

            if ok_marcia:
                # WU55 28/04 — verifica post-marcia direttamente in MAPPA
                # (no più vai_in_home → OCR → vai_in_mappa). Risparmio ~10-15s
                # per marcia. Guardrail Scenario E: se MAP=(0,N) ma attive_pre>=1
                # → fallback HOME singolo (popup overlay ambiguità).
                # Rollback: git checkout wu55-pre-refactor-mappa -- tasks/raccolta_fast.py
                attive_post = _aggiorna_slot_in_mappa(
                    ctx, obiettivo, attive_corrente + 1
                )
                if attive_post > attive_corrente:
                    ctx.log_msg(
                        f"RaccoltaFast: ✓ marcia confermata "
                        f"({attive_corrente} → {attive_post})"
                    )
                    attive_corrente = attive_post
                    inviate += 1
                    idx_tipo += 1
                else:
                    ctx.log_msg(
                        f"RaccoltaFast: ✗ slot non incrementato "
                        f"({attive_corrente} → {attive_post}) — fallita"
                    )
                    marce_fallite += 1
                    # Non avanzo idx_tipo, riprova stesso tipo prossima iter

                # WU55 28/04 — NIENTE vai_in_mappa: siamo gia' in mappa post
                # _aggiorna_slot_in_mappa (no vai_in_home intermedio).
                # Solo se _aggiorna_slot_in_mappa ha fatto fallback HOME (caso
                # ambiguo/fail), saremmo in HOME → lì serve vai_in_mappa.
                # Detection: attive_post == -1 o == obiettivo via fallback
                # _reset_to_mappa che lascia in mappa. Helper sempre torna in
                # mappa quindi NO vai_in_mappa qui necessario.

        # ── Finale: torna HOME ─────────────────────────────────────────────
        try:
            ctx.navigator.vai_in_home()
        except Exception:
            pass

        durata_batch = round(time.time() - ts_start_batch, 1)
        sec_per_marcia = round(durata_batch / max(inviate, 1), 1) if inviate else 0
        ctx.log_msg(
            f"RaccoltaFast: completato — {inviate}/{libere} inviate "
            f"recovery={recovery_count} fallite={marce_fallite} "
            f"durata={durata_batch}s ({sec_per_marcia}s/marcia)"
        )
        return TaskResult(
            success=True,
            message=f"{inviate}/{libere} marce fast",
            data={
                "inviate":        inviate,
                "libere_iniziali": libere,
                "marce_fallite":  marce_fallite,
                "recovery_count": recovery_count,
                "durata_batch_s": durata_batch,
                "sec_per_marcia": sec_per_marcia,
                "fast":           True,
            },
        )

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _tenta_marcia(self, ctx: TaskContext, tipo: str, n_truppe: int,
                      blacklist, blacklist_fuori, obiettivo: int) -> bool:
        """
        Esegue 1 marcia FAST (sequenza tap + 1-shot verifiche).
        Ritorna True se la marcia è stata inviata (UI conferma); False altrimenti.
        Il chiamante poi verifica via OCR HOME se davvero il contatore è salito.
        """
        from tasks.raccolta import (
            _cerca_nodo, _leggi_coord_nodo, _nodo_in_territorio, _cfg,
        )

        # ─── STEP 1 FAST: CERCA ──────────────────────────────────────────
        # Riusa _cerca_nodo (già con _apri_lente_verificata + verifica tipo
        # 1-shot interno + reset standard livello). NB: la verifica tipo
        # nel codice standard ha 2 retry — il fast li accetta come essenziali
        # perché l'OCR del tipo è critico.
        if not _cerca_nodo(ctx, tipo):
            ctx.log_msg(f"RaccoltaFast [{tipo}]: CERCA fallita")
            return False

        # ─── STEP 2: leggi coord ─────────────────────────────────────────
        chiave = _leggi_coord_nodo(ctx)
        if chiave is None:
            ctx.log_msg(f"RaccoltaFast [{tipo}]: nessun nodo disponibile")
            return False

        # ─── Blacklist check (gratis, evita spreco) ──────────────────────
        _fuori_terr_ok = bool(_cfg(ctx, "RACCOLTA_FUORI_TERRITORIO_ABILITATA"))
        if blacklist_fuori.contiene(chiave) and not _fuori_terr_ok:
            ctx.log_msg(f"RaccoltaFast [{tipo}]: nodo {chiave} in blacklist fuori — skip")
            return False
        if blacklist.contiene(chiave):
            ctx.log_msg(f"RaccoltaFast [{tipo}]: nodo {chiave} in blacklist RAM — skip")
            return False

        blacklist.reserve(chiave)

        # ─── STEP 3 FAST: tap nodo + popup gather 1-shot ─────────────────
        tap_nodo        = _cfg(ctx, "TAP_NODO")
        template_gather = _cfg(ctx, "TEMPLATE_GATHER")
        soglia          = _cfg(ctx, "TEMPLATE_SOGLIA")
        roi_gather      = _cfg(ctx, "ROI_GATHER")

        ctx.log_msg(f"RaccoltaFast [{tipo}]: tap nodo {tap_nodo}")
        ctx.device.tap(tap_nodo)
        time.sleep(_fcfg(ctx, "FAST_DELAY_TAP_NODO"))

        screen_popup = ctx.device.screenshot()
        if screen_popup is None:
            blacklist.rollback(chiave)
            ctx.log_msg(f"RaccoltaFast [{tipo}]: screenshot None")
            return False

        r = ctx.matcher.find_one(screen_popup, template_gather,
                                  threshold=soglia, zone=roi_gather)
        if not r.found:
            ctx.log_msg(
                f"RaccoltaFast [{tipo}]: pin_gather score={r.score:.3f} → "
                f"NON trovato (no retry)"
            )
            blacklist.rollback(chiave)
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.5)
            return False

        # ─── STEP 4: territorio (mantieni: gratis e protegge da spreco) ──
        if not _fuori_terr_ok and not _nodo_in_territorio(screen_popup, tipo, ctx):
            ctx.log_msg(
                f"RaccoltaFast [{tipo}]: nodo {chiave} FUORI territorio — "
                f"blacklist + back"
            )
            blacklist_fuori.aggiungi(chiave, tipo)
            blacklist.rollback(chiave)
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.5)
            return False

        # ─── STEP 5 FAST: SKIP OCR livello nodo ──────────────────────────
        # Accetta livello che troviamo. Reward variabile ma niente OCR fail.

        # ─── STEP 6 FAST: RACCOGLI/SQUADRA/MARCIA ────────────────────────
        ok_invio = self._invia_marcia_fast(ctx, n_truppe)
        if not ok_invio:
            ctx.log_msg(f"RaccoltaFast [{tipo}]: invio marcia fallito")
            blacklist.rollback(chiave)
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.5)
            return False

        # Marcia inviata → commit blacklist (occupazione nodo)
        blacklist.commit(chiave, eta_s=None)
        return True

    def _invia_marcia_fast(self, ctx: TaskContext, n_truppe: int) -> bool:
        """
        STEP 6 FAST: tap RACCOGLI → SQUADRA → check maschera 1-shot →
        truppe → MARCIA. NO retry intermedi. NO verifica chiusura maschera.
        """
        from tasks.raccolta import _cfg

        tap_raccogli    = _cfg(ctx, "TAP_RACCOGLI")
        tap_squadra     = _cfg(ctx, "TAP_SQUADRA")
        tap_marcia      = _cfg(ctx, "TAP_MARCIA")
        tap_cancella    = _cfg(ctx, "TAP_CANCELLA")
        tap_campo       = _cfg(ctx, "TAP_CAMPO_TESTO")
        tap_ok          = _cfg(ctx, "TAP_OK_TASTIERA")
        template_marcia = _cfg(ctx, "TEMPLATE_MARCIA")
        soglia          = _cfg(ctx, "TEMPLATE_SOGLIA")

        ctx.log_msg("RaccoltaFast: RACCOGLI → SQUADRA")
        ctx.device.tap(tap_raccogli)
        time.sleep(_fcfg(ctx, "FAST_DELAY_RACCOGLI"))
        ctx.device.tap(tap_squadra)
        time.sleep(_fcfg(ctx, "FAST_DELAY_SQUADRA"))

        # Verifica maschera 1-shot (no retry)
        screen = ctx.device.screenshot()
        if screen is not None:
            m = ctx.matcher.find_one(screen, template_marcia, threshold=soglia)
            if not m.found:
                ctx.log_msg(f"RaccoltaFast: maschera score={m.score:.3f} → NON aperta (no retry)")
                return False

        # Imposta truppe
        if n_truppe and n_truppe > 0:
            ctx.device.tap(tap_cancella); time.sleep(0.4)
            ctx.device.tap(tap_campo);    time.sleep(0.4)
            ctx.device.key("KEYCODE_CTRL_A"); time.sleep(0.15)
            ctx.device.key("KEYCODE_DEL");    time.sleep(0.15)
            ctx.device.input_text(str(n_truppe)); time.sleep(0.25)
            ctx.device.tap(tap_ok); time.sleep(0.25)

        ctx.log_msg("RaccoltaFast: tap MARCIA")
        ctx.device.tap(tap_marcia)
        time.sleep(_fcfg(ctx, "FAST_DELAY_MARCIA"))
        # NO verifica chiusura maschera (la verifica avviene in HOME via OCR slot)
        return True

    def _verifica_post_marcia(self, ctx: TaskContext, obiettivo: int) -> int:
        """
        DEPRECATO 28/04/2026 — non più usato dal flow principale.
        Sostituito da `_aggiorna_slot_in_mappa()` di tasks.raccolta che legge
        slot direttamente in mappa (no vai_in_home → OCR → vai_in_mappa).

        Mantenuto solo per eventuale uso esterno/test. Non rimuovere senza
        verificare assenza di chiamanti.

        Torna in HOME → sleep stabilizzazione → OCR slot.
        Returns attive_post (-1 se OCR fail, valore conservativo).
        """
        from shared.ocr_helpers import leggi_contatore_slot

        # Naviga in HOME
        try:
            ctx.navigator.vai_in_home()
        except Exception:
            pass
        time.sleep(_fcfg(ctx, "FAST_DELAY_POST_MARCIA"))

        # OCR slot HOME (ground truth)
        screen = ctx.device.screenshot()
        if screen is None:
            return -1
        attive, _totale = leggi_contatore_slot(screen, totale_noto=obiettivo)
        return attive

    def _recovery_marcia(self, ctx: TaskContext) -> bool:
        """
        Recovery dopo fail singola marcia: BACK fino HOME + vai_in_mappa.
        Returns True se mappa raggiunta (può tentare retry).
        """
        ctx.log_msg("RaccoltaFast: recovery → BACK + vai_in_home + vai_in_mappa")
        # Più BACK per uscire da popup/maschere aperte
        for _ in range(3):
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.4)
        try:
            if not ctx.navigator.vai_in_home():
                return False
            time.sleep(1.0)
            if not ctx.navigator.vai_in_mappa():
                return False
            return True
        except Exception as exc:
            ctx.log_msg(f"RaccoltaFast: recovery exception: {exc}")
            return False
