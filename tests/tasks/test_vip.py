# ==============================================================================
#  DOOMSDAY ENGINE V6 - tests/tasks/test_vip.py       → C:\doomsday-engine\tests\tasks\test_vip.py
#
#  Test unitari per tasks/vip.py.
#
#  Scenari coperti:
#    - should_run(): device None, matcher None, config disabilitato
#    - _mappa_esito(): tutti gli esiti → TaskResult corretto
#    - _check_pin(): trovato, non trovato, trovato al retry
#    - _polling_gate(): trovato al primo poll, non trovato
#    - _gestisci_cassaforte(): già ritirata, disponibile+ok, anomalia nessun pin
#    - _gestisci_claim_free(): già ritirato, disponibile+ok, anomalia nessun pin
#    - run():
#        * completato al primo tentativo (cass+free entrambe ok)
#        * cassaforte già ritirata + free ok
#        * maschera non aperta → skip dopo max_tentativi
#        * BACK×3 sempre eseguiti dopo ogni tentativo
# ==============================================================================

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tasks.vip import VipConfig, VipTask, _Esito


# ==============================================================================
# Fake infrastructure
# ==============================================================================

class FakeScreenshot:
    pass


class FakeDevice:
    def __init__(self, name: str = "FAKE_00") -> None:
        self.name  = name
        self.calls: list[tuple] = []

    def screenshot(self):
        self.calls.append(("screenshot",))
        return FakeScreenshot()

    def tap(self, x: int, y: int) -> None:
        self.calls.append(("tap", x, y))

    def back(self) -> None:
        self.calls.append(("back",))

    def tap_count(self) -> int:
        return sum(1 for c in self.calls if c[0] == "tap")

    def back_count(self) -> int:
        return sum(1 for c in self.calls if c[0] == "back")

    def taps_at(self, x: int, y: int) -> int:
        return sum(1 for c in self.calls if c[0] == "tap" and c[1] == x and c[2] == y)


class FakeMatcher:
    """
    Matcher con supporto a sequenze per simulare cambio stato UI nel tempo.
    """
    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self._scores: dict[str, float]       = scores or {}
        self._seq:    dict[str, list[float]] = {}

    def set_score(self, tmpl: str, score: float) -> None:
        self._scores[tmpl] = score

    def set_sequence(self, tmpl: str, scores: list[float]) -> None:
        self._seq[tmpl] = list(scores)

    def score(self, shot, tmpl: str, zone=None) -> float:
        if tmpl in self._seq and self._seq[tmpl]:
            return self._seq[tmpl].pop(0)
        return self._scores.get(tmpl, 0.0)

    def exists(self, shot, tmpl: str, threshold: float = 0.75, zone=None) -> bool:
        return self.score(shot, tmpl) >= threshold


# ==============================================================================
# Helpers
# ==============================================================================

class FakeConfig:
    def __init__(self, abilitato: bool = True):
        self._abilitato = abilitato

    def task_abilitato(self, nome: str) -> bool:
        return self._abilitato if nome == "vip" else True


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




def _cfg() -> VipConfig:
    # Riduce i poll per velocizzare i test
    return VipConfig(
        gate_max_poll=2,
        gate_f_max_poll=2,
        wait_open_badge=0,
        wait_claim_cass=0,
        wait_claim_free=0,
        wait_gate_poll=0,
        wait_back=0,
        wait_back_pre=0,
        retry_sleep=0,
    )


def _task(cfg=None) -> VipTask:
    return VipTask(config=cfg or _cfg())


