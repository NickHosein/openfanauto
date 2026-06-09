"""Read drive temperatures by shelling out to smartctl (fallback for NVMe etc.)."""

from __future__ import annotations

import re
import subprocess

from base_logger import logger

# smartctl output patterns observed across SATA, SAS, NVMe drives
_TEMP_RE = re.compile(r"(?:Temperature|Temperature Sensor \d+)\s*[:]\s*(\d+)\s*(?:C(?:elsius)?)", re.IGNORECASE)


class SmartCtlParser:
    """Wraps the ``smartctl`` CLI tool to extract drive temperatures.

    Args:
        smartctl_path: Path (or name) of the smartctl binary.
    """

    def __init__(self, smartctl_path: str = "smartctl") -> None:
        self._smartctl = smartctl_path

    # ------------------------------------------------------------------
    def get_temperature(self, device_path: str, timeout: int = 10) -> float | None:
        """Return the temperature in °C for *device_path*, or *None* on failure."""
        try:
            result = subprocess.run(
                [self._smartctl, "-a", device_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            logger.error("smartctl binary not found – install smartmontools")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("smartctl timed out for %s after %ds", device_path, timeout)
            return None
        except OSError as exc:
            logger.error("smartctl OS error for %s: %s", device_path, exc)
            return None

        if result.returncode != 0:
            logger.debug("smartctl non-zero exit for %s (rc=%d)", device_path, result.returncode)
            # Non-zero doesn't always mean no temp data — try parsing anyway.

        for line in result.stdout.splitlines():
            m = _TEMP_RE.search(line)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass

        logger.debug("No temperature found in smartctl output for %s", device_path)
        return None

    # ------------------------------------------------------------------
    def get_all_temperatures(self, devices: list[str]) -> dict[str, float]:
        """Return ``{device_path: temp_c}`` for every readable device."""
        temps: dict[str, float] = {}
        for dev in devices:
            t = self.get_temperature(dev)
            if t is not None:
                temps[dev] = t
        return temps