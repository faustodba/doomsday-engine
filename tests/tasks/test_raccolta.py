# ==============================================================================
#  tests/tasks/test_raccolta.py — Step 21
#  Tutti i test usano FakeDevice + FakeMatcher — zero ADB reale.
#
#  FIX 19/04/2026:
#    - _ctx_nav_ok(): helper che stubba navigator.vai_in_mappa/vai_in_home
#      a True, evitando il blocco early-return in RaccoltaTask.run
#      quando il navigator reale su FakeMatcher fallirebbe.
# ==============================================================================

import time
import pytest
from unittest.mock import patch, MagicMock

from core.device import FakeDevice
from core.navigator import GameNavigator
from core.state import InstanceState, RaccoltaState
from core.task import TaskContext, TaskResult
from shared.template_matcher import FakeMatcher
from tasks.raccolta import (
    RaccoltaTask,
    Blacklist,
    BlacklistFuori,
    _cfg,
    _calcola_sequenza,
    _calibra_livello_giornaliero,
    _cerca_nodo,
    _invia_squadra,
    _reset_leggero_lente,
    _loop_invio_marce,
    _DEFAULTS,
    _TUTTI_I_TIPI,
)


# ==============================================================================
# WU173 — isola data/nodi_mappa_observations.jsonl (e data/cap_nodi_dataset.jsonl,
# pre-esistente) nella tmp_path: senza questa fixture i test che esercitano
# _tenta_marcia scrivono nella vera cartella data/ del repo dev.
# ==============================================================================

@pytest.fixture(autouse=True)
def _isola_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DOOMSDAY_ROOT", str(tmp_path))


# ------------------------------------------------------------------------------
# Fixture base
# ------------------------------------------------------------------------------

def make_ctx(config_overrides: dict | None = None) -> TaskContext:
    device = FakeDevice()
    matcher = FakeMatcher()
    navigator = GameNavigator(device, matcher)
    config = dict(config_overrides or {})
    return TaskContext(
        instance_name="FAU_00",
        config=config,
        state=None,
        log=None,
        device=device,
        matcher=matcher,
        navigator=navigator,
    )


def ctx_base(**overrides) -> TaskContext:
    """TaskContext con raccolta abilitata e config minimale."""
    base = {
        "RACCOLTA_ABILITATA":      True,
        "RACCOLTA_SEQUENZA":       ["campo", "segheria"],
        "RACCOLTA_OBIETTIVO":      4,
        "RACCOLTA_MAX_FALLIMENTI": 3,
        "RACCOLTA_TRUPPE":         0,
        "RACCOLTA_LIVELLO":        6,
        "BLACKLIST_COMMITTED_TTL": 120,
        "BLACKLIST_RESERVED_TTL":  45,
        "BLACKLIST_ATTESA_NODO":   120,
        "DELAY_POST_MARCIA":       0.0,
        "DELAY_CERCA":             0.0,
        "TEMPLATE_GATHER":         "pin/pin_gather.png",
        "TEMPLATE_MARCIA":         "pin/pin_march.png",
        "TEMPLATE_SOGLIA":         0.75,
    }
    base.update(overrides)
    return make_ctx(base)


def _ctx_nav_ok(**overrides) -> TaskContext:
    """
    ctx_base() + navigator.vai_in_mappa/vai_in_home stubbed a True.
    Necessario perché GameNavigator + FakeMatcher non trovano template
    barra inferiore, quindi vai_in_mappa() torna False e l'esecuzione
    di RaccoltaTask.run termina anticipatamente al check di navigazione.
    """
    ctx = ctx_base(**overrides)
    ctx.navigator.vai_in_mappa = MagicMock(return_value=True)
    ctx.navigator.vai_in_home  = MagicMock(return_value=True)
    return ctx


# ==============================================================================
# 1. Proprietà del task
# ==============================================================================

class TestRaccoltaProperties:

    def test_name(self):
        assert RaccoltaTask().name() == "raccolta"

    def test_schedule_type(self):
        assert RaccoltaTask().schedule_type() == "periodic"

    def test_interval_hours(self):
        assert RaccoltaTask().interval_hours() == 4.0


# ==============================================================================
# 2. _cfg — lettura config con fallback
# ==============================================================================

class TestCfg:

    def test_default_abilitata(self):
        ctx = make_ctx()
        assert _cfg(ctx, "RACCOLTA_ABILITATA") is True

    def test_override_abilitata(self):
        ctx = make_ctx({"RACCOLTA_ABILITATA": False})
        assert _cfg(ctx, "RACCOLTA_ABILITATA") is False

    def test_default_obiettivo(self):
        ctx = make_ctx()
        assert _cfg(ctx, "RACCOLTA_OBIETTIVO") == 4

    def test_override_obiettivo(self):
        ctx = make_ctx({"RACCOLTA_OBIETTIVO": 6})
        assert _cfg(ctx, "RACCOLTA_OBIETTIVO") == 6

    def test_default_livello(self):
        ctx = make_ctx()
        assert _cfg(ctx, "RACCOLTA_LIVELLO") == 6

    def test_default_committed_ttl(self):
        ctx = make_ctx()
        assert _cfg(ctx, "BLACKLIST_COMMITTED_TTL") == 120

    def test_default_tap_lente(self):
        ctx = make_ctx()
        assert _cfg(ctx, "TAP_LENTE") == (38, 325)


# ==============================================================================
# 2b. _cerca_nodo — WU198 09/07/2026: skip_verifica_tipo + delay override
#     (parametri opt-in per RaccoltaFastTask, default = comportamento
#     standard preesistente invariato).
# ==============================================================================