def _matcher_tutto_ok() -> FakeMatcher:
    """
    Matcher che simula: maschera aperta, cass disponibile, cass confermata,
    free disponibile, free confermato.
    """
    cfg = _cfg()
    m   = FakeMatcher()
    # PRE-VIP store → ok
    m.set_score(cfg.tmpl_store,       0.90)
    # CASS: cass_chiusa presente, cass_aperta assente prima, presente dopo claim
    m.set_sequence(cfg.tmpl_cass_chiusa, [0.90])
    m.set_sequence(cfg.tmpl_cass_aperta, [0.10, 0.90])  # check iniziale, POST-C
    # popup_cass ok, GATE-C: store ok al poll 1
    m.set_score(cfg.tmpl_popup_cass,  0.90)
    # FREE: free_chiuso presente, free_aperto assente prima, presente dopo claim
    m.set_sequence(cfg.tmpl_free_chiuso, [0.90])
    m.set_sequence(cfg.tmpl_free_aperto, [0.10, 0.90])  # check iniziale, POST-F
    # popup_free ok
    m.set_score(cfg.tmpl_popup_free,  0.90)
    return m


# ==============================================================================
# Test: should_run()
# ==============================================================================

class TestShouldRun:

    def test_device_none_false(self):
        ctx = _make_ctx(device=None, matcher=FakeMatcher())
        assert VipTask().should_run(ctx) is False

    def test_matcher_none_false(self):
        ctx = _make_ctx(device=FakeDevice(), matcher=None)
        assert VipTask().should_run(ctx) is False

    def test_disabilitato_false(self):
        ctx = _make_ctx(device=FakeDevice(), matcher=FakeMatcher(), abilitato=False)
        assert VipTask().should_run(ctx) is False

    def test_ok_true(self):
        ctx = _make_ctx(device=FakeDevice(), matcher=FakeMatcher(), abilitato=True)
        assert VipTask().should_run(ctx) is True


# ==============================================================================
# Test: _mappa_esito()
# ==============================================================================

class TestMappaEsito:

    def _map(self, esito, cass_ok=True, free_ok=True):
        return VipTask._mappa_esito(esito, cass_ok, free_ok, log=lambda m: None)

    def test_completato_ok(self):
        r = self._map(_Esito.COMPLETATO)
        assert r.success is True
        assert r.skipped is False
        assert r.data["cass_ok"] is True
        assert r.data["free_ok"] is True

    def test_maschera_non_aperta_skip(self):
        r = self._map(_Esito.MASCHERA_NON_APERTA)
        assert r.success is True
        assert r.skipped is True

    def test_errore_fail(self):
        r = self._map(_Esito.ERRORE)
        assert r.success is False


# ==============================================================================
# Test: _check_pin()
# ==============================================================================

class TestCheckPin:

    def _check(self, scores: list[float], soglia=0.80, retry=0) -> bool:
        cfg = _cfg()
        m   = FakeMatcher()
        m.set_sequence(cfg.tmpl_store, scores)
        device = FakeDevice()
        return _task(cfg)._check_pin(
            device, m, cfg.tmpl_store, soglia, cfg.roi_store,
            retry=retry, retry_sleep=0,
            log=lambda x: None, label="TEST"
        )

    def test_trovato_subito(self):
        assert self._check([0.90]) is True

    def test_non_trovato(self):
        assert self._check([0.10]) is False

    def test_trovato_al_retry(self):
        assert self._check([0.10, 0.90], retry=1) is True

    def test_non_trovato_dopo_retry(self):
        assert self._check([0.10, 0.10], retry=1) is False


# ==============================================================================
# Test: _polling_gate()
# ==============================================================================

class TestPollingGate:

    def _gate(self, scores: list[float], max_poll=3) -> bool:
        cfg = _cfg()
        m   = FakeMatcher()
        m.set_sequence(cfg.tmpl_store, scores)
        device = FakeDevice()
        return _task(cfg)._polling_gate(
            device, m, cfg.tmpl_store, cfg.soglia_store, cfg.roi_store,
            max_poll=max_poll, poll_sleep=0,
            log=lambda x: None, label="TEST"
        )

    def test_trovato_al_primo_poll(self):
        assert self._gate([0.90]) is True

    def test_trovato_al_secondo_poll(self):
        assert self._gate([0.10, 0.90]) is True

    def test_non_trovato_esauriti(self):
        assert self._gate([0.10, 0.10, 0.10], max_poll=3) is False


