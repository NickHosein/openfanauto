"""Parse Unraid's /var/local/emhttp/disks.ini for drive temperatures."""

import os
import configparser
from base_logger import logger


class DisksIniParser:
    """Reads temperatures from Unraid disks.ini.

    Skips entries with non-numeric temp values (``*``, ``?``, empty string) —
    these represent unassigned or spun-down drives with no temperature data.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.sensors: dict[str, float] = {}
        self._parse()

    def _parse(self) -> None:
        if not os.path.exists(self.file_path):
            logger.warning("Disks ini file not found: %s", self.file_path)
            return

        cfg = configparser.ConfigParser()
        cfg.read(self.file_path)

        count = 0
        for section in cfg.sections():
            try:
                raw = cfg[section].get("temp", "").strip('"').strip()
                if not raw or raw in ("*", "?"):
                    continue
                temp = float(raw)
                name = section.strip('"')
                self.sensors[name] = temp
                count += 1
            except (ValueError, TypeError):
                continue

        if count:
            logger.info("Parsed %d sensors from disks.ini", count)
        else:
            logger.warning("No valid temperature sensors found in disks.ini")

    def get_temperature(self, sensor_name: str) -> float:
        return self.sensors.get(sensor_name, -1.0)

    def list_sensors(self) -> list[str]:
        return list(self.sensors.keys())