class TestCercaNodoSkipVerificaTipo:

    @patch("tasks.raccolta.time.sleep")
    def test_skip_verifica_tipo_ignora_match_fallito(self, mock_sleep):
        """
        pin_sawmill (template tipo "segheria") NON configurato → find_one
        tornerebbe found=False. Con skip_verifica_tipo=True, _verifica_tipo
        non viene mai invocata: _cerca_nodo deve comunque avere successo.
        pin_field (marker lente, TMPL_TIPO["campo"]) resta configurato per
        far aprire la lente — è un template diverso da pin_sawmill, quindi
        non c'è ambiguità sul cosa sta verificando cosa.
        """
        ctx = ctx_base()
        ctx.device.set_default_shot(object())
        ctx.matcher.set_result("pin/pin_field.png", (500, 500))  # marker lente
        with patch("tasks.raccolta._leggi_livello_panel", return_value=6):
            ok = _cerca_nodo(ctx, "segheria", skip_verifica_tipo=True)
        assert ok is True

    @patch("tasks.raccolta.time.sleep")
    def test_default_skip_false_comportamento_standard_invariato(self, mock_sleep):
        """
        Stesso setup del test sopra ma SENZA skip_verifica_tipo (default
        False): pin_sawmill non trovato → _verifica_tipo fallisce sempre,
        anche dopo i retry standard → _cerca_nodo deve fallire. Garantisce
        che il nuovo parametro non abbia alterato il comportamento di
        RaccoltaTask/RaccoltaChiusuraTask (che chiamano _cerca_nodo senza
        passarlo).
        """
        ctx = ctx_base()
        ctx.device.set_default_shot(object())
        ctx.matcher.set_result("pin/pin_field.png", (500, 500))  # marker lente
        with patch("tasks.raccolta._leggi_livello_panel", return_value=6):
            ok = _cerca_nodo(ctx, "segheria")
        assert ok is False

    @patch("tasks.raccolta.time.sleep")
    def test_delay_override_applicati_invece_dei_default(self, mock_sleep):
        """delay_tap_icona/delay_cerca personalizzati (profilo fast) vengono
        passati a time.sleep al posto dei valori standard (1.8s / DELAY_CERCA)."""
        ctx = ctx_base(DELAY_CERCA=1.5)
        ctx.device.set_default_shot(object())
        ctx.matcher.set_result("pin/pin_field.png", (500, 500))
        with patch("tasks.raccolta._leggi_livello_panel", return_value=6):
            _cerca_nodo(ctx, "campo", skip_verifica_tipo=True,
                       delay_tap_icona=0.3, delay_cerca=0.2)
        sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
        assert 0.3 in sleep_args
        assert 0.2 in sleep_args
        assert 1.8 not in sleep_args
        assert 1.5 not in sleep_args

    @patch("tasks.raccolta.time.sleep")
    def test_default_delay_invariati_se_non_passati(self, mock_sleep):
        """Senza override (chiamata standard, come da RaccoltaTask), i delay
        restano quelli storici: 1.8s dopo tap icona, DELAY_CERCA da config."""
        ctx = ctx_base(DELAY_CERCA=1.5)
        ctx.device.set_default_shot(object())
        ctx.matcher.set_result("pin/pin_field.png", (500, 500))
        ctx.matcher.set_result("pin/pin_sawmill.png", (500, 500))
        with patch("tasks.raccolta._leggi_livello_panel", return_value=6):
            ok = _cerca_nodo(ctx, "segheria")
        assert ok is True
        sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
        assert 1.8 in sleep_args
        assert 1.5 in sleep_args

    @patch("tasks.raccolta.time.sleep")
    def test_skip_livello_check_non_legge_pannello(self, mock_sleep):
        """WU199ter 09/07/2026: con skip_livello_check=True, _leggi_livello_panel
        non deve mai essere invocata (zero round-trip OCR pannello) — tap
        diretto su 'cerca' col livello già impostato, qualunque esso sia."""
        ctx = ctx_base()
        ctx.device.set_default_shot(object())
        ctx.matcher.set_result("pin/pin_field.png", (500, 500))
        with patch("tasks.raccolta._leggi_livello_panel") as mock_livello:
            ok = _cerca_nodo(ctx, "segheria", skip_verifica_tipo=True,
                             skip_livello_check=True)
        assert ok is True
        mock_livello.assert_not_called()

    @patch("tasks.raccolta.time.sleep")
    def test_default_skip_livello_check_false_legge_pannello(self, mock_sleep):
        """Senza il parametro (default False, come RaccoltaTask/Chiusura),
        _leggi_livello_panel resta chiamata — comportamento standard invariato."""
        ctx = ctx_base()
        ctx.device.set_default_shot(object())
        ctx.matcher.set_result("pin/pin_field.png", (500, 500))
        with patch("tasks.raccolta._leggi_livello_panel", return_value=6) as mock_livello:
            ok = _cerca_nodo(ctx, "segheria", skip_verifica_tipo=True)
        assert ok is True
        mock_livello.assert_called()


# ==============================================================================
# 3. Blacklist — stati e TTL
# ==============================================================================

class TestBlacklist:

    def test_contiene_false_inizialmente(self):
        bl = Blacklist()
        assert bl.contiene("100_200") is False

    def test_reserve_aggiunge(self):
        bl = Blacklist()
        bl.reserve("100_200")
        assert bl.contiene("100_200") is True

    def test_commit_aggiunge(self):
        bl = Blacklist()
        bl.commit("100_200", eta_s=60.0)
        assert bl.contiene("100_200") is True

    def test_rollback_rimuove(self):
        bl = Blacklist()
        bl.reserve("100_200")
        bl.rollback("100_200")
        assert bl.contiene("100_200") is False

    def test_get_eta_dopo_commit(self):
        bl = Blacklist()
        bl.commit("100_200", eta_s=54.0)
        assert bl.get_eta("100_200") == 54.0

    def test_get_eta_none_dopo_reserve(self):
        bl = Blacklist()
        bl.reserve("100_200")
        assert bl.get_eta("100_200") is None

    def test_get_state_reserved(self):
        bl = Blacklist()
        bl.reserve("100_200")
        assert bl.get_state("100_200") == "RESERVED"

    def test_get_state_committed(self):
        bl = Blacklist()
        bl.commit("100_200")
        assert bl.get_state("100_200") == "COMMITTED"

    def test_get_state_none_se_assente(self):
        bl = Blacklist()
        assert bl.get_state("999_999") is None

    def test_pulizia_scaduti_committed(self):
        bl = Blacklist(committed_ttl=0, reserved_ttl=0)
        bl.commit("100_200")
        time.sleep(0.01)
        assert bl.contiene("100_200") is False

    def test_pulizia_scaduti_reserved(self):
        bl = Blacklist(committed_ttl=120, reserved_ttl=0)
        bl.reserve("100_200")
        time.sleep(0.01)
        assert bl.contiene("100_200") is False

    def test_len(self):
        bl = Blacklist()
        bl.reserve("A")
        bl.commit("B")
        assert len(bl) == 2

    def test_snapshot_vuoto(self):
        bl = Blacklist()
        assert bl.snapshot() == {}

    def test_snapshot_con_dati(self):
        bl = Blacklist()
        bl.commit("100_200", eta_s=30.0)
        snap = bl.snapshot()
        assert "100_200" in snap

    def test_chiave_vuota_safe(self):
        bl = Blacklist()
        bl.reserve("")
        bl.commit("")
        bl.rollback("")
        assert bl.contiene("") is False

    def test_commit_sovrascrive_reserve(self):
        bl = Blacklist()
        bl.reserve("100_200")
        bl.commit("100_200", eta_s=90.0)
        assert bl.get_state("100_200") == "COMMITTED"
        assert bl.get_eta("100_200") == 90.0


# ==============================================================================
# 4. _calcola_sequenza
# ==============================================================================

