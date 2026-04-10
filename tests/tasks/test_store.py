# ==============================================================================
#  DOOMSDAY ENGINE V6 - tests/tasks/test_store.py      → C:\doomsday-engine\tests\tasks\test_store.py
#
#  Test unitari per tasks/store.py.
#
#  Scenari coperti:
#    - should_run(): device None, matcher None, config disabilitato
#    - _rileva_banner(): aperto, chiuso, sconosciuto
#    - _conta_pulsanti(): zero, uno, più pulsanti
#    - _mappa_esito(): tutti gli _Esito → TaskResult corretto
#    - run() via FakeDevice:
#        * store trovato passo 0 → completato con acquisti
#        * store trovato con mercante diretto
#        * store non trovato dopo griglia completa
#        * label non trovata dopo tap store
#        * carrello non trovato
#        * merchant non confermato
#        * free refresh eseguito
# ==============================================================================

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from tasks.store import StoreConfig, StoreTask, _Esito


# ==============================================================================
# Fake infrastructure (stessa struttura di test_boost.py)
# ==============================================================================

@dataclass
class FakeMatch:
    cx:    int   = 480
    cy:    int   = 270
    score: float = 0.90
    found: bool  = True


class FakeScreenshot:
    pass


class FakeDevice:
    def __init__(self, name: str = "FAKE_00") -> None:
        self.name  = name
        self.calls: list[tuple] = []

    async def screenshot(self):
        self.calls.append(("screenshot",))
        return FakeScreenshot()

    async def tap(self, x: int, y: int) -> None:
        self.calls.append(("tap", x, y))

    async def back(self) -> None:
        self.calls.append(("back",))

    async def swipe(self, x1, y1, x2, y2, duration_ms=400) -> None:
        self.calls.append(("swipe", x1, y1, x2, y2))

    def tap_count(self) -> int:
        return sum(1 for c in self.calls if c[0] == "tap")

    def back_count(self) -> int:
        return sum(1 for c in self.calls if c[0] == "back")

    def swipe_count(self) -> int:
        return sum(1 for c in self.calls if c[0] == "swipe")


class FakeMatcher:
    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self._scores: dict[str, float] = scores or {}
        self._finds:  dict[str, FakeMatch | None] = {}
        self._all:    dict[str, list[FakeMatch]] = {}

    def set_score(self, tmpl: str, score: float) -> None:
        self._scores[tmpl] = score

    def set_find(self, tmpl: str, match: FakeMatch | None) -> None:
        self._finds[tmpl] = match

    def set_all(self, tmpl: str, matches: list[FakeMatch]) -> None:
        self._all[tmpl] = matches

    def score(self, shot, tmpl: str, zone=None) -> float:
        return self._scores.get(tmpl, 0.0)

    def exists(self, shot, tmpl: str, threshold: float = 0.75, zone=None) -> bool:
        return self.score(shot, tmpl) >= threshold

    def find_one(self, shot, tmpl: str, threshold: float = 0.75, zone=None) -> FakeMatch:
        if tmpl in self._finds:
            m = self._finds[tmpl]
            if m and m.score >= threshold:
                return m
            return FakeMatch(score=0.0, found=False)
        s = self.score(shot, tmpl)
        if s >= threshold:
            return FakeMatch(score=s, found=True)
        return FakeMatch(score=s, found=False)

    def find_all(self, shot, tmpl: str, threshold: float = 0.75,
                 zone=None, cluster_px: int = 20) -> list[FakeMatch]:
        if tmpl in self._all:
            return [m for m in self._all[tmpl] if m.score >= threshold]
        s = self.score(shot, tmpl)
        if s >= threshold:
            return [FakeMatch(score=s)]
        return []


# ==============================================================================
# Helpers
# ==============================================================================

class FakeConfig:
    def __init__(self, abilitato: bool = True):
        self._abilitato = abilitato

    def task_abilitato(self, nome: str) -> bool:
        return self._abilitato if nome == "store" else True


class FakeLogger:
    def info(self, task, msg, **kw): pass
    def error(self, task, msg, **kw): pass


