"""ConfigManager — loads, caches, and hot-reloads YAML configuration."""

from __future__ import annotations

import os
from copy import deepcopy

import yaml

from base_logger import logger


class ConfigManager:
    """Loads config from a YAML file and provides dot-notation access.

    Usage:
        cm = ConfigManager("config/config.yaml")
        port = cm.get("server.port", 3211)
        profiles = cm.get("fan_profiles", {})
    """

    def __init__(self, config_path: str) -> None:
        self._path = config_path
        self._data: dict = {}
        self.load()

    # ------------------------------------------------------------------
    def load(self) -> bool:
        """(Re)load configuration from disk. Returns *True* on success."""
        if not os.path.exists(self._path):
            logger.warning("Config file %s not found — using empty defaults", self._path)
            self._data = {}
            return False

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
    def save(self) -> bool:
        """Write current config back to disk."""
        try:
            with open(self._path, "w", encoding="utf-8") as fh:
                yaml.dump(self._data, fh, default_flow_style=False)
            logger.info("Configuration saved to %s", self._path)
            return True
        except Exception:
            logger.exception("Error saving config to %s", self._path)
            return False