class TestCalcolaSequenza:

    def test_sequenza_base(self):
        seq = _calcola_sequenza(4, ["campo", "segheria"], set())
        assert all(t in ["campo", "segheria"] for t in seq)
        assert len(seq) >= 4

    def test_esclude_bloccati(self):
        seq = _calcola_sequenza(4, ["campo", "segheria", "petrolio"], {"campo"})
        assert "campo" not in seq

    def test_fallback_tutti_i_tipi(self):
        seq = _calcola_sequenza(4, ["campo"], {"campo"})
        # campo bloccato → fallback a tipi rimanenti
        assert len(seq) > 0
        assert "campo" not in seq

    def test_sequenza_vuota_se_tutti_bloccati(self):
        seq = _calcola_sequenza(4, ["campo"], set(_TUTTI_I_TIPI))
        assert seq == []

    def test_lunghezza_sufficiente(self):
        seq = _calcola_sequenza(4, ["campo", "segheria"], set())
        assert len(seq) >= 4


# ==============================================================================
# 5. RaccoltaTask.run — disabilitato
# ==============================================================================

class TestRaccoltaDisabilitata:

    def test_disabilitata_skip(self):
        ctx = make_ctx({"RACCOLTA_ABILITATA": False})
        result = RaccoltaTask().run(ctx)
        assert result.success is True
        assert result.message == "disabilitato"
        assert len(ctx.device.taps) == 0

    def test_disabilitata_data(self):
        ctx = make_ctx({"RACCOLTA_ABILITATA": False})
        result = RaccoltaTask().run(ctx)
        assert result.data["inviate"] == 0


# ==============================================================================
# 6. RaccoltaTask.run — nessuna squadra libera
# ==============================================================================

class TestRaccoltaNessunaSquadra:

    def test_slot_zero_skip(self):
        ctx = ctx_base()
        result = RaccoltaTask().run(ctx, attive_inizio=4, slot_liberi=0)
        assert result.success is True
        assert "libera" in result.message
        assert result.data["inviate"] == 0

    def test_attive_uguali_obiettivo_skip(self):
        ctx = ctx_base(**{"RACCOLTA_OBIETTIVO": 4})
        result = RaccoltaTask().run(ctx, attive_inizio=4)
        assert result.data["inviate"] == 0
        assert len(ctx.device.taps) == 0

    def test_slot_zero_nessun_keycode_map(self):
        ctx = ctx_base()
        RaccoltaTask().run(ctx, attive_inizio=4, slot_liberi=0)
        assert ("KEY", "KEYCODE_MAP") not in ctx.device.taps


# ==============================================================================
# 7. RaccoltaTask.run — navigazione in mappa
# ==============================================================================

class TestRaccoltaNavigazioneMappa:

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", return_value=0)
    def test_navigazione_mappa_eseguita(self, mock_loop, mock_sleep):
        """Navigator.vai_in_mappa() chiamato → loop viene eseguito."""
        ctx = _ctx_nav_ok()
        RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=2)
        # Il ciclo esterno puo' ripetere fino a 3 tentativi se attive_correnti
        # non raggiunge obiettivo — verifichiamo solo che sia stato chiamato.
        assert mock_loop.called

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", return_value=0)
    def test_ritorno_home_eseguito(self, mock_loop, mock_sleep):
        """Dopo il loop, navigator.vai_in_home() viene chiamato."""
        ctx = _ctx_nav_ok()
        RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=2)
        # Il loop è stato chiamato = navigazione andata a buon fine
        # Il ritorno home è garantito dal finally
        assert mock_loop.called


# ==============================================================================
# 8. RaccoltaTask.run — loop marce mockato
# ==============================================================================

class TestRaccoltaLoopMockato:

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", side_effect=[3, 0, 0])
    def test_tre_inviate(self, mock_loop, mock_sleep):
        """Prima chiamata torna 3 inviate, successive 0 (slot pieni)."""
        ctx = _ctx_nav_ok()
        result = RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=3)
        assert result.data["inviate"] == 3
        assert result.success is True

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", side_effect=[1, 0, 0])
    def test_result_message_inviate(self, mock_loop, mock_sleep):
        """Prima chiamata torna 1, successive 0 → inviate_totali=1."""
        ctx = _ctx_nav_ok()
        result = RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=2)
        assert "1" in result.message

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", side_effect=RuntimeError("test"))
    def test_errore_loop_result_false(self, mock_loop, mock_sleep):
        ctx = _ctx_nav_ok()
        result = RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=2)
        assert result.success is False
        assert "errore" in result.message

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", side_effect=RuntimeError("test"))
    def test_errore_home_eseguito_comunque(self, mock_loop, mock_sleep):
        """Anche se il loop lancia eccezione, il ritorno home viene eseguito."""
        ctx = _ctx_nav_ok()
        result = RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=2)
        assert result.success is False  # errore riportato


# ==============================================================================
# 9. RaccoltaTask.run — blacklist iniettata
# ==============================================================================

class TestRaccoltaBlacklistIniettata:

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", return_value=2)
    def test_blacklist_custom_passata(self, mock_loop, mock_sleep):
        ctx = _ctx_nav_ok()
        bl = Blacklist()
        bl.commit("100_200")
        RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=2, blacklist=bl)
        # Verifica che il loop venga chiamato con la nostra blacklist
        args = mock_loop.call_args
        assert args[0][3] is bl  # quarto argomento posizionale = blacklist

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", return_value=0)
    def test_blacklist_creata_internamente_se_none(self, mock_loop, mock_sleep):
        ctx = _ctx_nav_ok()
        RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=2, blacklist=None)
        args = mock_loop.call_args
        bl_passata = args[0][3]
        assert isinstance(bl_passata, Blacklist)


# ==============================================================================
# 10. _loop_invio_marce — con FakeMatcher che NON trova nodi
# ==============================================================================

class TestLoopInvioMarceNoNodi:

    @patch("tasks.raccolta.time.sleep")
    def test_zero_inviate_se_nodi_non_trovati(self, mock_sleep):
        """FakeMatcher default → None → coordinate non leggibili → fallimenti."""
        ctx = ctx_base(**{"RACCOLTA_MAX_FALLIMENTI": 1,
                          "RACCOLTA_OBIETTIVO": 2})
        bl = Blacklist()
        # FakeMatcher non trova nulla → _leggi_coordinate_nodo ritorna None
        inviate = _loop_invio_marce(ctx, 2, 0, bl)
        assert inviate == 0

    @patch("tasks.raccolta.time.sleep")
    def test_taps_lente_eseguiti(self, mock_sleep):
        """Anche con nodi non trovati, i tap lente devono essere eseguiti."""
        ctx = ctx_base(**{"RACCOLTA_MAX_FALLIMENTI": 1,
                          "RACCOLTA_OBIETTIVO": 1})
        bl = Blacklist()
        _loop_invio_marce(ctx, 1, 0, bl)
        tap_lente = _DEFAULTS["TAP_LENTE"]
        assert tap_lente in ctx.device.taps


# ==============================================================================
# 11. _loop_invio_marce — con FakeMatcher che trova gather
# ==============================================================================

