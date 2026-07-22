"""
tasks/mall_daily.py — MallDailyTask V6
============================================================================
Task (22/07/2026) — claim giornalieri gratuiti nel menu Mall: Daily Boost
"Claim" (Intermediate Resource Pack) + Limited-Time Promo → Daily Present
"Free" (risorse base). Tutti gli altri elementi nello stesso menu sono a
pagamento (Daily Boost X1/X2/X3, Monthly Special Pack, Double Gems,
Premium Packs, Mystery Treasure, Doomsday Courier, Privileges
Subscription) e NON vengono mai toccati — solo i due claim esplicitamente
gratuiti, verificati dal vivo.

Calibrato live via ADB diretto su FAU_00 (22/07, bot fermo, sessione di
mappatura manuale). Posizioni FISSE (icone/tab non si spostano tra
istanze/sessioni — confermato dall'utente). Verificato end-to-end con tap
reali: Daily Boost → "You obtained Intermediate Resource Pack X2!";
Daily Present → "You obtained 5m Construction Speedup X5, Battle Manual
(100 EXP) X5, 1,000 Food X5, 1,000 Wood X5, 500 Steel X5!".

FLUSSO:
  - HOME → tap icona Mall (770,62).
  - Se appare il popup "Privileges Subscription Trial" (stesso banner del
    catalogo WU237, può ripresentarsi come intro al primo ingresso Mall
    della sessione) → chiudi con X (813,94), MAI "Go Claim".
  - Tab Daily Boost (73,373): se l'icona "Claim" (badge rosso) è presente
    → tap (260,75). Se già "Claimed" (icona diversa/badge assente) → skip,
    nessun tap sui pacchetti X1/X2/X3 sottostanti.
  - Tab Limited-Time Promo (73,233): apre di default sulla sotto-tab
    "Daily Present". Se il pulsante verde "Free" è presente → tap
    (789,456). Dopo il claim la vista passa AUTOMATICAMENTE alla
    sotto-tab successiva (a pagamento, es. "Monthly Special Pack") — non
    si tocca, si esce subito.
  - Back → HOME (singolo tap fisso + `navigator.vai_in_home()` come
    verifica/correzione — MAI un secondo tap cieco alle stesse coordinate:
    su HOME quella zona è l'icona avatar/Commander Info, non "back").

REGOLA SICUREZZA: si tappano SOLO "Claim" (Daily Boost) e "Free" (Daily
Present) — verificati live gratuiti, nessun addebito, messaggio "You
obtained...". Mai altri pulsanti/tab del Mall.

Schedule: daily (via task_setup.json) — un tentativo al giorno basta.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from core.task import Task, TaskContext, TaskResult


@dataclass
class MallDailyConfig:
    tap_mall_icon: tuple[int, int] = (770, 62)
    wait_mall: float = 2.5

    # Privileges Subscription Trial (WU237) puo' ripresentarsi come intro Mall
    pin_privileges_title: str = "pin/pin_privileges_subscription_title.png"
    soglia_privileges: float = 0.80
    zona_privileges: tuple[int, int, int, int] = (150, 125, 660, 185)
    tap_privileges_x: tuple[int, int] = (813, 94)
    wait_dismiss: float = 1.5

    # Tab Daily Boost
    tap_tab_daily_boost: tuple[int, int] = (73, 373)
    wait_tab: float = 2.0
    pin_daily_boost_claim: str = "pin/pin_mall_daily_boost_claim.png"
    soglia_daily_boost: float = 0.80
    zona_daily_boost: tuple[int, int, int, int] = (225, 45, 300, 115)
    tap_daily_boost_claim: tuple[int, int] = (260, 75)
    wait_claim: float = 2.0

    # Tab Limited-Time Promo -> sotto-tab Daily Present (default all'apertura)
    tap_tab_limited_promo: tuple[int, int] = (73, 233)
    pin_daily_present_free: str = "pin/pin_mall_daily_present_free.png"
    soglia_daily_present: float = 0.80
    zona_daily_present: tuple[int, int, int, int] = (655, 435, 925, 478)
    tap_daily_present_free: tuple[int, int] = (789, 456)

    # Uscita: un solo tap back (Mall -> HOME), mai un secondo tap cieco
    # alla stessa coordinata (su HOME e' l'icona avatar/Commander Info).
    tap_back: tuple[int, int] = (30, 30)
    wait_back: float = 1.5


class MallDailyTask(Task):
    """Claim giornalieri gratuiti nel Mall: Daily Boost + Daily Present.
    Non tocca mai pacchetti a pagamento (X1/X2/X3, Monthly Special Pack,
    Double Gems, Premium Packs, Mystery Treasure, Doomsday Courier,
    Privileges Subscription)."""

    def __init__(self, config: MallDailyConfig | None = None) -> None:
        self._cfg = config or MallDailyConfig()

    def name(self) -> str:
        return "mall_daily"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            if not ctx.config.task_abilitato(self.name()):
                return False
        return True

    # ------------------------------------------------------------------

    def _dismiss_privileges_popup(self, ctx, cfg, log) -> bool:
        """Se il popup Privileges Subscription Trial e' presente (intro
        Mall), lo chiude con la X. Mai il pulsante 'Go Claim'."""
        shot = ctx.device.screenshot()
        m = ctx.matcher.find_one(shot, cfg.pin_privileges_title,
                                 threshold=cfg.soglia_privileges, zone=cfg.zona_privileges)
        if m.found:
            log(f"[MALL_DAILY] popup Privileges Subscription Trial rilevato "
                f"(score={m.score:.3f}) → chiudo con X, mai Go Claim")
            ctx.device.tap(*cfg.tap_privileges_x)
            time.sleep(cfg.wait_dismiss)
            return True
        return False

    def _claim_daily_boost(self, ctx, cfg, log) -> bool:
        ctx.device.tap(*cfg.tap_tab_daily_boost)
        time.sleep(cfg.wait_tab)
        shot = ctx.device.screenshot()
        m = ctx.matcher.find_one(shot, cfg.pin_daily_boost_claim,
                                 threshold=cfg.soglia_daily_boost, zone=cfg.zona_daily_boost)
        if not m.found:
            log(f"[MALL_DAILY] Daily Boost: nessun Claim disponibile "
                f"(score={m.score:.3f}) → già ritirato oggi")
            return False
        log(f"[MALL_DAILY] Daily Boost: Claim disponibile (score={m.score:.3f}) → tap")
        ctx.device.tap(*cfg.tap_daily_boost_claim)
        time.sleep(cfg.wait_claim)
        return True

    def _claim_daily_present(self, ctx, cfg, log) -> bool:
        ctx.device.tap(*cfg.tap_tab_limited_promo)
        time.sleep(cfg.wait_tab)
        shot = ctx.device.screenshot()
        m = ctx.matcher.find_one(shot, cfg.pin_daily_present_free,
                                 threshold=cfg.soglia_daily_present, zone=cfg.zona_daily_present)
        if not m.found:
            log(f"[MALL_DAILY] Daily Present: nessun Free disponibile "
                f"(score={m.score:.3f}) → già ritirato oggi")
            return False
        log(f"[MALL_DAILY] Daily Present: Free disponibile (score={m.score:.3f}) → tap")
        ctx.device.tap(*cfg.tap_daily_present_free)
        time.sleep(cfg.wait_claim)
        # Dopo il claim la sotto-tab avanza automaticamente su un pacchetto
        # a pagamento (es. Monthly Special Pack) — non si tocca, si esce.
        return True

    # ------------------------------------------------------------------

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg, log = self._cfg, ctx.log_msg
        if ctx.navigator is not None and not ctx.navigator.vai_in_home():
            return TaskResult.fail("Navigator non ha raggiunto HOME", step="vai_in_home")

        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("mall_daily", getattr(ctx, "instance_name", "_unknown"))
        try:
            ctx.device.tap(*cfg.tap_mall_icon)
            time.sleep(cfg.wait_mall)
            debug.snap("01_mall", ctx.device.screenshot())
            self._dismiss_privileges_popup(ctx, cfg, log)

            boost_claimed = self._claim_daily_boost(ctx, cfg, log)
            debug.snap("02_post_daily_boost", ctx.device.screenshot())

            present_claimed = self._claim_daily_present(ctx, cfg, log)
            debug.snap("03_post_daily_present", ctx.device.screenshot())

            ctx.device.tap(*cfg.tap_back)
            time.sleep(cfg.wait_back)
            if ctx.navigator is not None:
                ctx.navigator.vai_in_home()
            debug.snap("04_home", ctx.device.screenshot())

            log(f"[MALL_DAILY] completato — daily_boost={boost_claimed} "
                f"daily_present={present_claimed}")
            debug.flush(success=True,
                        force=not (boost_claimed or present_claimed),
                        log_fn=log)
            return TaskResult.ok(f"Mall Daily — daily_boost={boost_claimed} "
                                 f"daily_present={present_claimed}",
                                 daily_boost=boost_claimed, daily_present=present_claimed)
        except Exception as exc:
            log(f"[MALL_DAILY] eccezione: {exc}")
            debug.snap("99_exception", ctx.device.screenshot())
            debug.flush(success=False, log_fn=log)
            return TaskResult.fail(f"Eccezione: {exc}", step="run")
