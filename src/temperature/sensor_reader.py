"""SensorReader — merges temperatures from disks.ini (priority) and smartctl (fallback)."""

from __future__ import annotations

from temperature.disks_ini_parser import DisksIniParser
from temperature.smartctl_parser import SmartCtlParser
from base_logger import logger


class SensorReader:
    """Reads drive temperatures from Unraid sources.

    *disks.ini* is the primary source (fast, no disk spin-up).
    *smartctl* provides fallback data for drives not in disks.ini (NVMe, unassigned).

    On conflicts, disks.ini wins.
    """

    def __init__(
        self,
        disks_ini_path: str | None = None,
        smartctl_devices: list[str] | None = None,
    ) -> None:
        self._disks_parser: DisksIniParser | None = None
        self._smartctl_parser: SmartCtlParser | None = None
        self._smartctl_devices: list[str] = smartctl_devices or []

        if disks_ini_path:
            try:
                self._disks_parser = DisksIniParser(disks_ini_path)
            except Exception:
                logger.exception("Failed to initialise DisksIniParser")

        if self._smartctl_devices:
            self._smartctl_parser = SmartCtlParser()

    # ------------------------------------------------------------------
    def read_all_temperatures(self) -> dict[str, float]:
        """Return ``{sensor_name: temp_c}`` from all available sources.

        disks.ini values take priority over smartctl for the same device.
        """
        results: dict[str, float] = {}

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