def _make_ctx(device=None, matcher=None, navigator=None, abilitato=True):
    from core.task import TaskContext
    return TaskContext(
        instance_name="FAKE_00",
        config=FakeConfig(abilitato),
        state=object(),
        log=FakeLogger(),
        device=device,
        matcher=matcher,
        navigator=navigator,
    )


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _cfg() -> StoreConfig:
    return StoreConfig()


def _matcher_store_trovato(**extra) -> FakeMatcher:
    """Matcher con store trovato al passo 0, merchant confermato, niente pulsanti."""
    cfg = _cfg()
    m   = FakeMatcher({
        cfg.tmpl_store:         0.85,
        cfg.tmpl_store_attivo:  0.85,
        cfg.tmpl_carrello:      0.80,
        cfg.tmpl_merchant:      0.80,
        cfg.tmpl_mercante:      0.10,
        cfg.tmpl_banner_aperto: 0.10,
        cfg.tmpl_banner_chiuso: 0.10,
        cfg.tmpl_no_refresh:    0.10,
        cfg.tmpl_free_refresh:  0.10,
        "pin/pin_home.png":     0.85,
        **extra,
    })
    m.set_find(cfg.tmpl_store, FakeMatch(cx=400, cy=300, score=0.85))
    m.set_find(cfg.tmpl_carrello, FakeMatch(cx=600, cy=400, score=0.80))
    return m


# ==============================================================================
# Test: should_run()
# ==============================================================================

class TestShouldRun:

    def test_device_none_ritorna_false(self):
        ctx = _make_ctx(device=None, matcher=FakeMatcher())
        assert StoreTask().should_run(ctx) is False

    def test_matcher_none_ritorna_false(self):
        ctx = _make_ctx(device=FakeDevice(), matcher=None)
        assert StoreTask().should_run(ctx) is False

    def test_disabilitato_ritorna_false(self):
        ctx = _make_ctx(device=FakeDevice(), matcher=FakeMatcher(), abilitato=False)
        assert StoreTask().should_run(ctx) is False

    def test_ok_ritorna_true(self):
        ctx = _make_ctx(device=FakeDevice(), matcher=FakeMatcher(), abilitato=True)
        assert StoreTask().should_run(ctx) is True


# ==============================================================================
# Test: _rileva_banner()
# ==============================================================================

class TestRilevaBanner:

    def _task(self) -> StoreTask:
        return StoreTask()

    def test_aperto(self):
        cfg = _cfg()
        m   = FakeMatcher({cfg.tmpl_banner_aperto: 0.90, cfg.tmpl_banner_chiuso: 0.10})
        assert self._task()._rileva_banner(FakeScreenshot(), m, cfg) == "aperto"

    def test_chiuso(self):
        cfg = _cfg()
        m   = FakeMatcher({cfg.tmpl_banner_aperto: 0.10, cfg.tmpl_banner_chiuso: 0.90})
        assert self._task()._rileva_banner(FakeScreenshot(), m, cfg) == "chiuso"

    def test_sconosciuto(self):
        cfg = _cfg()
        m   = FakeMatcher({cfg.tmpl_banner_aperto: 0.10, cfg.tmpl_banner_chiuso: 0.10})
        assert self._task()._rileva_banner(FakeScreenshot(), m, cfg) == "sconosciuto"

    def test_entrambi_sopra_soglia_vince_aperto(self):
        """Se entrambi sopra soglia, vince il più alto."""
        cfg = _cfg()
        m   = FakeMatcher({cfg.tmpl_banner_aperto: 0.95, cfg.tmpl_banner_chiuso: 0.88})
        assert self._task()._rileva_banner(FakeScreenshot(), m, cfg) == "aperto"


# ==============================================================================
# Test: _conta_pulsanti()
# ==============================================================================

