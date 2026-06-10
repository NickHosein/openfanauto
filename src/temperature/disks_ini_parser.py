"""Parse Unraid's /var/local/emhttp/disks.ini for drive temperatures."""

import os
import configparser
from base_logger import logger


class DisksIniParser:
    """Reads temperatures from Unraid disks.ini.

    ``DISK_OK`` entries are always included — drives that are spun-down
    (``temp="*"``) get a ``None`` temperature so the UI can show them as
    "spun down" while keeping the sensor list stable.  Empty slots
    (``DISK_NP`` / ``DISK_NP_DSBL``) are excluded entirely.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.sensors: dict[str, float | None] = {}
        self.disk_ids: dict[str, str] = {}
        self._parse()

    def _parse(self) -> None:
        if not os.path.exists(self.file_path):
            logger.warning("Disks ini file not found: %s", self.file_path)
            return

        cfg = configparser.ConfigParser()
        cfg.read(self.file_path)

        active = 0
        spun_down = 0
        for section in cfg.sections():
            try:
                status = cfg[section].get("status", "").strip('"').strip()
                # Skip empty / disabled slots
                if status in ("DISK_NP", "DISK_NP_DSBL", ""):
                    continue

                raw = cfg[section].get("temp", "").strip('"').strip()
                name = section.strip('"')

                # Always capture the disk id suffix for identification
                disk_id = cfg[section].get("id", "").strip('"').strip()
                if disk_id:
                    self.disk_ids[name] = disk_id[-4:]

                if not raw or raw in ("*", "?"):
                    # Drive present but temperature unavailable (spun-down, USB, etc.)
                    self.sensors[name] = None
                    spun_down += 1
                    continue

                temp = float(raw)
                self.sensors[name] = temp
                active += 1
            except (ValueError, TypeError):
                continue

        if active or spun_down:
            logger.info(
                "Parsed %d sensors from disks.ini (%d active, %d no-temp)",
                active + spun_down,
                active,
                spun_down,
            )
        else:
            logger.warning("No disk entries found in disks.ini")

    def get_temperature(self, sensor_name: str) -> float | None:
        return self.sensors.get(sensor_name, -1.0)

    def list_sensors(self) -> list[str]:
        return list(self.sensors.keys())
