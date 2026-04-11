# ==============================================================================
#  DOOMSDAY ENGINE V6 - shared/template_matcher.py
#
#  Gestione centralizzata dei template PNG per il matching visivo.
#
#  Classi:
#    TemplateCache    — carica e cachea template da disco, thread-safe
#    TemplateMatcher  — esegue match su Screenshot con soglie configurabili
#
#  Funzioni:
#    get_matcher()    — factory globale (singleton per template_dir)
#
#  Design:
#    - I template PNG sono in una directory configurabile (default: templates/)
#    - Lazy loading: il file viene letto solo al primo utilizzo
#    - Cache in memoria: lo stesso template non viene riletto da disco
#    - TemplateMatcher wrappa Screenshot.match_template con logging opzionale
#    - Nessuna dipendenza da state.py o logger.py (opzionale tramite callback)
# ==============================================================================

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from core.device import MatchResult, Screenshot


# ==============================================================================
# TemplateCache — carica e cachea template PNG da disco
# ==============================================================================

class TemplateCache:
    """
    Cache thread-safe di template PNG.

    I template vengono caricati da disco al primo accesso e tenuti in memoria
    per tutta la durata del processo. Supporta sottocartelle:
        get("boost/btn_boost.png")
        get("pin/pin_home.png")
    """

    def __init__(self, template_dir: str | Path = "templates"):
        self._dir  = Path(template_dir)
        self._cache: dict[str, Screenshot] = {}
        self._lock  = threading.Lock()

    @property
    def template_dir(self) -> Path:
        return self._dir

    def get(self, name: str) -> Screenshot:
        """
        Ritorna il template come Screenshot.

        Args:
            name: percorso relativo alla template_dir (es. "pin_home.png")

        Raises:
            FileNotFoundError: se il file non esiste
            ValueError:        se il file non è un'immagine valida
        """
        with self._lock:
            if name not in self._cache:
                self._cache[name] = self._load(name)
            return self._cache[name]

    def _load(self, name: str) -> Screenshot:
        path = self._dir / name
        if not path.exists():
            raise FileNotFoundError(
                f"TemplateCache: template non trovato: {path}"
            )
        img = cv2.imread(str(path))
        if img is None:
            raise ValueError(
                f"TemplateCache: impossibile leggere immagine: {path}"
            )
        return Screenshot(img)

    def preload(self, names: list[str]) -> dict[str, Exception | None]:
        """
        Precarica una lista di template. Utile all'avvio del bot.

        Returns:
            dict {name: None} se ok, {name: Exception} se fallisce.
        """
        results: dict[str, Exception | None] = {}
        for name in names:
            try:
                self.get(name)
                results[name] = None
            except Exception as e:
                results[name] = e
        return results

    def invalidate(self, name: str) -> None:
        """Rimuove un template dalla cache (forza rilettura da disco)."""
        with self._lock:
            self._cache.pop(name, None)

    def clear(self) -> None:
        """Svuota tutta la cache."""
        with self._lock:
            self._cache.clear()

    def cached_names(self) -> list[str]:
        """Lista dei template attualmente in cache."""
        with self._lock:
            return list(self._cache.keys())

    def __repr__(self) -> str:
        return (
            f"TemplateCache(dir={self._dir}, "
            f"cached={len(self._cache)})"
        )


# ==============================================================================
# TemplateMatcher — esegue match con soglie e logging opzionale
# ==============================================================================

# Soglie default per categoria di template
DEFAULT_THRESHOLDS: dict[str, float] = {
    "pin":      0.80,   # pin mappa (pin_home, pin_oil_refinery, ...)
    "btn":      0.75,   # pulsanti UI
    "avatar":   0.75,   # avatar giocatore per rifornimento
    "store":    0.65,   # store / mercante (variabilità maggiore)
    "default":  0.75,
}