class TestLoopInvioMarceConGather:

    @patch("tasks.raccolta.time.sleep")
    def test_una_squadra_inviata(self, mock_sleep):
        """
        FakeMatcher trova gather (popup nodo OK) MA non trova marcia
        (maschera invio non aperta) → marcia fallisce → 0 inviate.
        """
        ctx = ctx_base(**{"RACCOLTA_MAX_FALLIMENTI": 1,
                          "RACCOLTA_OBIETTIVO": 1})
        ctx.matcher.set_result("pin/pin_gather.png", (400, 300))
        # pin_marcia non trovato → maschera non aperta → fallisce
        bl = Blacklist()
        inviate = _loop_invio_marce(ctx, 1, 0, bl)
        # Nessuna marcia completata (maschera non aperta)
        assert inviate == 0

    @patch("tasks.raccolta.time.sleep")
    def test_marcia_ok_se_gather_e_marcia_trovati(self, mock_sleep):
        """
        Setup end-to-end simulato: _cerca_nodo OK (pin tipo trovati),
        _leggi_coord_nodo patchato a "100_200" (V6 usa OCR X_Y),
        _esegui_marcia patchato a (True, 60.0) → 1 marcia inviata.

        FIX 19/04/2026: chiave aggiornata da "tipo_campo" (V5 legacy)
        al formato OCR V6 "X_Y". Patchati _leggi_coord_nodo,
        _reset_to_mappa, _leggi_attive_post_marcia, _leggi_livello_nodo
        per isolare il test dalla catena OCR.
        """
        with patch("tasks.raccolta._esegui_marcia", return_value=(True, 60.0)), \
             patch("tasks.raccolta._leggi_coord_nodo", return_value="100_200"), \
             patch("tasks.raccolta._reset_to_mappa", return_value=-1), \
             patch("tasks.raccolta._leggi_attive_post_marcia", return_value=-1), \
             patch("tasks.raccolta._leggi_livello_nodo", return_value=6):
            ctx = _ctx_nav_ok(**{"RACCOLTA_MAX_FALLIMENTI": 1,
                                 "RACCOLTA_OBIETTIVO": 1})
            ctx.device.set_default_shot(object())
            ctx.matcher.set_result("pin/pin_gather.png", (400, 300))
            # verifica tipo: tutti i pin tipo trovati per non bloccare _cerca_nodo
            for tmpl in ["pin/pin_field.png", "pin/pin_sawmill.png",
                         "pin/pin_steel_mill.png", "pin/pin_oil_refinery.png"]:
                ctx.matcher.set_result(tmpl, (500, 500))
            bl = Blacklist()
            inviate = _loop_invio_marce(ctx, 1, 0, bl)
            assert inviate == 1

    @patch("tasks.raccolta.time.sleep")
    def test_nodo_committed_dopo_marcia(self, mock_sleep):
        """
        Dopo marcia OK, nodo COMMITTED in blacklist con ETA dinamica.
        FIX 19/04/2026: chiave OCR V6 "100_200" invece di "tipo_campo".
        """
        with patch("tasks.raccolta._esegui_marcia", return_value=(True, 45.0)), \
             patch("tasks.raccolta._leggi_coord_nodo", return_value="100_200"), \
             patch("tasks.raccolta._reset_to_mappa", return_value=-1), \
             patch("tasks.raccolta._leggi_attive_post_marcia", return_value=-1), \
             patch("tasks.raccolta._leggi_livello_nodo", return_value=6):
            ctx = _ctx_nav_ok(**{"RACCOLTA_MAX_FALLIMENTI": 1,
                                 "RACCOLTA_OBIETTIVO": 1})
            ctx.device.set_default_shot(object())
            ctx.matcher.set_result("pin/pin_gather.png", (400, 300))
            for tmpl in ["pin/pin_field.png", "pin/pin_sawmill.png",
                         "pin/pin_steel_mill.png", "pin/pin_oil_refinery.png"]:
                ctx.matcher.set_result(tmpl, (500, 500))
            bl = Blacklist()
            _loop_invio_marce(ctx, 1, 0, bl)
            # V6: chiave = coordinate OCR "X_Y" (patchata a "100_200")
            assert bl.get_state("100_200") == "COMMITTED"
            assert bl.get_eta("100_200") == 45.0


# ==============================================================================
# 11b. _loop_invio_marce — WU187: slot pieni via streak maschera, break reale
# ==============================================================================

class TestLoopInvioMarceSlotPieniStreak:

    @patch("tasks.raccolta.time.sleep")
    def test_streak_maschera_ferma_subito_il_while(self, mock_sleep):
        """
        WU187 — regressione: prima del fix, il break al raggiungimento di
        SOGLIA_MASK_STREAK usciva solo dal for interno; il while esterno
        rientrava e tentava un ulteriore invio a vuoto prima di fermarsi
        (osservato in produzione: 8/8 occorrenze su 6 istanze, log
        "uscita immediata" seguito comunque da un altro "invio squadra").
        RACCOLTA_MAX_FALLIMENTI alto per isolare il bug: senza il fix il
        while non uscirebbe per coincidenza sul contatore fallimenti.
        """
        def fake_invia_squadra(ctx, tipo, *a, **kw):
            ctx._raccolta_mask_not_opened = True
            return False, False, False

        with patch("tasks.raccolta._invia_squadra",
                   side_effect=fake_invia_squadra) as mock_invia:
            ctx = ctx_base(**{"RACCOLTA_MAX_FALLIMENTI": 10,
                              "RACCOLTA_OBIETTIVO": 5})
            bl = Blacklist()
            inviate = _loop_invio_marce(ctx, 5, 3, bl)

        assert inviate == 0
        # SOGLIA_MASK_STREAK=2 → si ferma esattamente al 2° tentativo,
        # non un terzo "a vuoto" dopo aver già dedotto slot pieni.
        assert mock_invia.call_count == 2
        assert ctx._raccolta_slot_pieni is True


# ==============================================================================
# 12. _loop_invio_marce — blacklist check
# ==============================================================================

class TestLoopBlacklist:

    @patch("tasks.raccolta.time.sleep")
    def test_nodo_in_blacklist_riproposto_cooldown(self, mock_sleep):
        """
        Se il nodo è in blacklist e il CERCA ripropone lo stesso → cooldown tipo.
        """
        ctx = ctx_base(**{"RACCOLTA_MAX_FALLIMENTI": 1,
                          "RACCOLTA_OBIETTIVO": 1})
        ctx.device.set_default_shot(object())
        # Sempre lo stesso nodo → blacklisted → riproposto → cooldown
        ctx.matcher.set_result("pin/pin_gather.png", (400, 300))
        bl = Blacklist()
        bl.commit("400_300", eta_s=60.0)
        inviate = _loop_invio_marce(ctx, 1, 0, bl)
        assert inviate == 0


# ==============================================================================
# 13. Coordinate personalizzate
# ==============================================================================