class TestContaPulsanti:

    def test_nessun_pulsante(self):
        cfg  = _cfg()
        m    = FakeMatcher()   # tutti score=0.0
        res  = StoreTask()._conta_pulsanti(FakeScreenshot(), m, cfg)
        assert res == []

    def test_un_pulsante_legno(self):
        cfg = _cfg()
        m   = FakeMatcher()
        m.set_all(cfg.tmpl_legno, [FakeMatch(cx=300, cy=200, score=0.85)])
        res = StoreTask()._conta_pulsanti(FakeScreenshot(), m, cfg)
        assert len(res) == 1
        assert res[0][3] == cfg.tmpl_legno

    def test_pulsanti_ordinati_per_cy(self):
        """I candidati devono essere ordinati top-down (cy crescente)."""
        cfg = _cfg()
        m   = FakeMatcher()
        m.set_all(cfg.tmpl_legno, [
            FakeMatch(cx=300, cy=300, score=0.85),
            FakeMatch(cx=300, cy=100, score=0.85),
        ])
        res = StoreTask()._conta_pulsanti(FakeScreenshot(), m, cfg)
        assert res[0][0] < res[1][0]   # cy crescente

    def test_piu_tipi_pulsanti(self):
        cfg = _cfg()
        m   = FakeMatcher()
        m.set_all(cfg.tmpl_legno,    [FakeMatch(cx=200, cy=150, score=0.85)])
        m.set_all(cfg.tmpl_pomodoro, [FakeMatch(cx=400, cy=250, score=0.82)])
        res = StoreTask()._conta_pulsanti(FakeScreenshot(), m, cfg)
        assert len(res) == 2


# ==============================================================================
# Test: _mappa_esito()
# ==============================================================================

class TestMappaEsito:

    def _map(self, esito, acquistati=0, refreshed=False):
        return StoreTask._mappa_esito(esito, acquistati, refreshed, log=lambda m: None)

    def test_completato_ok(self):
        r = self._map(_Esito.COMPLETATO, acquistati=3, refreshed=True)
        assert r.success is True
        assert r.skipped is False
        assert r.data["acquistati"] == 3
        assert r.data["refreshed"] is True

    def test_completato_zero_acquisti_ok(self):
        """Acquistati=0 non è un errore — niente da comprare."""
        r = self._map(_Esito.COMPLETATO, acquistati=0)
        assert r.success is True

    def test_store_non_trovato_skip(self):
        r = self._map(_Esito.STORE_NON_TROVATO)
        assert r.success is True
        assert r.skipped is True

    def test_label_non_trovata_skip(self):
        r = self._map(_Esito.LABEL_NON_TROVATA)
        assert r.skipped is True

    def test_carrello_non_trovato_skip(self):
        r = self._map(_Esito.CARRELLO_NON_TROVATO)
        assert r.skipped is True

    def test_merchant_non_aperto_skip(self):
        r = self._map(_Esito.MERCHANT_NON_APERTO)
        assert r.skipped is True

    def test_errore_fail(self):
        r = self._map(_Esito.ERRORE)
        assert r.success is False


# ==============================================================================
# Test: run() — store trovato e completato
# ==============================================================================

class TestStoreCompletato:

    def test_ritorna_ok(self):
        device  = FakeDevice()
        matcher = _matcher_store_trovato()
        ctx     = _make_ctx(device=device, matcher=matcher)
        result  = run(StoreTask().run(ctx))
        assert result.success is True
        assert result.skipped is False

    def test_tap_store_eseguito(self):
        device  = FakeDevice()
        matcher = _matcher_store_trovato()
        ctx     = _make_ctx(device=device, matcher=matcher)
        run(StoreTask().run(ctx))
        taps = [c for c in device.calls if c[0] == "tap" and c[1] == 400]
        assert len(taps) >= 1

    def test_back_chiude_negozio(self):
        device  = FakeDevice()
        matcher = _matcher_store_trovato()
        ctx     = _make_ctx(device=device, matcher=matcher)
        run(StoreTask().run(ctx))
        assert device.back_count() >= 1


# ==============================================================================
# Test: run() — mercante diretto (skip carrello)
# ==============================================================================

