"""ConfigManager — loads, caches, hot-reloads, and saves YAML configuration."""

from __future__ import annotations

import os
import shutil
import threading
from copy import deepcopy

import yaml

from base_logger import logger


# Default config written when no file exists
_DEFAULT_CONFIG = {
    "server": {
        "hostname": "localhost",
        "port": 3211,
    },
    "hardware": {
        "port": None,
        "debug_uart": False,
    },
    "automation": {
        "enabled": False,
        "poll_interval": 10,
    },
    "paths": {
        "disks_ini": "/var/local/emhttp/disks.ini",
    },
    "smartctl_devices": [],
    "fan_profiles": {},
    "fan_controls": {},
}


class ConfigManager:
    """Loads config from a YAML file and provides dot-notation access.

    Usage:
        cm = ConfigManager("config/config.yaml")
        port = cm.get("server.port", 3211)
        cm.set("automation.poll_interval", 15)
        cm.save()
    """

    def __init__(self, config_path: str) -> None:
        self._path = config_path
        self._data: dict = {}
        self._lock = threading.Lock()
        self.load()

    # ------------------------------------------------------------------
    # Load / Reload
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """(Re)load configuration from disk.  Creates default if missing."""
        if not os.path.exists(self._path):
            logger.warning("Config file %s not found — creating default", self._path)
            self._data = deepcopy(_DEFAULT_CONFIG)
            self.save()
            return True

        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                loaded = yaml.safe_load(fh) or {}
            self._data = loaded
            logger.info("Loaded configuration from %s", self._path)
            return True
        except Exception:
            logger.exception("Error loading config from %s", self._path)
            return False

    def reload(self) -> bool:
        """Hot-reload config (used with live-reload env var)."""
        return self.load()

    # ------------------------------------------------------------------
    # Read access
    # ------------------------------------------------------------------

    def get(self, key: str, default=None):
        """Return a config value using dot-notation (e.g. ``"server.port"``)."""
        parts = key.split(".")
        node = self._data
        try:
            for p in parts:
                node = node[p]
            return deepcopy(node) if isinstance(node, (dict, list)) else node
        except (KeyError, TypeError, IndexError):
            return default

    def all(self) -> dict:
        """Return a deep copy of the entire config dict."""
        return deepcopy(self._data)

    # ------------------------------------------------------------------
    # Write access (in-memory — call save() to persist)
    # ------------------------------------------------------------------

    def set(self, key: str, value) -> bool:
        """Set a config value using dot-notation and return *True* on success.

        Example: ``cm.set("fan_profiles.Quiet.Points.30", 50)``

        Intermediate dicts are created automatically if they don't exist.
        """
        parts = key.split(".")
        if not parts:
            return False
        node = self._data
        try:
            for p in parts[:-1]:
                if p not in node or not isinstance(node[p], dict):
                    node[p] = {}
                node = node[p]
            node[parts[-1]] = value
            return True
        except Exception:
            logger.exception("Error setting config key %s", key)
            return False

    def delete(self, key: str) -> bool:
        """Delete a config key and return *True* on success."""
        parts = key.split(".")
        if not parts:
            return False
        node = self._data
        try:
            for p in parts[:-1]:
                node = node[p]
            if parts[-1] in node:
                del node[parts[-1]]
                return True
            return False
        except (KeyError, TypeError):
            return False

    # ------------------------------------------------------------------
    # Persist to disk
    # ------------------------------------------------------------------

    def save(self) -> bool:
        """Atomically write current config back to disk.

        Writes to a temp file then renames (atomic on Linux).
        Creates a ``.bak`` backup of the previous file on success.
        If the parent directory does not exist, it is created.
        """
        tmp_path = self._path + ".tmp"
        bak_path = self._path + ".bak"

        # Ensure parent directory exists
        parent = os.path.dirname(self._path)
        if parent and not os.path.isdir(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError:
                logger.exception("Cannot create config directory %s", parent)
                return False

        with self._lock:
            try:
                # 1. Write to temp file
                with open(tmp_path, "w", encoding="utf-8") as fh:
                    yaml.dump(self._data, fh, default_flow_style=False, allow_unicode=True)
                # 2. Backup current (if exists)
                if os.path.exists(self._path):
                    shutil.copy2(self._path, bak_path)
                # 3. Atomic rename
                os.replace(tmp_path, self._path)
                logger.info("Configuration saved to %s", self._path)
                return True
            except Exception:
                logger.exception("Error saving config to %s", self._path)
                # Clean up temp file
                try:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                except OSError:
                    pass
                return False