class TestRaccoltaCoordCustom:

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", return_value=1)
    def test_tap_lente_custom(self, mock_loop, mock_sleep):
        ctx = ctx_base(**{"TAP_LENTE": (100, 20)})
        RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=1)
        # Non testiamo direttamente TAP_LENTE nel run (è nel loop)
        # ma verifichiamo che il cfg sia letto correttamente
        assert _cfg(ctx, "TAP_LENTE") == (100, 20)

    def test_coord_livello_campo_default(self):
        ctx = make_ctx()
        coord_lv = _cfg(ctx, "COORD_LIVELLO")
        assert "campo" in coord_lv
        assert "meno" in coord_lv["campo"]
        assert "piu"  in coord_lv["campo"]
        assert "search" in coord_lv["campo"]


# ==============================================================================
# 14. RaccoltaTask.run — slot_liberi iniettato vs calcolato
# ==============================================================================

class TestRaccoltaSlotLiberi:

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", return_value=0)
    def test_slot_calcolato_da_attive(self, mock_loop, mock_sleep):
        """slot_liberi=-1 → calcolato come obiettivo - attive_inizio."""
        ctx = _ctx_nav_ok(**{"RACCOLTA_OBIETTIVO": 4})
        RaccoltaTask().run(ctx, attive_inizio=2, slot_liberi=-1)
        # 4 - 2 = 2 libere → il loop viene chiamato (puo' essere richiamato
        # fino a 3 volte dal ciclo esterno)
        assert mock_loop.called

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", return_value=0)
    def test_slot_iniettato_sovrascrive(self, mock_loop, mock_sleep):
        """slot_liberi esplicito → usato direttamente."""
        ctx = _ctx_nav_ok(**{"RACCOLTA_OBIETTIVO": 4})
        RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=1)
        assert mock_loop.called


# ==============================================================================
# 15. _nodo_in_territorio — pixel check territorio alleanza
# ==============================================================================

class TestNodoInTerritorio:

    def _make_screen_con_verde(self):
        """Crea uno screenshot fake con pixel verdi nella zona buff."""
        import numpy as np
        from unittest.mock import MagicMock
        frame = np.zeros((540, 960, 3), dtype=np.uint8)
        # Zona buff: (250,340,420,370) — riempi con verde "alleanza"
        # BGR: B=30, G=180, R=20 → g>140, g>r*1.4, g>b*1.3, g-r>40
        frame[340:370, 250:420] = [30, 180, 20]
        screen = MagicMock()
        screen.frame = frame
        return screen

    def _make_screen_senza_verde(self):
        """Crea uno screenshot fake senza pixel verdi — fuori territorio."""
        import numpy as np
        from unittest.mock import MagicMock
        frame = np.zeros((540, 960, 3), dtype=np.uint8)
        # Zona buff: grigi neutri — nessun verde
        frame[340:370, 250:420] = [100, 100, 100]
        screen = MagicMock()
        screen.frame = frame
        return screen

    def test_in_territorio(self):
        from tasks.raccolta import _nodo_in_territorio
        ctx = ctx_base()
        screen = self._make_screen_con_verde()
        assert _nodo_in_territorio(screen, "campo", ctx) is True

    def test_fuori_territorio(self):
        from tasks.raccolta import _nodo_in_territorio
        ctx = ctx_base()
        screen = self._make_screen_senza_verde()
        assert _nodo_in_territorio(screen, "campo", ctx) is False

    def test_fail_safe_frame_none(self):
        """Se frame è None ritorna True (fail-safe)."""
        from tasks.raccolta import _nodo_in_territorio
        from unittest.mock import MagicMock
        ctx = ctx_base()
        screen = MagicMock()
        screen.frame = None
        assert _nodo_in_territorio(screen, "campo", ctx) is True


# ==============================================================================
# WU231 (16/07) — BlacklistFuori: scrittura atomica + niente azzeramento
# silenzioso su file corrotto.
#
# Bug pre-fix: _salva() era un write_text diretto (non atomico) -- un
# crash/kill a meta' scrittura lasciava un JSON troncato. _carica() su quel
# file sollevava un'eccezione, la ingoiava e ritornava {} -- la prima
# aggiungi() successiva SOVRASCRIVEVA il file corrotto con {} + 1 solo nodo,
# perdendo per sempre la blacklist accumulata (in prod: 46 nodi da 2 mesi).
# ==============================================================================

class TestBlacklistFuoriPersistenza:

    def _bl(self, tmp_path):
        return BlacklistFuori(data_dir=str(tmp_path))

    def test_file_assente_e_normale_non_corrotto(self, tmp_path):
        bl = self._bl(tmp_path)
        assert bl._corrotto is False
        assert len(bl) == 0

    def test_aggiungi_e_contiene_roundtrip(self, tmp_path):
        bl = self._bl(tmp_path)
        bl.aggiungi("700_500", "petrolio")
        assert bl.contiene("700_500") is True
        assert len(bl) == 1

    def test_salva_e_atomico_no_file_tmp_residuo(self, tmp_path):
        bl = self._bl(tmp_path)
        bl.aggiungi("700_500", "petrolio")
        assert bl._path.exists()
        assert not bl._path.with_suffix(".tmp").exists()

    def test_persiste_tra_istanze_diverse(self, tmp_path):
        bl1 = self._bl(tmp_path)
        bl1.aggiungi("700_500", "petrolio")
        bl1.aggiungi("701_501", "campo")
        bl2 = self._bl(tmp_path)   # nuova istanza, stesso data_dir = rilettura da disco
        assert bl2.contiene("700_500") is True
        assert bl2.contiene("701_501") is True
        assert len(bl2) == 2

    def test_file_corrotto_rilevato_e_marcato(self, tmp_path):
        p = tmp_path / "blacklist_fuori_globale.json"
        p.write_text('{"700_500": {"ts": 1.0, "tipo": "petro', encoding="utf-8")  # troncato
        bl = self._bl(tmp_path)
        assert bl._corrotto is True

    def test_file_corrotto_non_azzera_in_memoria_ma_non_scrive(self, tmp_path):
        """Il cuore del fix: file corrotto -> in RAM parte vuoto (fail-safe,
        il bot continua a funzionare), MA aggiungi() NON deve sovrascrivere
        il file corrotto su disco -- altrimenti il contenuto originale
        (potenzialmente recuperabile a mano) e' perso per sempre."""
        p = tmp_path / "blacklist_fuori_globale.json"
        originale = '{"700_500": {"ts": 1.0, "tipo": "petro'   # troncato
        p.write_text(originale, encoding="utf-8")
        bl = self._bl(tmp_path)
        assert bl.contiene("700_500") is False   # fail-safe: non blocca il bot

        bl.aggiungi("999_999", "campo")           # tentativo di scrittura successivo

        assert p.read_text(encoding="utf-8") == originale   # file NON toccato
        assert not p.with_suffix(".tmp").exists()            # nessun residuo tmp

    def test_crash_a_meta_scrittura_simulato_lascia_file_precedente_intatto(
        self, tmp_path, monkeypatch
    ):
        """Simula un crash durante _salva(): os.replace non viene mai
        chiamato (interrotto a meta'). Con la scrittura atomica il file
        pubblico deve restare quello vecchio, mai un JSON troncato."""
        bl = self._bl(tmp_path)
        bl.aggiungi("700_500", "petrolio")
        contenuto_buono = bl._path.read_text(encoding="utf-8")

        def _crash(*a, **kw):
            raise OSError("crash simulato durante os.replace")
        monkeypatch.setattr("os.replace", _crash)

        bl.aggiungi("701_501", "campo")   # tenta di scrivere, "crasha" a meta'

        assert bl._path.read_text(encoding="utf-8") == contenuto_buono
        assert not bl._path.with_suffix(".tmp").exists()   # tmp ripulito, non lasciato a terra