# ==============================================================================
# Test: _gestisci_cassaforte()
# ==============================================================================

class TestGestisciCassaforte:

    def test_gia_ritirata(self):
        """pin_vip_03_cass_aperta presente → True senza tap."""
        cfg = _cfg()
        m   = FakeMatcher()
        m.set_sequence(cfg.tmpl_cass_chiusa, [0.10])
        m.set_sequence(cfg.tmpl_cass_aperta, [0.90])
        device = FakeDevice()
        ok = _task(cfg)._gestisci_cassaforte(device, m, lambda x: None, cfg)
        assert ok is True
        assert device.taps_at(*cfg.tap_claim_cassaforte) == 0

    def test_disponibile_e_confermata(self):
        """pin_vip_02 presente → tap claim → POST-C confermato."""
        cfg = _cfg()
        m   = FakeMatcher()
        m.set_sequence(cfg.tmpl_cass_chiusa, [0.90])
        m.set_sequence(cfg.tmpl_cass_aperta, [0.10,  # check iniziale
                                               0.90]) # POST-C
        m.set_score(cfg.tmpl_popup_cass, 0.90)
        m.set_score(cfg.tmpl_store, 0.90)   # GATE-C
        device = FakeDevice()
        ok = _task(cfg)._gestisci_cassaforte(device, m, lambda x: None, cfg)
        assert ok is True
        assert device.taps_at(*cfg.tap_claim_cassaforte) == 1

    def test_nessun_pin_anomalia(self):
        """Nessun pin rilevato → False."""
        cfg = _cfg()
        m   = FakeMatcher()
        m.set_score(cfg.tmpl_cass_chiusa, 0.10)
        m.set_score(cfg.tmpl_cass_aperta, 0.10)
        device = FakeDevice()
        ok = _task(cfg)._gestisci_cassaforte(device, m, lambda x: None, cfg)
        assert ok is False


# ==============================================================================
# Test: _gestisci_claim_free()
# ==============================================================================

class TestGestisciClaimFree:

    def test_gia_ritirato(self):
        cfg = _cfg()
        m   = FakeMatcher()
        m.set_sequence(cfg.tmpl_free_chiuso, [0.10])
        m.set_sequence(cfg.tmpl_free_aperto, [0.90])
        device = FakeDevice()
        ok = _task(cfg)._gestisci_claim_free(device, m, lambda x: None, cfg)
        assert ok is True
        assert device.taps_at(*cfg.tap_claim_free) == 0

    def test_disponibile_e_confermato(self):
        cfg = _cfg()
        m   = FakeMatcher()
        m.set_sequence(cfg.tmpl_free_chiuso, [0.90])
        m.set_sequence(cfg.tmpl_free_aperto, [0.10, 0.90])
        m.set_score(cfg.tmpl_popup_free, 0.90)
        m.set_score(cfg.tmpl_store, 0.90)   # GATE-F
        device = FakeDevice()
        ok = _task(cfg)._gestisci_claim_free(device, m, lambda x: None, cfg)
        assert ok is True
        assert device.taps_at(*cfg.tap_claim_free) == 1

    def test_tap_chiudi_reward_eseguito(self):
        """TAP_VIP_CHIUDI_REWARD_FREE deve essere sempre tappato dopo claim free."""
        cfg = _cfg()
        m   = FakeMatcher()
        m.set_sequence(cfg.tmpl_free_chiuso, [0.90])
        m.set_sequence(cfg.tmpl_free_aperto, [0.10, 0.90])
        m.set_score(cfg.tmpl_popup_free, 0.90)
        m.set_score(cfg.tmpl_store, 0.90)
        device = FakeDevice()
        _task(cfg)._gestisci_claim_free(device, m, lambda x: None, cfg)
        assert device.taps_at(*cfg.tap_chiudi_reward_free) >= 1

    def test_nessun_pin_anomalia(self):
        cfg = _cfg()
        m   = FakeMatcher()
        m.set_score(cfg.tmpl_free_chiuso, 0.10)
        m.set_score(cfg.tmpl_free_aperto, 0.10)
        device = FakeDevice()
        ok = _task(cfg)._gestisci_claim_free(device, m, lambda x: None, cfg)
        assert ok is False


