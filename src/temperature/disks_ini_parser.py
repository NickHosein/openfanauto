import os
import configparser
from base_logger import logger

class DisksIniParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self.sensors = {}
        self._parse()

    def _parse(self):
        if not os.path.exists(self.file_path):
            logger.warning(f"Disks ini file not found: {self.file_path}")
            return

        try:
            cfg = configparser.ConfigParser()
            cfg.read(self.file_path)
            for section in cfg.sections():
                temp = cfg[section].get('temp', '-1').replace('"', '')
                sensor = section.replace('"', '')
                self.sensors[sensor] = float(temp)
            logger.debug(f"Parsed disks.ini: {len(self.sensors)} sensors found")
        except Exception as e:
            logger.error(f"Error parsing disks.ini: {e}")

    def get_temperature(self, sensor_name):
        return self.sensors.get(sensor_name, -1.0)

    def list_sensors(self):
        return list(self.sensors.keys())