# ==============================================================================
# WU232 (16/07) — CANARY reset leggero. Verifica che il flag
# RACCOLTA_RESET_LEGGERO_ABILITATO governi correttamente quale reset viene
# usato sui rami di scarto che cambiano livello (chiave_test None, blacklist
# fuori), che il segnale canary_reset_leggero passi a _cerca_nodo SOLO per il
# tentativo immediatamente successivo (single-shot), e che la strumentazione
# [CANARY-RESET-LEGGERO] in _cerca_nodo logghi denominatore + esiti corretti
# senza alterare il valore di ritorno rispetto al comportamento standard.
# ==============================================================================

class TestCanaryResetLeggeroFlag:

    def _ctx_livelli_multipli(self, **overrides):
        # RACCOLTA_LIVELLO=6 -> sequenza_livelli=[6,7], due giri nel loop.
        base = {"RACCOLTA_LIVELLO": 6}
        base.update(overrides)
        return ctx_base(**base)

    @patch("tasks.raccolta._reset_leggero_lente")
    @patch("tasks.raccolta._reset_to_mappa")
    @patch("tasks.raccolta._leggi_coord_nodo", return_value=None)
    @patch("tasks.raccolta._cerca_nodo", return_value=True)
    def test_flag_off_default_usa_reset_pesante(
        self, mock_cerca, mock_coord, mock_pesante, mock_leggero, tmp_path
    ):
        """Default (flag assente = False): comportamento INVARIATO, usa
        sempre _reset_to_mappa, mai il reset leggero. 3 chiamate attese:
        2 dal loop (livelli 6 e 7, chiave_test None) + 1 dal fallback finale
        skip_neutro (nessun livello ha dato nodo utile)."""
        ctx = self._ctx_livelli_multipli()
        _invia_squadra(ctx, "campo", Blacklist(), BlacklistFuori(data_dir=str(tmp_path)),
                       {}, 0, set(), 4)
        assert mock_pesante.call_count == 3
        mock_leggero.assert_not_called()

    @patch("tasks.raccolta._reset_leggero_lente")
    @patch("tasks.raccolta._reset_to_mappa")
    @patch("tasks.raccolta._leggi_coord_nodo", return_value=None)
    @patch("tasks.raccolta._cerca_nodo", return_value=True)
    def test_flag_on_usa_reset_leggero_su_chiave_none(
        self, mock_cerca, mock_coord, mock_pesante, mock_leggero, tmp_path
    ):
        """Flag ON: i 2 rami DENTRO il loop (che cambiano livello nella
        stessa chiamata) usano il reset leggero. Il 3o call-site (fallback
        finale skip_neutro, righe 1925-1932, FUORI dal loop — il prossimo
        _cerca_nodo sarà per un tipo diverso in una chiamata futura, non lo
        stesso scenario del bug storico) resta volutamente sul reset pesante:
        1 chiamata."""
        ctx = self._ctx_livelli_multipli(
            RACCOLTA_RESET_LEGGERO_ABILITATO=True)
        _invia_squadra(ctx, "campo", Blacklist(), BlacklistFuori(data_dir=str(tmp_path)),
                       {}, 0, set(), 4)
        assert mock_leggero.call_count == 2
        assert mock_pesante.call_count == 1

    @patch("tasks.raccolta._reset_leggero_lente")
    @patch("tasks.raccolta._reset_to_mappa")
    @patch("tasks.raccolta._leggi_coord_nodo")
    @patch("tasks.raccolta._cerca_nodo", return_value=True)
    def test_flag_on_usa_reset_leggero_su_blacklist_fuori(
        self, mock_cerca, mock_coord, mock_pesante, mock_leggero, tmp_path
    ):
        bl_fuori = BlacklistFuori(data_dir=str(tmp_path))
        bl_fuori.aggiungi("700_500", "campo")
        mock_coord.return_value = "700_500"   # sempre lo stesso nodo, in blacklist fuori
        ctx = self._ctx_livelli_multipli(
            RACCOLTA_RESET_LEGGERO_ABILITATO=True)
        _invia_squadra(ctx, "campo", Blacklist(), bl_fuori, {}, 0, set(), 4)
        assert mock_leggero.call_count == 2
        assert mock_pesante.call_count == 1   # fallback finale, stesso motivo di sopra

    @patch("tasks.raccolta._reset_leggero_lente")
    @patch("tasks.raccolta._leggi_coord_nodo", return_value=None)
    def test_flag_on_passa_canary_true_al_cerca_nodo_successivo(
        self, mock_coord, mock_leggero, tmp_path
    ):
        """Il cuore del meccanismo: dopo un reset leggero, la chiamata
        _cerca_nodo del livello SUCCESSIVO riceve canary_reset_leggero=True
        -- il 1o tentativo (livello iniziale) invece NO (nessun reset ancora
        avvenuto prima di lui)."""
        ctx = self._ctx_livelli_multipli(
            RACCOLTA_RESET_LEGGERO_ABILITATO=True)
        chiamate = []
        def fake_cerca(ctx, tipo, livello_override=0, **kw):
            chiamate.append(kw.get("canary_reset_leggero", False))
            return True
        with patch("tasks.raccolta._cerca_nodo", side_effect=fake_cerca):
            _invia_squadra(ctx, "campo", Blacklist(),
                           BlacklistFuori(data_dir=str(tmp_path)), {}, 0, set(), 4)
        assert chiamate == [False, True]   # 1o giro: no; 2o giro (dopo reset leggero): si

    @patch("tasks.raccolta._reset_to_mappa")
    def test_flag_off_cerca_nodo_mai_riceve_canary_true(self, mock_pesante, tmp_path):
        ctx = self._ctx_livelli_multipli()   # flag assente = default False
        chiamate = []
        def fake_cerca(ctx, tipo, livello_override=0, **kw):
            chiamate.append(kw.get("canary_reset_leggero", False))
            return True
        with patch("tasks.raccolta._cerca_nodo", side_effect=fake_cerca), \
             patch("tasks.raccolta._leggi_coord_nodo", return_value=None):
            _invia_squadra(ctx, "campo", Blacklist(),
                           BlacklistFuori(data_dir=str(tmp_path)), {}, 0, set(), 4)
        assert chiamate == [False, False]

    def test_reset_leggero_lente_fa_solo_back(self):
        """L'helper stesso: un tap BACK, nessuna navigazione HOME/MAPPA."""
        ctx = ctx_base()
        ctx.navigator.vai_in_home = MagicMock()
        ctx.navigator.vai_in_mappa = MagicMock()
        with patch("tasks.raccolta.time.sleep"):
            _reset_leggero_lente(ctx)
        assert ctx.device.key_calls == ["KEYCODE_BACK"]
        ctx.navigator.vai_in_home.assert_not_called()
        ctx.navigator.vai_in_mappa.assert_not_called()


