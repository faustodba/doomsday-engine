# ==============================================================================
#  DOOMSDAY ENGINE V6 - core/device.py
#
#  Astrazione del device fisico (MuMu Player via ADB).
#
#  Classi:
#    Screenshot    — immagine in memoria con metodi di analisi
#    MuMuDevice    — comunicazione async con una istanza MuMu
#    FakeDevice    — implementazione per test, risponde con screenshot precaricati
#
#  Design:
#    - Tutte le operazioni I/O sono async (asyncio.create_subprocess_exec)
#    - Screenshot non tocca mai il filesystem locale: pull diretto in memoria
#    - MuMuDevice è l'unica implementazione reale — nessuna astrazione multi-emulatore
# ==============================================================================

from __future__ import annotations

import asyncio
import io
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np
from PIL import Image


# ==============================================================================
# MatchResult — risultato template matching
# ==============================================================================

class MatchResult(NamedTuple):
    found: bool
    score: float
    cx: int          # coordinata X centro del match (assoluta)
    cy: int          # coordinata Y centro del match (assoluta)

    @property
    def coords(self) -> tuple[int, int]:
        return (self.cx, self.cy)


# ==============================================================================
# Screenshot — immagine in memoria
# ==============================================================================

class Screenshot:
    """
    Immagine acquisita dall'emulatore, tenuta in RAM come numpy array BGR.

    Non scrive mai su disco. Espone metodi di analisi (template matching,
    OCR, pixel sampling) direttamente sull'oggetto.
    """

    def __init__(self, data: np.ndarray, timestamp: float | None = None):
        """
        Args:
            data: array BGR (H, W, 3) — formato OpenCV standard
            timestamp: epoch time acquisizione (default: now)
        """
        if data is None or data.size == 0:
            raise ValueError("Screenshot: dati immagine vuoti o None")
        self._data = data
        self.timestamp = timestamp or time.monotonic()

    # ── Costruttori alternativi ──────────────────────────────────────────────

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Screenshot":
        """Costruisce da bytes PNG/JPEG (output ADB pull)."""
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Screenshot.from_bytes: impossibile decodificare immagine")
        return cls(img)

    @classmethod
    def from_file(cls, path: str | Path) -> "Screenshot":
        """Costruisce da file PNG su disco — usato solo nei test (fixture)."""
        img = cv2.imread(str(path))
        if img is None:
            raise ValueError(f"Screenshot.from_file: file non trovato o non leggibile: {path}")
        return cls(img)

    # ── Proprietà ────────────────────────────────────────────────────────────

    @property
    def width(self) -> int:
        return self._data.shape[1]

    @property
    def height(self) -> int:
        return self._data.shape[0]

    @property
    def array(self) -> np.ndarray:
        """Array BGR originale — sola lettura."""
        return self._data

    # ── Template matching ────────────────────────────────────────────────────

    def match_template(
        self,
        template: "Screenshot",
        threshold: float = 0.75,
        zone: tuple[int, int, int, int] | None = None,
    ) -> MatchResult:
        """
        Cerca il template nell'immagine.

        Args:
            template:  Screenshot del template da cercare
            threshold: soglia minima score (0.0–1.0)
            zone:      (x1, y1, x2, y2) zona di ricerca — None = tutta l'immagine

        Returns:
            MatchResult(found, score, cx, cy) con coordinate assolute.
        """
        img = self._data
        offset_x, offset_y = 0, 0

        if zone is not None:
            x1, y1, x2, y2 = zone
            img = self._data[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1

        tmpl = template.array
        th, tw = tmpl.shape[:2]

        if img.shape[0] < th or img.shape[1] < tw:
            return MatchResult(False, 0.0, 0, 0)

        result = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val < threshold:
            return MatchResult(False, float(max_val), 0, 0)

        cx = int(max_loc[0] + tw // 2 + offset_x)
        cy = int(max_loc[1] + th // 2 + offset_y)
        return MatchResult(True, float(max_val), cx, cy)

    def match_template_all(
        self,
        template: "Screenshot",
        threshold: float = 0.75,
        zone: tuple[int, int, int, int] | None = None,
        cluster_px: int = 20,
    ) -> list[MatchResult]:
        """
        Trova tutti i match del template (deduplicati per cluster).
        Usato per trovare più pulsanti identici (es. store items).
        """
        img = self._data
        offset_x, offset_y = 0, 0

        if zone is not None:
            x1, y1, x2, y2 = zone
            img = self._data[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1

        tmpl = template.array
        th, tw = tmpl.shape[:2]

        if img.shape[0] < th or img.shape[1] < tw:
            return []

        result = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= threshold)

        matches: list[MatchResult] = []
        for pt in zip(*locations[::-1]):
            score = float(result[pt[1], pt[0]])
            cx = int(pt[0] + tw // 2 + offset_x)
            cy = int(pt[1] + th // 2 + offset_y)
            # Deduplica: scarta se già c'è un match entro cluster_px
            if not any(
                abs(cx - m.cx) < cluster_px and abs(cy - m.cy) < cluster_px
                for m in matches
            ):
                matches.append(MatchResult(True, score, cx, cy))

        # Ordina per score decrescente
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    # ── Analisi pixel ────────────────────────────────────────────────────────

    def pixel_color(self, x: int, y: int) -> tuple[int, int, int]:
        """Ritorna (B, G, R) del pixel alle coordinate date."""
        return tuple(self._data[y, x])

    def count_pixels(
        self,
        zone: tuple[int, int, int, int],
        lower_bgr: tuple[int, int, int],
        upper_bgr: tuple[int, int, int],
    ) -> int:
        """
        Conta i pixel nella zona che rientrano nell'intervallo colore.

        Args:
            zone:      (x1, y1, x2, y2)
            lower_bgr: limite inferiore colore (B, G, R)
            upper_bgr: limite superiore colore (B, G, R)
        """
        x1, y1, x2, y2 = zone
        roi = self._data[y1:y2, x1:x2]
        lower = np.array(lower_bgr, dtype=np.uint8)
        upper = np.array(upper_bgr, dtype=np.uint8)
        mask = cv2.inRange(roi, lower, upper)
        return int(mask.sum() // 255)

    # ── Crop / utility ───────────────────────────────────────────────────────

    def crop(self, zone: tuple[int, int, int, int]) -> "Screenshot":
        """Ritorna un nuovo Screenshot ritagliato alla zona specificata."""
        x1, y1, x2, y2 = zone
        return Screenshot(self._data[y1:y2, x1:x2].copy())

    def to_pil(self) -> Image.Image:
        """Converte in PIL Image (RGB) — per OCR con pytesseract."""
        return Image.fromarray(cv2.cvtColor(self._data, cv2.COLOR_BGR2RGB))

    def save(self, path: str | Path) -> None:
        """Salva su disco — usato solo per debug e fixture."""
        cv2.imwrite(str(path), self._data)

    def __repr__(self) -> str:
        return f"Screenshot({self.width}x{self.height}, t={self.timestamp:.2f})"


# ==============================================================================
# MuMuDevice — comunicazione async con MuMu Player
# ==============================================================================

class MuMuDevice:
    """
    Interfaccia async con una singola istanza MuMu Player via ADB.

    Tutte le operazioni I/O usano asyncio.create_subprocess_exec —
    nessuna chiamata bloccante, nessun thread pool.

    Screenshot acquisiti con `adb exec-out screencap -p` direttamente
    in memoria — nessun file temporaneo su disco.
    """

    # ── Costanti MuMu ────────────────────────────────────────────────────────
    ADB_PORT_BASE: int = 16384
    ADB_PORT_STEP: int = 32

    # Path di default — sovrascrivibili via config se installazione non standard
    DEFAULT_ADB_EXE: str = r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe"
    DEFAULT_MANAGER_EXE: str = r"C:\Program Files\Netease\MuMuPlayer\shell\MuMuManager.exe"

    def __init__(
        self,
        index: int,
        name: str,
        adb_exe: str | None = None,
        manager_exe: str | None = None,
    ):
        """
        Args:
            index:       indice istanza MuMu (0–10)
            name:        nome istanza (es. "FAU_00") — usato nei log
            adb_exe:     path adb.exe — default: percorso MuMu standard
            manager_exe: path MuMuManager.exe — default: percorso MuMu standard
        """
        self.index       = index
        self.name        = name
        self.port        = self.ADB_PORT_BASE + index * self.ADB_PORT_STEP
        self.adb_serial  = f"127.0.0.1:{self.port}"
        self._adb_exe    = adb_exe or self.DEFAULT_ADB_EXE
        self._mgr_exe    = manager_exe or self.DEFAULT_MANAGER_EXE
        self._game_pid: int | None = None

    # ── Ciclo vita istanza ───────────────────────────────────────────────────

    async def launch(self) -> bool:
        """
        Avvia l'istanza MuMu via MuMuManager.
        Ritorna True se il comando è stato accettato (errcode=0).
        Non attende che Android sia pronto — usare wait_ready() dopo.
        """
        code, stdout, _ = await self._manager_run("control", "-v", str(self.index), "launch")
        return code == 0

    async def shutdown(self) -> None:
        """Spegne l'istanza MuMu via MuMuManager."""
        await self._manager_run("control", "-v", str(self.index), "shutdown")

    async def wait_ready(self, timeout: int = 120, poll_interval: float = 5.0) -> bool:
        """
        Attende che Android sia completamente avviato (init.svc.bootanim = stopped).

        Args:
            timeout:       secondi massimi di attesa
            poll_interval: secondi tra un controllo e il successivo

        Ritorna True se pronto entro timeout, False altrimenti.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            code, stdout, _ = await self._adb_run(
                "shell", "getprop", "init.svc.bootanim"
            )
            if code == 0 and stdout.strip() == "stopped":
                return True
            await asyncio.sleep(poll_interval)
        return False

    async def connect_adb(self) -> bool:
        """Connette ADB alla porta dell'istanza. Ritorna True se connesso."""
        code, stdout, _ = await self._adb_run_raw("connect", self.adb_serial)
        return code == 0 and "connected" in stdout.lower()

    async def is_running(self) -> bool:
        """
        Controlla se il processo del gioco è in esecuzione nell'istanza.
        Verifica tramite `ps` ADB cercando il package Doomsday.
        """
        code, stdout, _ = await self._adb_run(
            "shell", "pidof", "com.im30.ROE.gp"
        )
        if code != 0 or not stdout.strip():
            return False
        try:
            self._game_pid = int(stdout.strip().split()[0])
            return True
        except (ValueError, IndexError):
            return False

    async def start_game(self) -> None:
        """Avvia l'app del gioco tramite intent Android."""
        await self._adb_run(
            "shell", "am", "start",
            "-n", "com.im30.ROE.gp/com.im30.roe.UnityPlayerActivity"
        )

    async def stop_game(self) -> None:
        """Termina il processo del gioco."""
        await self._adb_run(
            "shell", "am", "force-stop", "com.im30.ROE.gp"
        )

    # ── Input ────────────────────────────────────────────────────────────────

    async def tap(self, x: int, y: int) -> None:
        """Tap alle coordinate (x, y) nella risoluzione 960x540."""
        await self._adb_run("shell", "input", "tap", str(x), str(y))

    async def swipe(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration_ms: int = 300,
    ) -> None:
        """Swipe da (x1,y1) a (x2,y2) con durata specificata."""
        await self._adb_run(
            "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(duration_ms)
        )

    async def keyevent(self, key: str) -> None:
        """
        Invia un keyevent Android.

        Args:
            key: nome del keycode (es. "KEYCODE_BACK", "KEYCODE_HOME")
                 oppure codice numerico come stringa (es. "4")
        """
        await self._adb_run("shell", "input", "keyevent", key)

    async def back(self) -> None:
        """Shortcut per KEYCODE_BACK."""
        await self.keyevent("KEYCODE_BACK")

    async def home(self) -> None:
        """Shortcut per KEYCODE_HOME."""
        await self.keyevent("KEYCODE_HOME")

    async def input_text(self, text: str) -> None:
        """
        Inserisce testo nel campo focalizzato.
        Escapa i caratteri speciali per la shell Android.
        """
        escaped = text.replace(" ", "%s").replace("'", "\\'")
        await self._adb_run("shell", "input", "text", escaped)

    # ── Screenshot ───────────────────────────────────────────────────────────

    async def screenshot(self) -> Screenshot:
        """
        Acquisisce uno screenshot direttamente in memoria.

        Usa `adb exec-out screencap -p` che ritorna PNG via stdout —
        nessun file temporaneo, nessun pull da /sdcard.

        Ritorna Screenshot con i dati dell'immagine.
        Lancia RuntimeError se l'acquisizione fallisce.
        """
        proc = await asyncio.create_subprocess_exec(
            self._adb_exe,
            "-s", self.adb_serial,
            "exec-out", "screencap", "-p",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        raw, err = await proc.communicate()

        if proc.returncode != 0 or not raw:
            raise RuntimeError(
                f"[{self.name}] screenshot fallito (rc={proc.returncode}): "
                f"{err.decode(errors='replace').strip()}"
            )

        return Screenshot.from_bytes(raw)

    # ── Helpers ADB interni ──────────────────────────────────────────────────

    async def _adb_run(self, *args: str) -> tuple[int, str, str]:
        """Esegue un comando ADB con il serial dell'istanza corrente."""
        return await self._adb_run_raw("-s", self.adb_serial, *args)

    async def _adb_run_raw(self, *args: str) -> tuple[int, str, str]:
        """Esegue adb.exe con gli argomenti dati. Ritorna (returncode, stdout, stderr)."""
        proc = await asyncio.create_subprocess_exec(
            self._adb_exe, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout_b.decode(errors="replace"),
            stderr_b.decode(errors="replace"),
        )

    async def _manager_run(self, *args: str) -> tuple[int, str, str]:
        """Esegue MuMuManager.exe con gli argomenti dati."""
        proc = await asyncio.create_subprocess_exec(
            self._mgr_exe, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout_b.decode(errors="replace"),
            stderr_b.decode(errors="replace"),
        )

    def __repr__(self) -> str:
        return f"MuMuDevice(name={self.name!r}, index={self.index}, port={self.port})"


# ==============================================================================
# FakeDevice — implementazione per test
# ==============================================================================

@dataclass
class TapCall:
    """Registra un singolo tap per asserzioni nei test."""
    x: int
    y: int


@dataclass
class SwipeCall:
    """Registra un singolo swipe per asserzioni nei test."""
    x1: int
    y1: int
    x2: int
    y2: int
    duration_ms: int


@dataclass
class KeyCall:
    """Registra un singolo keyevent per asserzioni nei test."""
    key: str


class FakeDevice:
    """
    Device fittizio per test — non comunica con nessun emulatore.

    Riceve una sequenza di Screenshot da restituire in ordine alle chiamate
    a screenshot(). Registra tutte le interazioni (tap, swipe, keyevent)
    per permettere asserzioni nei test.

    Esempio:
        device = FakeDevice(screenshots=[
            Screenshot.from_file("fixtures/home.png"),
            Screenshot.from_file("fixtures/boost_open.png"),
        ])
        # ... esegui task ...
        assert device.tap_calls[0] == TapCall(142, 47)
        assert len(device.screenshots_consumed) == 2
    """

    def __init__(
        self,
        screenshots: list[Screenshot] | None = None,
        name: str = "FAKE_00",
        index: int = 0,
    ):
        self.name    = name
        self.index   = index
        self.port    = 16384 + index * 32

        self._screenshots: list[Screenshot] = screenshots or []
        self._screen_idx: int = 0

        # Registro interazioni — ispezionabile nei test
        self.tap_calls:    list[TapCall]   = []
        self.swipe_calls:  list[SwipeCall] = []
        self.key_calls:    list[KeyCall]   = []
        self.text_inputs:  list[str]       = []
        self.screenshots_consumed: list[Screenshot] = []

        # Stato simulato
        self.launched:  bool = False
        self.game_running: bool = True

    # ── Ciclo vita ───────────────────────────────────────────────────────────

    async def launch(self) -> bool:
        self.launched = True
        return True

    async def shutdown(self) -> None:
        self.launched = False

    async def wait_ready(self, timeout: int = 120, poll_interval: float = 5.0) -> bool:
        return True

    async def connect_adb(self) -> bool:
        return True

    async def is_running(self) -> bool:
        return self.game_running

    async def start_game(self) -> None:
        self.game_running = True

    async def stop_game(self) -> None:
        self.game_running = False

    # ── Input ────────────────────────────────────────────────────────────────

    async def tap(self, x: int, y: int) -> None:
        self.tap_calls.append(TapCall(x, y))

    async def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> None:
        self.swipe_calls.append(SwipeCall(x1, y1, x2, y2, duration_ms))

    async def keyevent(self, key: str) -> None:
        self.key_calls.append(KeyCall(key))

    async def back(self) -> None:
        await self.keyevent("KEYCODE_BACK")

    async def home(self) -> None:
        await self.keyevent("KEYCODE_HOME")

    async def input_text(self, text: str) -> None:
        self.text_inputs.append(text)

    # ── Screenshot ───────────────────────────────────────────────────────────

    async def screenshot(self) -> Screenshot:
        """
        Restituisce il prossimo Screenshot dalla sequenza precaricata.
        Lancia IndexError se la sequenza è esaurita (segnale che il test
        non ha fornito abbastanza fixture).
        """
        if self._screen_idx >= len(self._screenshots):
            raise IndexError(
                f"FakeDevice '{self.name}': screenshot #{self._screen_idx} richiesto "
                f"ma la sequenza ha solo {len(self._screenshots)} elementi. "
                f"Aggiungere altri fixture al test."
            )
        shot = self._screenshots[self._screen_idx]
        self._screenshots_consumed_append(shot)
        self._screen_idx += 1
        return shot

    def _screenshots_consumed_append(self, s: Screenshot) -> None:
        self.screenshots_consumed.append(s)

    # ── Utility per test ─────────────────────────────────────────────────────

    def add_screenshot(self, s: Screenshot) -> None:
        """Aggiunge uno screenshot alla coda durante il test."""
        self._screenshots.append(s)

    def reset(self) -> None:
        """Azzera il registro interazioni e l'indice screenshot."""
        self.tap_calls.clear()
        self.swipe_calls.clear()
        self.key_calls.clear()
        self.text_inputs.clear()
        self.screenshots_consumed.clear()
        self._screen_idx = 0

    @property
    def all_keys(self) -> list[str]:
        """Lista di tutti i keyevent inviati — comodo per asserzioni."""
        return [k.key for k in self.key_calls]

    @property
    def back_count(self) -> int:
        """Numero di KEYCODE_BACK inviati."""
        return sum(1 for k in self.key_calls if k.key == "KEYCODE_BACK")

    def __repr__(self) -> str:
        return (
            f"FakeDevice(name={self.name!r}, "
            f"screenshots={len(self._screenshots)}, "
            f"consumed={self._screen_idx})"
        )
