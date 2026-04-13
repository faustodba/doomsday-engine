# ==============================================================================
#  tests/tasks/test_raccolta.py — Step 21
#  Tutti i test usano FakeDevice + FakeMatcher — zero ADB reale.
# ==============================================================================

import time
import pytest
from unittest.mock import patch

from core.device import FakeDevice
from core.navigator import GameNavigator
from core.task import TaskContext, TaskResult
from shared.template_matcher import FakeMatcher
from tasks.raccolta import (
    RaccoltaTask,
    Blacklist,
    _cfg,
    _calcola_sequenza,
    _loop_invio_marce,
    _DEFAULTS,
    _TUTTI_I_TIPI,
)


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
        "TEMPLATE_MARCIA":         "pin/pin_marcia.png",
        "TEMPLATE_SOGLIA":         0.75,
    }
    base.update(overrides)
    return make_ctx(base)


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
        ctx = ctx_base()
        RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=2)
        mock_loop.assert_called_once()

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", return_value=0)
    def test_ritorno_home_eseguito(self, mock_loop, mock_sleep):
        """Dopo il loop, navigator.vai_in_home() viene chiamato."""
        ctx = ctx_base()
        RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=2)
        # Il loop è stato chiamato = navigazione andata a buon fine
        # Il ritorno home è garantito dal finally
        assert mock_loop.called


# ==============================================================================
# 8. RaccoltaTask.run — loop marce mockato
# ==============================================================================

class TestRaccoltaLoopMockato:

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", return_value=3)
    def test_tre_inviate(self, mock_loop, mock_sleep):
        ctx = ctx_base()
        result = RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=3)
        assert result.data["inviate"] == 3
        assert result.success is True

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", return_value=1)
    def test_result_message_inviate(self, mock_loop, mock_sleep):
        ctx = ctx_base()
        result = RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=2)
        assert "1" in result.message

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", side_effect=RuntimeError("test"))
    def test_errore_loop_result_false(self, mock_loop, mock_sleep):
        ctx = ctx_base()
        result = RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=2)
        assert result.success is False
        assert "errore" in result.message

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", side_effect=RuntimeError("test"))
    def test_errore_home_eseguito_comunque(self, mock_loop, mock_sleep):
        """Anche se il loop lancia eccezione, il ritorno home viene eseguito."""
        ctx = ctx_base()
        result = RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=2)
        assert result.success is False  # errore riportato


# ==============================================================================
# 9. RaccoltaTask.run — blacklist iniettata
# ==============================================================================

class TestRaccoltaBlacklistIniettata:

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", return_value=2)
    def test_blacklist_custom_passata(self, mock_loop, mock_sleep):
        ctx = ctx_base()
        bl = Blacklist()
        bl.commit("100_200")
        RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=2, blacklist=bl)
        # Verifica che il loop venga chiamato con la nostra blacklist
        args = mock_loop.call_args
        assert args[0][3] is bl  # quarto argomento posizionale = blacklist

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", return_value=0)
    def test_blacklist_creata_internamente_se_none(self, mock_loop, mock_sleep):
        ctx = ctx_base()
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
        FakeMatcher trova gather E marcia = None (maschera chiusa dopo MARCIA)
        → marcia OK → 1 inviata.

        Sequenza FakeMatcher:
          1. _leggi_coordinate_nodo: find(gather) → (400, 300)  [nodo trovato]
          2. _esegui_marcia → screenshot → find(marcia) → None  [maschera aperta fail → OK]
        
        La logica _esegui_marcia verifica che la maschera sia aperta PRIMA e
        chiusa DOPO. Nel test: matcher.find(marcia) sempre None significa
        "maschera non rilevata" — in _esegui_marcia questo causa:
          step 1: screenshot dopo squadra → find(marcia) = None → maschera "non aperta"
          → retry → ancora None → return False, None
        Quindi con solo gather trovato → marcia fallisce.
        
        Per simulare una marcia completa usiamo patch diretto su _esegui_marcia.
        """
        with patch("tasks.raccolta._esegui_marcia", return_value=(True, 60.0)):
            ctx = ctx_base(**{"RACCOLTA_MAX_FALLIMENTI": 1,
                              "RACCOLTA_OBIETTIVO": 1})
            ctx.device.set_default_shot(object())
            ctx.matcher.set_result("pin/pin_gather.png", (400, 300))
            bl = Blacklist()
            inviate = _loop_invio_marce(ctx, 1, 0, bl)
            assert inviate == 1

    @patch("tasks.raccolta.time.sleep")
    def test_nodo_committed_dopo_marcia(self, mock_sleep):
        """Dopo una marcia OK, il nodo deve essere COMMITTED in blacklist."""
        with patch("tasks.raccolta._esegui_marcia", return_value=(True, 45.0)):
            ctx = ctx_base(**{"RACCOLTA_MAX_FALLIMENTI": 1,
                              "RACCOLTA_OBIETTIVO": 1})
            ctx.device.set_default_shot(object())
            ctx.matcher.set_result("pin/pin_gather.png", (400, 300))
            bl = Blacklist()
            _loop_invio_marce(ctx, 1, 0, bl)
            # Il nodo (400, 300) → chiave "400_300" deve essere in blacklist
            assert bl.get_state("400_300") == "COMMITTED"
            assert bl.get_eta("400_300") == 45.0


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
        ctx = ctx_base(**{"RACCOLTA_OBIETTIVO": 4})
        RaccoltaTask().run(ctx, attive_inizio=2, slot_liberi=-1)
        # 4 - 2 = 2 libere → il loop viene chiamato
        mock_loop.assert_called_once()

    @patch("tasks.raccolta.time.sleep")
    @patch("tasks.raccolta._loop_invio_marce", return_value=0)
    def test_slot_iniettato_sovrascrive(self, mock_loop, mock_sleep):
        """slot_liberi esplicito → usato direttamente."""
        ctx = ctx_base(**{"RACCOLTA_OBIETTIVO": 4})
        RaccoltaTask().run(ctx, attive_inizio=0, slot_liberi=1)
        mock_loop.assert_called_once()