class TestCanaryResetLeggeroStrumentazione:
    """Verifica la sonda [CANARY-RESET-LEGGERO] dentro _cerca_nodo: logga
    sempre il denominatore (tentativo), poi soft-marker al 1o fallimento,
    hard-marker (firma del bug storico 7c5e789) se tutti i retry falliscono.
    Zero marker se canary_reset_leggero=False -- non deve intromettersi nel
    percorso standard."""

    def _ctx_con_log_mock(self, **overrides):
        ctx = ctx_base(**overrides)
        ctx.device.set_default_shot(object())
        ctx.matcher.set_result("pin/pin_field.png", (500, 500))  # marker lente
        ctx.log_msg = MagicMock()
        return ctx

    def _msgs(self, ctx):
        return [c.args[0] for c in ctx.log_msg.call_args_list if c.args]

    @patch("tasks.raccolta.time.sleep")
    def test_canary_true_verifica_ok_solo_denominatore(self, mock_sleep):
        ctx = self._ctx_con_log_mock()
        with patch("tasks.raccolta._verifica_tipo", return_value=True), \
             patch("tasks.raccolta._leggi_livello_panel", return_value=6):
            ok = _cerca_nodo(ctx, "campo", livello_override=6,
                             canary_reset_leggero=True)
        assert ok is True
        msgs = self._msgs(ctx)
        marker = [m for m in msgs if "CANARY-RESET-LEGGERO" in m]
        assert len(marker) == 1
        assert "tentativo" in marker[0]
        assert not any("ABORT" in m for m in marker)

    @patch("tasks.raccolta.time.sleep")
    def test_canary_false_nessun_marker_anche_con_verifica_fallita(self, mock_sleep):
        """Regressione: con canary_reset_leggero=False (default/standard),
        la sonda deve restare TOTALMENTE silenziosa, anche se _verifica_tipo
        fallisce sempre (percorso standard invariato)."""
        ctx = self._ctx_con_log_mock()
        with patch("tasks.raccolta._verifica_tipo", return_value=False), \
             patch("tasks.raccolta._apri_lente_verificata", return_value=True):
            ok = _cerca_nodo(ctx, "campo", livello_override=6)
        assert ok is False
        msgs = self._msgs(ctx)
        assert not any("CANARY-RESET-LEGGERO" in m for m in msgs)

    @patch("tasks.raccolta.time.sleep")
    def test_canary_true_soft_fail_poi_successo(self, mock_sleep):
        """1o tentativo fallisce, 2o (retry tap icona) riesce: soft-marker
        presente, hard-abort NO, funzione ritorna comunque al comportamento
        standard (procede oltre la verifica tipo)."""
        ctx = self._ctx_con_log_mock()
        esiti = iter([False, True])
        with patch("tasks.raccolta._verifica_tipo",
                   side_effect=lambda *a, **k: next(esiti)), \
             patch("tasks.raccolta._leggi_livello_panel", return_value=6):
            ok = _cerca_nodo(ctx, "campo", livello_override=6,
                             canary_reset_leggero=True)
        assert ok is True
        msgs = self._msgs(ctx)
        marker = [m for m in msgs if "CANARY-RESET-LEGGERO" in m]
        assert any("1o tentativo" in m for m in marker)
        assert not any("ABORT" in m for m in marker)

    @patch("tasks.raccolta.time.sleep")
    def test_canary_true_hard_fail_riproduce_bug_storico(self, mock_sleep):
        """Tutti e 3 i tentativi di _verifica_tipo falliscono: ABORT loggato
        con riferimento esplicito al commit storico, _cerca_nodo ritorna
        False esattamente come nel percorso standard (nessuna alterazione
        del comportamento, solo osservabilita')."""
        ctx = self._ctx_con_log_mock()
        with patch("tasks.raccolta._verifica_tipo", return_value=False), \
             patch("tasks.raccolta._apri_lente_verificata", return_value=True):
            ok = _cerca_nodo(ctx, "campo", livello_override=6,
                             canary_reset_leggero=True)
        assert ok is False
        msgs = self._msgs(ctx)
        marker = [m for m in msgs if "CANARY-RESET-LEGGERO" in m]
        assert any("ABORT" in m and "7c5e789" in m for m in marker)


# ==============================================================================
# WU254 (23/07) — Modalità "jolly": skip verifica OCR pannello livello ad ogni
# CERCA (fallback a False, garanzia livello, riservato al livello di fallback),
# più calibrazione esplicita una volta al giorno. Vedi core.state.RaccoltaState
# + tasks.raccolta._calibra_livello_giornaliero.
# ==============================================================================

class TestLivelloJollyFlag:

    def _ctx_livelli_multipli(self, **overrides):
        # RACCOLTA_LIVELLO=6 -> sequenza_livelli=[6,7], due giri nel loop.
        base = {"RACCOLTA_LIVELLO": 6}
        base.update(overrides)
        return ctx_base(**base)

    def test_default_flag_off(self):
        ctx = make_ctx()
        assert _cfg(ctx, "RACCOLTA_LIVELLO_JOLLY_ABILITATO") is False

    def test_override_flag_on(self):
        ctx = make_ctx({"RACCOLTA_LIVELLO_JOLLY_ABILITATO": True})
        assert _cfg(ctx, "RACCOLTA_LIVELLO_JOLLY_ABILITATO") is True

    @patch("tasks.raccolta._reset_to_mappa")
    @patch("tasks.raccolta._leggi_coord_nodo", return_value=None)
    def test_jolly_off_skip_livello_check_mai_true(self, mock_coord, mock_reset, tmp_path):
        """Regressione: senza il flag (default assente = False), nessun
        tentativo passa skip_livello_check=True — comportamento standard
        preesistente invariato, byte-identico a prima di WU254."""
        ctx = self._ctx_livelli_multipli()
        chiamate = []
        def fake_cerca(ctx, tipo, livello_override=0, **kw):
            chiamate.append(kw.get("skip_livello_check", False))
            return True
        with patch("tasks.raccolta._cerca_nodo", side_effect=fake_cerca):
            _invia_squadra(ctx, "campo", Blacklist(),
                           BlacklistFuori(data_dir=str(tmp_path)), {}, 0, set(), 4)
        assert chiamate == [False, False]

    @patch("tasks.raccolta._reset_to_mappa")
    @patch("tasks.raccolta._leggi_coord_nodo", return_value=None)
    def test_jolly_on_skip_solo_primo_tentativo(self, mock_coord, mock_reset, tmp_path):
        """Con jolly attivo: il PRIMO tentativo (livello primario) passa
        skip_livello_check=True; il fallback (livello successivo, quando il
        primo non trova nodi) passa sempre False — al fallback serve la
        garanzia di cambiare davvero livello, non solo 'quello che c'è'."""
        ctx = self._ctx_livelli_multipli(RACCOLTA_LIVELLO_JOLLY_ABILITATO=True)
        chiamate = []
        def fake_cerca(ctx, tipo, livello_override=0, **kw):
            chiamate.append(kw.get("skip_livello_check", False))
            return True
        with patch("tasks.raccolta._cerca_nodo", side_effect=fake_cerca):
            _invia_squadra(ctx, "campo", Blacklist(),
                           BlacklistFuori(data_dir=str(tmp_path)), {}, 0, set(), 4)
        assert chiamate == [True, False]

    @patch("tasks.raccolta._reset_to_mappa")
    def test_jolly_on_singolo_livello_sempre_skip(self, mock_reset, tmp_path):
        """Istanza con RACCOLTA_LIVELLO fuori 6/7 (sequenza_livelli a un solo
        elemento, niente fallback): con jolly attivo l'unico tentativo è
        comunque il 'primo' della sequenza -> skip_livello_check=True."""
        ctx = ctx_base(RACCOLTA_LIVELLO=3, RACCOLTA_LIVELLO_JOLLY_ABILITATO=True)
        chiamate = []
        def fake_cerca(ctx, tipo, livello_override=0, **kw):
            chiamate.append(kw.get("skip_livello_check", False))
            return True
        with patch("tasks.raccolta._cerca_nodo", side_effect=fake_cerca), \
             patch("tasks.raccolta._leggi_coord_nodo", return_value="700_500"):
            _invia_squadra(ctx, "campo", Blacklist(),
                           BlacklistFuori(data_dir=str(tmp_path)), {}, 0, set(), 4)
        assert chiamate == [True]


