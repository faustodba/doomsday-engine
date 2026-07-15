# ==============================================================================
#  tests/unit/test_logger.py
#
#  Unit test per core/logger.py
# ==============================================================================

import json
import os
import tempfile
from pathlib import Path

import pytest

from core.logger import (
    LogLevel,
    StructuredLogger,
    close_all_loggers,
    get_logger,
)


# ==============================================================================
# Fixture
# ==============================================================================

def make_logger(tmpdir, instance="FAU_TEST", level=LogLevel.DEBUG, console=False):
    """Crea un logger su directory temporanea senza output console."""
    return StructuredLogger(
        instance_name=instance,
        log_dir=tmpdir,
        min_level=level,
        console=console,
        colors=False,
    )


def read_lines(logger: StructuredLogger) -> list[dict]:
    """Legge tutte le righe JSONL del file di log."""
    logger._file.flush()
    path = logger._file_path
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(json.loads(line))
    return lines


# ==============================================================================
# TestLogLevel
# ==============================================================================

class TestLogLevel:

    def test_ordine(self):
        assert LogLevel.DEBUG < LogLevel.INFO < LogLevel.WARNING < LogLevel.ERROR

    def test_label(self):
        assert LogLevel.DEBUG.label() == "DEBUG"
        assert LogLevel.ERROR.label() == "ERROR"

    def test_valori(self):
        assert LogLevel.DEBUG == 10
        assert LogLevel.INFO == 20
        assert LogLevel.WARNING == 30
        assert LogLevel.ERROR == 40


# ==============================================================================
# TestStructuredLogger — scrittura base
# ==============================================================================

