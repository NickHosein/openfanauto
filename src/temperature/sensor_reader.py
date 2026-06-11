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

    Results are cached for 30 seconds to avoid running expensive ``smartctl``
    subprocess calls on every 2-second poll cycle.

    **Thread safety**: Blocking I/O (smartctl subprocess) is wrapped in a
    background thread with a 10 s timeout so Tornado's event loop is never
    blocked.

    On conflicts, disks.ini wins.
    """

    _CACHE_TTL = 30  # seconds
    _READ_TIMEOUT = 10  # seconds — max time to wait for smartctl + parsing

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

        if disks_ini_path:
            try:
                self._disks_parser = DisksIniParser(disks_ini_path)
            except Exception:
                logger.exception("Failed to initialise DisksIniParser")

        if self._smartctl_devices:
            self._smartctl_parser = SmartCtlParser()

    # ------------------------------------------------------------------
    def _do_read(self) -> dict[str, float | None]:
        """Perform the actual blocking read (called in a background thread)."""
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
    def read_all_temperatures(self) -> dict[str, float | None]:
        """Return ``{sensor_name: temp_c}`` from all available sources.

        Results are cached for *CACHE_TTL* seconds; calling this method
        more frequently returns the same value without re-running smartctl
        or re-reading disks.ini.

        The underlying blocking I/O (smartctl subprocess) runs in a
        background thread with a *READ_TIMEOUT* second cap.  If the
        thread doesn't finish in time, the previous cached value (or
        an empty dict on first call) is returned, keeping Tornado's
        event loop responsive.
        """
        now = time.time()
        if self._cache_time and (now - self._cache_time) < self._CACHE_TTL:
            return self._cached.copy()

        # Run the blocking read in a background thread so the Tornado
        # event loop is never blocked by a hung smartctl subprocess.
        result_container: list[dict[str, float | None]] = []

        def _target() -> None:
            result_container.append(self._do_read())

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=self._READ_TIMEOUT)

        if thread.is_alive():
            logger.warning(
                "Sensor read exceeded %d s timeout — returning cached data (%d keys)",
                self._READ_TIMEOUT,
                len(self._cached),
            )
            return self._cached.copy() if self._cached else {}

        results = result_container[0]
        self._cached = results
        self._cache_time = now
        return results.copy()
