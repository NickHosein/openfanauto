"""SensorReader — merges temperatures from disks.ini (priority) and smartctl (fallback)."""

from __future__ import annotations

import threading
import time

from temperature.disks_ini_parser import DisksIniParser
from temperature.smartctl_parser import SmartCtlParser
from base_logger import logger


class SensorReader:
    """Reads drive temperatures from Unraid sources.

    *disks.ini* is the primary source (fast, no disk spin-up).
    *smartctl* provides fallback data for drives not in disks.ini (NVMe, unassigned).

    Uses a **stale-while-revalidate** cache: when the 30 s TTL expires,
    stale cached data is returned immediately while a background thread
    refreshes the cache.  This prevents Tornado's I/O loop from ever
    being blocked by a slow smartctl subprocess.

    The web-facing ``SensorsHandler`` reads ``self._cached`` directly
    for the same reason.

    On conflicts, disks.ini wins.
    """

    _CACHE_TTL = 30  # seconds

    def __init__(
        self,
        disks_ini_path: str | None = None,
        smartctl_devices: list[str] | None = None,
    ) -> None:
        self._disks_parser: DisksIniParser | None = None
        self._smartctl_parser: SmartCtlParser | None = None
        self._smartctl_devices: list[str] = smartctl_devices or []
        self._cache_time: float = 0.0
        self._cached: dict[str, float | None] = {}
        self._refresh_lock = threading.Lock()  # prevent concurrent background refreshes

        if disks_ini_path:
            try:
                self._disks_parser = DisksIniParser(disks_ini_path)
            except Exception:
                logger.exception("Failed to initialise DisksIniParser")

        if self._smartctl_devices:
            self._smartctl_parser = SmartCtlParser()

    # ------------------------------------------------------------------
    def _do_read(self) -> dict[str, float | None]:
        """Perform the actual blocking read (disks.ini + smartctl).

        This is the only method that should run blocking I/O.
        """
        results: dict[str, float | None] = {}

        # 1.  disks.ini (fast, primary source)
        if self._disks_parser:
            try:
                results.update(self._disks_parser.sensors)
            except Exception:
                logger.exception("Error reading disks.ini")

        # 2.  smartctl (fallback — fills in gaps)
        if self._smartctl_parser and self._smartctl_devices:
            try:
                extra = self._smartctl_parser.get_all_temperatures(self._smartctl_devices)
                for device, temp in extra.items():
                    results.setdefault(device, temp)
            except Exception:
                logger.exception("Error reading smartctl")

        return results

    # ------------------------------------------------------------------
    def _background_refresh(self) -> None:
        """Refresh the cache in a background thread (never blocks the I/O loop)."""
        try:
            results = self._do_read()
            self._cached = results
            self._cache_time = time.time()
            logger.debug("Background sensor refresh complete (%d entries)", len(results))
        except Exception:
            logger.exception("Background sensor refresh failed")

    # ------------------------------------------------------------------
    def read_all_temperatures(self) -> dict[str, float | None]:
        """Return ``{sensor_name: temp_c}`` from all available sources.

        - If cache is fresh (< ``_CACHE_TTL``) → return cached data instantly.
        - If cache is stale but has data → return stale data, fire
          a background refresh (non-blocking).
        - If cache is empty (first call) → block until data is available.

        Called by ``auto_controller.tick()`` on the Tornado PeriodicCallback.
        The web-facing ``SensorsHandler`` reads ``self._cached`` directly.
        """
        now = time.time()

        # Fresh cache — fast path
        if self._cache_time and (now - self._cache_time) < self._CACHE_TTL:
            return self._cached.copy()

        # Stale cache with existing data — return stale, refresh in background
        if self._cached:
            if self._refresh_lock.acquire(blocking=False):
                try:
                    logger.debug("Cache stale (%d s) — starting background refresh", int(now - self._cache_time))
                    threading.Thread(target=self._background_refresh, daemon=True).start()
                finally:
                    self._refresh_lock.release()
            return self._cached.copy()

        # First call ever — must block (no data to fall back on)
        logger.info("First sensor read — this may take a few seconds (smartctl)…")
        results = self._do_read()
        self._cached = results
        self._cache_time = now
        logger.info("Sensor read complete (%d entries)", len(results))
        return results.copy()