class TestMercanteDiretto:

    def test_skip_carrello(self):
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = _matcher_store_trovato()
        matcher.set_score(cfg.tmpl_mercante, 0.90)   # mercante visibile
        ctx     = _make_ctx(device=device, matcher=matcher)
        run(StoreTask().run(ctx))

        # Nessun tap su carrello
        carrello_taps = [
            c for c in device.calls
            if c[0] == "tap" and c[1] == 600 and c[2] == 400
        ]
        assert len(carrello_taps) == 0


# ==============================================================================
# Test: run() — store non trovato
# ==============================================================================

class TestStoreNonTrovato:

    def _matcher_no_store(self) -> FakeMatcher:
        cfg = _cfg()
        return FakeMatcher({
            cfg.tmpl_store:         0.20,
            cfg.tmpl_banner_aperto: 0.10,
            cfg.tmpl_banner_chiuso: 0.10,
            "pin/pin_home.png":     0.85,
        })

    def test_ritorna_skip(self):
        device  = FakeDevice()
        matcher = self._matcher_no_store()
        ctx     = _make_ctx(device=device, matcher=matcher)
        result  = run(StoreTask().run(ctx))
        assert result.success is True
        assert result.skipped is True

    def test_esegue_tutti_swipe_griglia(self):
        """Deve tentare tutti i 24 swipe della griglia spirale."""
        device  = FakeDevice()
        matcher = self._matcher_no_store()
        ctx     = _make_ctx(device=device, matcher=matcher)
        run(StoreTask().run(ctx))
        # 25 passi griglia, passo 0 nessuno swipe → 24 swipe mappa
        assert device.swipe_count() == 24


# ==============================================================================
# Test: run() — label non trovata
# ==============================================================================

class TestLabelNonTrovata:

    def test_ritorna_skip(self):
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = _matcher_store_trovato()
        matcher.set_score(cfg.tmpl_store_attivo, 0.10)   # label assente
        ctx     = _make_ctx(device=device, matcher=matcher)
        result  = run(StoreTask().run(ctx))
        assert result.skipped is True

    def test_back_eseguito(self):
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = _matcher_store_trovato()
        matcher.set_score(cfg.tmpl_store_attivo, 0.10)
        ctx     = _make_ctx(device=device, matcher=matcher)
        run(StoreTask().run(ctx))
        assert device.back_count() >= 1


# ==============================================================================
# Test: run() — free refresh
# ==============================================================================

class TestFreeRefresh:

    def test_refresh_eseguito(self):
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = _matcher_store_trovato()
        matcher.set_score(cfg.tmpl_no_refresh,   0.10)
        matcher.set_score(cfg.tmpl_free_refresh, 0.90)
        matcher.set_find(cfg.tmpl_free_refresh,
                         FakeMatch(cx=500, cy=500, score=0.90))
        ctx    = _make_ctx(device=device, matcher=matcher)
        result = run(StoreTask().run(ctx))

        assert result.success is True
        assert result.data.get("refreshed") is True

    def test_no_refresh_skip_refresh(self):
        """Se pin_no_refresh trovato → non esegue refresh."""
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = _matcher_store_trovato()
        matcher.set_score(cfg.tmpl_no_refresh, 0.90)
        ctx    = _make_ctx(device=device, matcher=matcher)
        result = run(StoreTask().run(ctx))
        assert result.data.get("refreshed") is False


# ==============================================================================
# Test: StoreConfig defaults
# ==============================================================================

class TestStoreConfig:

    def test_griglia_25_passi(self):
        assert len(StoreConfig().griglia) == 25

    def test_primo_passo_zero(self):
        assert StoreConfig().griglia[0] == (0, 0)

    def test_pin_acquisto_tre_elementi(self):
        assert len(StoreConfig().pin_acquisto) == 3

    def test_soglie_in_range(self):
        cfg = StoreConfig()
        for attr in ("soglia_store", "soglia_banner", "soglia_store_attivo",
                     "soglia_carrello", "soglia_merchant", "soglia_mercante",
                     "soglia_acquisto", "soglia_free_refresh", "soglia_no_refresh"):
            val = getattr(cfg, attr)
            assert 0 < val < 1, f"{attr} fuori range: {val}"

    def test_name_ritorna_store(self):
        assert StoreTask().name() == "store"