# ==============================================================================
# Test: run() — flusso completo
# ==============================================================================

class TestRunCompleto:

    def test_completato_primo_tentativo(self):
        device  = FakeDevice()
        matcher = _matcher_tutto_ok()
        ctx     = _make_ctx(device=device, matcher=matcher)
        result = _task().run(ctx)
        assert result.success is True
        assert result.skipped is False
        assert result.data["cass_ok"] is True
        assert result.data["free_ok"] is True

    def test_back_tre_dopo_tentativo(self):
        """BACK×3 sempre eseguiti dopo ogni tentativo completato."""
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = _matcher_tutto_ok()
        ctx     = _make_ctx(device=device, matcher=matcher)
        _task(cfg).run(ctx)
        assert device.back_count() == cfg.n_back_chiudi

    def test_tap_badge_eseguito(self):
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = _matcher_tutto_ok()
        ctx     = _make_ctx(device=device, matcher=matcher)
        _task(cfg).run(ctx)
        assert device.taps_at(*cfg.tap_badge) == 1


# ==============================================================================
# Test: run() — maschera non aperta → skip
# ==============================================================================

class TestMascheraNonAperta:

    def test_ritorna_skip_dopo_max_tentativi(self):
        cfg     = VipConfig(max_tentativi=2, wait_open_badge=0,
                            wait_back_pre=0, wait_back=0, retry_sleep=0)
        device  = FakeDevice()
        # store mai visibile → maschera mai aperta
        matcher = FakeMatcher({cfg.tmpl_store: 0.10})
        ctx     = _make_ctx(device=device, matcher=matcher)
        result = VipTask(config=cfg).run(ctx)
        assert result.success is True
        assert result.skipped is True

    def test_tap_badge_ripetuto_per_ogni_tentativo(self):
        cfg     = VipConfig(max_tentativi=2, wait_open_badge=0,
                            wait_back_pre=0, wait_back=0, retry_sleep=0)
        device  = FakeDevice()
        matcher = FakeMatcher({cfg.tmpl_store: 0.10})
        ctx     = _make_ctx(device=device, matcher=matcher)
        VipTask(config=cfg).run(ctx)
        assert device.taps_at(*cfg.tap_badge) == 2


# ==============================================================================
# Test: VipConfig defaults
# ==============================================================================

class TestVipConfig:

    def test_name(self):
        assert VipTask().name() == "vip"

    def test_soglie_in_range(self):
        cfg = VipConfig()
        for attr in ("soglia_store", "soglia_cass_chiusa", "soglia_cass_aperta",
                     "soglia_free_chiuso", "soglia_free_aperto",
                     "soglia_popup_cass", "soglia_popup_free"):
            val = getattr(cfg, attr)
            assert 0 < val < 1, f"{attr} fuori range: {val}"

    def test_tmpl_paths_pin(self):
        cfg = VipConfig()
        for attr in ("tmpl_store", "tmpl_cass_chiusa", "tmpl_cass_aperta",
                     "tmpl_free_chiuso", "tmpl_free_aperto",
                     "tmpl_popup_cass", "tmpl_popup_free"):
            assert getattr(cfg, attr).startswith("pin/"), f"{attr} non inizia con pin/"

    def test_coordinate_plausibili(self):
        cfg = VipConfig()
        for attr in ("tap_badge", "tap_claim_cassaforte", "tap_claim_free",
                     "tap_dismiss_cass", "tap_dismiss_free", "tap_chiudi_reward_free"):
            x, y = getattr(cfg, attr)
            assert 0 <= x <= 960, f"{attr}.x fuori range: {x}"
            assert 0 <= y <= 540, f"{attr}.y fuori range: {y}"