class TemplateMatcher:
    """
    Esegue template matching su Screenshot usando TemplateCache.

    Supporta:
      - match singolo (find_one)
      - match multiplo (find_all)
      - verifica presenza/assenza (exists / not_exists)
      - soglie per categoria di template
      - callback di log opzionale

    Esempio:
        matcher = TemplateMatcher(cache)
        result = matcher.find_one(screenshot, "pin/pin_home.png")
        if result.found:
            await device.tap(*result.coords)
    """

    def __init__(
        self,
        cache: TemplateCache,
        thresholds: dict[str, float] | None = None,
        log_callback: Callable[[str, str, float, bool], None] | None = None,
    ):
        """
        Args:
            cache:        TemplateCache da usare
            thresholds:   dict {categoria: soglia} — sovrascrive DEFAULT_THRESHOLDS
            log_callback: funzione opzionale chiamata dopo ogni match:
                          (template_name, result_str, score, found) → None
        """
        self._cache     = cache
        self._thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self._log       = log_callback

    def _threshold_for(self, name: str, override: float | None) -> float:
        """Determina la soglia da usare per un dato template."""
        if override is not None:
            return override
        # Cerca la categoria nel nome (es. "pin/pin_home.png" → categoria "pin")
        for category in self._thresholds:
            if category in name.lower():
                return self._thresholds[category]
        return self._thresholds["default"]

    # ── API principale ────────────────────────────────────────────────────────

    def find_one(
        self,
        screenshot: Screenshot,
        template_name: str,
        threshold: float | None = None,
        zone: tuple[int, int, int, int] | None = None,
    ) -> MatchResult:
        """
        Cerca il template nello screenshot.

        Args:
            screenshot:    Screenshot su cui cercare
            template_name: nome file template (relativo a template_dir)
            threshold:     soglia override (None = usa DEFAULT_THRESHOLDS)
            zone:          (x1, y1, x2, y2) zona di ricerca

        Returns:
            MatchResult(found, score, cx, cy)

        Raises:
            FileNotFoundError: se il template non esiste su disco
        """
        template = self._cache.get(template_name)
        thresh   = self._threshold_for(template_name, threshold)
        result   = screenshot.match_template(template, threshold=thresh, zone=zone)

        if self._log:
            self._log(template_name, "find_one", result.score, result.found)

        return result

    def find_all(
        self,
        screenshot: Screenshot,
        template_name: str,
        threshold: float | None = None,
        zone: tuple[int, int, int, int] | None = None,
        cluster_px: int = 20,
    ) -> list[MatchResult]:
        """
        Trova tutte le occorrenze del template (es. più pulsanti identici).

        Returns:
            Lista di MatchResult ordinata per score decrescente.
        """
        template = self._cache.get(template_name)
        thresh   = self._threshold_for(template_name, threshold)
        results  = screenshot.match_template_all(
            template, threshold=thresh, zone=zone, cluster_px=cluster_px
        )

        if self._log and results:
            self._log(template_name, "find_all", results[0].score, True)

        return results

    def exists(
        self,
        screenshot: Screenshot,
        template_name: str,
        threshold: float | None = None,
        zone: tuple[int, int, int, int] | None = None,
    ) -> bool:
        """Ritorna True se il template è presente nello screenshot."""
        return self.find_one(screenshot, template_name, threshold, zone).found

    def not_exists(
        self,
        screenshot: Screenshot,
        template_name: str,
        threshold: float | None = None,
        zone: tuple[int, int, int, int] | None = None,
    ) -> bool:
        """Ritorna True se il template NON è presente (verifica assenza)."""
        return not self.exists(screenshot, template_name, threshold, zone)

    def find_first_of(
        self,
        screenshot: Screenshot,
        template_names: list[str],
        threshold: float | None = None,
        zone: tuple[int, int, int, int] | None = None,
    ) -> tuple[str | None, MatchResult]:
        """
        Cerca una lista di template e ritorna il primo trovato.

        Utile quando lo schermo può mostrare uno di N pulsanti alternativi
        (es. cerca "btn_ok.png" oppure "btn_conferma.png").

        Returns:
            (nome_template_trovato, MatchResult) oppure (None, MatchResult not found)
        """
        not_found = MatchResult(False, 0.0, 0, 0)
        for name in template_names:
            try:
                result = self.find_one(screenshot, name, threshold, zone)
                if result.found:
                    return name, result
            except FileNotFoundError:
                continue
        return None, not_found

    def score(
        self,
        screenshot: Screenshot,
        template_name: str,
        zone: tuple[int, int, int, int] | None = None,
    ) -> float:
        """
        Ritorna lo score grezzo del miglior match (0.0–1.0), ignorando la soglia.
        Utile per diagnostica e calibrazione delle soglie.
        """
        template = self._cache.get(template_name)
        # Usa soglia 0.0 per ottenere sempre il risultato
        result = screenshot.match_template(template, threshold=0.0, zone=zone)
        return result.score

    def __repr__(self) -> str:
        return f"TemplateMatcher(cache={self._cache!r})"


# ==============================================================================
# Registry globale
# ==============================================================================

_matchers: dict[str, TemplateMatcher] = {}
_matchers_lock = threading.Lock()


def get_matcher(
    template_dir: str | Path = "templates",
    thresholds: dict[str, float] | None = None,
    log_callback: Callable | None = None,
) -> TemplateMatcher:
    """
    Factory globale: un TemplateMatcher (con relativa cache) per template_dir.

    Se chiamato più volte con la stessa directory, ritorna la stessa istanza
    (la cache rimane condivisa tra tutti i task che usano la stessa dir).
    """
    key = str(Path(template_dir).resolve())
    with _matchers_lock:
        if key not in _matchers:
            cache = TemplateCache(template_dir)
            _matchers[key] = TemplateMatcher(
                cache,
                thresholds=thresholds,
                log_callback=log_callback,
            )
        return _matchers[key]


def clear_matchers() -> None:
    """Svuota il registry globale (usato nei test)."""
    with _matchers_lock:
        for m in _matchers.values():
            m._cache.clear()
        _matchers.clear()