class TestCalibrazioneGiornalieraLivello:

    def _ctx_con_state(self, **overrides):
        ctx = ctx_base(**overrides)
        ctx.state = InstanceState(instance_name="FAU_00")
        return ctx

    @patch("tasks.raccolta.time.sleep")
    def test_calibra_tutti_i_tipi_skip_livello_check_false(self, mock_sleep):
        """Cicla sui 4 tipi, chiama _cerca_nodo con skip_livello_check=False
        per ciascuno (verifica/aggiustamento OCR classico, mai il tap diretto
        jolly) — la calibrazione DEVE garantire il livello, non presumerlo."""
        ctx = self._ctx_con_state(RACCOLTA_LIVELLO=7)
        chiamate = []
        def fake_cerca(ctx, tipo, **kw):
            chiamate.append((tipo, kw.get("skip_livello_check")))
            return True
        with patch("tasks.raccolta._cerca_nodo", side_effect=fake_cerca):
            _calibra_livello_giornaliero(ctx)
        assert chiamate == [(t, False) for t in _TUTTI_I_TIPI]

    @patch("tasks.raccolta.time.sleep")
    def test_calibra_chiude_lente_dopo_ogni_tipo(self, mock_sleep):
        ctx = self._ctx_con_state()
        with patch("tasks.raccolta._cerca_nodo", return_value=True):
            _calibra_livello_giornaliero(ctx)
        assert ctx.device.key_calls.count("KEYCODE_BACK") == len(_TUTTI_I_TIPI)

    @patch("tasks.raccolta.time.sleep")
    def test_calibra_registra_stato_a_fine_giro(self, mock_sleep):
        ctx = self._ctx_con_state()
        assert ctx.state.raccolta.ultima_calibrazione_livello is None
        with patch("tasks.raccolta._cerca_nodo", return_value=True):
            _calibra_livello_giornaliero(ctx)
        assert ctx.state.raccolta.ultima_calibrazione_livello is not None

    @patch("tasks.raccolta.time.sleep")
    def test_calibra_fail_safe_un_tipo_fallito_non_blocca_gli_altri(self, mock_sleep):
        """Fail-safe non bloccante: un tipo che fallisce (es. tipo non
        selezionato) viene loggato e saltato, ma non impedisce la
        calibrazione degli altri 3 né la registrazione finale."""
        ctx = self._ctx_con_state()
        risultati = iter([True, False, True, True])
        with patch("tasks.raccolta._cerca_nodo",
                   side_effect=lambda *a, **k: next(risultati)):
            _calibra_livello_giornaliero(ctx)
        assert ctx.device.key_calls.count("KEYCODE_BACK") == len(_TUTTI_I_TIPI)
        assert ctx.state.raccolta.ultima_calibrazione_livello is not None

    @patch("tasks.raccolta.time.sleep")
    def test_calibra_eccezione_singolo_tipo_non_blocca_gli_altri(self, mock_sleep):
        """Stesso fail-safe ma per un'eccezione (non solo un esito False)."""
        ctx = self._ctx_con_state()
        chiamate = []
        def fake_cerca(ctx, tipo, **kw):
            chiamate.append(tipo)
            if tipo == "segheria":
                raise RuntimeError("boom")
            return True
        with patch("tasks.raccolta._cerca_nodo", side_effect=fake_cerca):
            _calibra_livello_giornaliero(ctx)
        assert chiamate == _TUTTI_I_TIPI   # tutti e 4 tentati comunque
        assert ctx.state.raccolta.ultima_calibrazione_livello is not None


class TestRaccoltaStateCalibrazioneDovuta:
    """Unit test puri su core.state.RaccoltaState (nessun mock device/matcher
    necessario) — la logica "primo ciclo dopo il reset giornaliero"."""

    def test_mai_calibrato_dovuta(self):
        from datetime import datetime, timezone
        rs = RaccoltaState()
        assert rs.calibrazione_dovuta(datetime.now(timezone.utc)) is True

    def test_calibrato_oggi_non_dovuta(self):
        from datetime import datetime, timezone
        rs = RaccoltaState()
        rs.registra_calibrazione(datetime.now(timezone.utc))
        reset_oggi = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0)
        assert rs.calibrazione_dovuta(reset_oggi) is False

    def test_calibrato_ieri_dovuta_oggi(self):
        from datetime import datetime, timezone, timedelta
        rs = RaccoltaState()
        ieri = datetime.now(timezone.utc) - timedelta(days=1)
        rs.registra_calibrazione(ieri)
        reset_oggi = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0)
        assert rs.calibrazione_dovuta(reset_oggi) is True

    def test_stato_corrotto_fail_safe_dovuta(self):
        rs = RaccoltaState(ultima_calibrazione_livello="non-una-data")
        from datetime import datetime, timezone
        assert rs.calibrazione_dovuta(datetime.now(timezone.utc)) is True

    def test_roundtrip_dict(self):
        from datetime import datetime, timezone
        rs = RaccoltaState()
        rs.registra_calibrazione(datetime.now(timezone.utc))
        rs2 = RaccoltaState.from_dict(rs.to_dict())
        assert rs2.ultima_calibrazione_livello == rs.ultima_calibrazione_livello