class TestStructuredLoggerBase:

    def test_crea_file_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = make_logger(tmpdir)
            log.info("test", "ciao")
            log.close()
            assert (Path(tmpdir) / "FAU_TEST.jsonl").exists()

    def test_crea_directory_se_non_esiste(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "nested", "logs")
            log = StructuredLogger("FAU_00", log_dir=subdir, console=False)
            log.info("test", "msg")
            log.close()
            assert os.path.exists(os.path.join(subdir, "FAU_00.jsonl"))

    def test_messaggio_campi_fissi(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = make_logger(tmpdir, instance="FAU_05")
            log.info("raccolta", "Marcia inviata")
            lines = read_lines(log)
            log.close()

            assert len(lines) == 1
            r = lines[0]
            assert r["level"] == "INFO"
            assert r["instance"] == "FAU_05"
            assert r["module"] == "raccolta"
            assert r["msg"] == "Marcia inviata"
            assert "ts" in r

    def test_campi_extra(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = make_logger(tmpdir)
            log.info("boost", "Speed boost", durata_h=8, score=0.92)
            lines = read_lines(log)
            log.close()

            r = lines[0]
            assert r["durata_h"] == 8
            assert r["score"] == 0.92

    def test_tutti_i_livelli(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = make_logger(tmpdir)
            log.debug("m", "debug msg")
            log.info("m", "info msg")
            log.warning("m", "warning msg")
            log.error("m", "error msg")
            lines = read_lines(log)
            log.close()

            levels = [l["level"] for l in lines]
            assert levels == ["DEBUG", "INFO", "WARNING", "ERROR"]

    def test_metodo_log_generico(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = make_logger(tmpdir)
            log.log(LogLevel.WARNING, "nav", "schermata sconosciuta")
            lines = read_lines(log)
            log.close()
            assert lines[0]["level"] == "WARNING"

    def test_repr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = make_logger(tmpdir, instance="FAU_01")
            r = repr(log)
            log.close()
            assert "FAU_01" in r
            assert "DEBUG" in r


# ==============================================================================
# TestStructuredLogger — filtro livello
# ==============================================================================

class TestStructuredLoggerLevel:

    def test_filtra_debug_con_info(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = make_logger(tmpdir, level=LogLevel.INFO)
            log.debug("m", "non deve apparire")
            log.info("m", "deve apparire")
            lines = read_lines(log)
            log.close()
            assert len(lines) == 1
            assert lines[0]["level"] == "INFO"

    def test_filtra_tutto_sotto_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = make_logger(tmpdir, level=LogLevel.ERROR)
            log.debug("m", "x")
            log.info("m", "x")
            log.warning("m", "x")
            log.error("m", "solo questo")
            lines = read_lines(log)
            log.close()
            assert len(lines) == 1
            assert lines[0]["level"] == "ERROR"

    def test_debug_level_scrive_tutto(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = make_logger(tmpdir, level=LogLevel.DEBUG)
            for _ in range(4):
                log.debug("m", "x")
            lines = read_lines(log)
            log.close()
            assert len(lines) == 4


# ==============================================================================
# TestStructuredLogger — rotazione file
# ==============================================================================

class TestStructuredLoggerRotation:

    def test_rotazione_crea_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # max_bytes molto piccolo per triggerare la rotazione
            log = StructuredLogger(
                "FAU_ROT", log_dir=tmpdir, console=False, max_bytes=200
            )
            # Scrive abbastanza da superare 200 byte
            for i in range(20):
                log.info("test", f"messaggio lungo numero {i:04d} con dati extra")
            log.close()

            # Deve esistere sia il file corrente che il backup
            assert (Path(tmpdir) / "FAU_ROT.jsonl").exists()
            assert (Path(tmpdir) / "FAU_ROT.jsonl.1").exists()

    def test_dopo_rotazione_continua_a_scrivere(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = StructuredLogger(
                "FAU_ROT2", log_dir=tmpdir, console=False, max_bytes=300
            )
            for i in range(30):
                log.info("test", f"msg {i}")
            log.info("test", "ultimo messaggio post-rotazione")
            log._file.flush()

            # Il file corrente deve contenere almeno l'ultimo messaggio
            path = Path(tmpdir) / "FAU_ROT2.jsonl"
            content = path.read_text(encoding="utf-8")
            assert "ultimo messaggio post-rotazione" in content
            log.close()


# ==============================================================================
# TestGetLogger — registry globale
# ==============================================================================

class TestGetLogger:

    def setup_method(self):
        """Pulisce il registry prima di ogni test."""
        close_all_loggers()

    def teardown_method(self):
        close_all_loggers()

    # WU227 — questi due chiudevano il registry lasciando l'handle aperto e la
    # TemporaryDirectory non riusciva a cancellarsi (PermissionError su
    # Windows): fallivano da sempre, per lo stesso identico motivo del bug di
    # rotazione corretto in WU227. `close_all_loggers()` in coda li sana.
    def test_stesso_logger_per_stesso_nome(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log1 = get_logger("FAU_00", log_dir=tmpdir, console=False)
            log2 = get_logger("FAU_00", log_dir=tmpdir, console=False)
            assert log1 is log2
            close_all_loggers()

    def test_logger_diversi_per_nomi_diversi(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log1 = get_logger("FAU_00", log_dir=tmpdir, console=False)
            log2 = get_logger("FAU_01", log_dir=tmpdir, console=False)
            assert log1 is not log2
            close_all_loggers()

    def test_close_all_loggers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = get_logger("FAU_02", log_dir=tmpdir, console=False)
            log.info("test", "pre-close")
            close_all_loggers()
            assert log._file.closed

    def test_dopo_close_all_nuovo_logger_ricreato(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log1 = get_logger("FAU_03", log_dir=tmpdir, console=False)
            close_all_loggers()
            log2 = get_logger("FAU_03", log_dir=tmpdir, console=False)
            assert log1 is not log2
            log2.close()


# ==============================================================================
# WU227 — rotazione forzata con handle aperto
# ==============================================================================

class TestRotate:
    """WU227 (15/07): `main.py::_thread_istanza` ruotava il .jsonl con un
    os.replace diretto dentro un `except: pass`. Ma get_logger() tiene il
    StructuredLogger nel registry con l'handle APERTO, e su Windows il rename
    di un file aperto fallisce → la rotazione riusciva solo alla PRIMA run di
    ogni istanza dopo un riavvio, poi falliva in silenzio accumulando più tick
    nello stesso file. Scoperto col doppio giro FAU_00 (WU221)."""

    def test_rotate_sposta_contenuto_e_riparte_da_vuoto(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = make_logger(tmpdir)
            log.info("tick1", "primo passaggio")
            assert log.rotate() is True

            bak = Path(tmpdir) / "FAU_TEST.jsonl.bak"
            assert bak.exists()
            assert "primo passaggio" in bak.read_text(encoding="utf-8")

            # il file corrente riparte vuoto e resta scrivibile
            assert read_lines(log) == []
            log.info("tick2", "secondo passaggio")
            righe = read_lines(log)
            assert len(righe) == 1
            assert righe[0]["msg"] == "secondo passaggio"
            log.close()

    def test_rotate_con_handle_aperto_e_il_caso_che_falliva(self):
        """Il cuore del bug: il logger sta scrivendo (handle aperto) e si
        ruota. Un os.replace fatto da fuori qui fallirebbe su Windows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log = make_logger(tmpdir)
            log.info("tick1", "riga con handle aperto")
            assert log._file.closed is False      # handle vivo
            assert log.rotate() is True
            assert log._file.closed is False      # riaperto dopo la rotazione
            assert read_lines(log) == []
            log.close()

    def test_rotate_su_file_inesistente_non_esplode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = make_logger(tmpdir)
            log.close()
            (Path(tmpdir) / "FAU_TEST.jsonl").unlink()
            assert log.rotate() is False

    def test_rotate_sovrascrive_bak_precedente(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = make_logger(tmpdir)
            log.info("t", "vecchio")
            log.rotate()
            log.info("t", "nuovo")
            log.rotate()
            bak = (Path(tmpdir) / "FAU_TEST.jsonl.bak").read_text(encoding="utf-8")
            assert "nuovo" in bak and "vecchio" not in bak   # max 1 backup
            log.close()


class TestRotateLogger:
    """`rotate_logger()` — usata da main.py: deve funzionare sia col logger già
    nel registry (handle aperto) sia senza (prima run dopo l'avvio)."""

    def test_delega_al_logger_del_registry(self):
        from core.logger import rotate_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = get_logger("FAU_ROT", log_dir=tmpdir, console=False)
            log.info("tick1", "primo")
            assert rotate_logger("FAU_ROT", log_dir=tmpdir) is True
            # stesso oggetto logger, file nuovo e vuoto
            assert get_logger("FAU_ROT", log_dir=tmpdir, console=False) is log
            assert read_lines(log) == []
            assert "primo" in (Path(tmpdir) / "FAU_ROT.jsonl.bak").read_text(encoding="utf-8")
            close_all_loggers()

    def test_due_rotazioni_consecutive_stessa_istanza(self):
        """Il caso doppio giro: la stessa istanza gira due volte nello stesso
        processo. Pre-WU227 la seconda rotazione falliva in silenzio."""
        from core.logger import rotate_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = get_logger("FAU_DG", log_dir=tmpdir, console=False)
            log.info("t", "primo passaggio")
            assert rotate_logger("FAU_DG", log_dir=tmpdir) is True
            log.info("t", "secondo passaggio")
            assert rotate_logger("FAU_DG", log_dir=tmpdir) is True

            bak = (Path(tmpdir) / "FAU_DG.jsonl.bak").read_text(encoding="utf-8")
            assert "secondo passaggio" in bak
            assert "primo passaggio" not in bak   # i due passaggi NON mescolati
            close_all_loggers()

    def test_senza_logger_in_registry_rinomina_comunque(self):
        from core.logger import rotate_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            close_all_loggers()
            p = Path(tmpdir) / "FAU_NEW.jsonl"
            p.write_text('{"msg":"da un run precedente"}\n', encoding="utf-8")
            assert rotate_logger("FAU_NEW", log_dir=tmpdir) is True
            assert not p.exists()
            assert (Path(tmpdir) / "FAU_NEW.jsonl.bak").exists()

    def test_file_assente_ritorna_false(self):
        from core.logger import rotate_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            close_all_loggers()
            assert rotate_logger("FAU_MAI_VISTA", log_dir=tmpdir) is False
