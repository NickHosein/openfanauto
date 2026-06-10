"""ConfigManager — SQLite-backed configuration with the same dot-notation API.

Replaces the previous YAML-based implementation.  Uses :class:`db.Database`
for ACID-compliant storage with WAL journal mode.

Usage (unchanged from before):
    cm = ConfigManager("config/openfan.db")
    port = cm.get("server.port", 3211)
    cm.set("automation.poll_interval", 15)
    cm.save()
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from base_logger import logger

# ---------------------------------------------------------------------------
# Default values (used once on first-run to bootstrap the DB)
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict[str, Any] = {
    "server": {"hostname": "localhost", "port": 3211},
    "hardware": {"port": None, "debug_uart": False},
    "automation": {"enabled": False, "poll_interval": 10},
    "paths": {"disks_ini": "/var/local/emhttp/disks.ini"},
    "smartctl_devices": [],
}

# Top-level keys that live directly in the ``config`` table (everything
# else is handled via the profiles / controls tables).
_SIMPLE_CONFIG_KEYS = frozenset(
    {"server", "hardware", "automation", "paths", "smartctl_devices"}
)


class ConfigManager:
    """Loads config from a SQLite database and provides dot-notation access.

    Usage:
        cm = ConfigManager("config/openfan.db")
        port = cm.get("server.port", 3211)
        cm.set("automation.poll_interval", 15)
        cm.save()
    """

    def __init__(self, config_path: str) -> None:
        # The path now points to a .db file, but we accept any path for
        # backward compatibility.  If given a .yaml we auto-convert to .db.
        self._path = self._resolve_db_path(config_path)

        # Deferred import to avoid circular deps at module level.
        from db import Database  # pylint: disable=import-outside-toplevel

        self._db = Database(self._path)

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_db_path(path: str) -> str:
        """Ensure we always use a ``.db`` path."""
        p = Path(path)
        if p.suffix in (".yaml", ".yml"):
            p = p.with_suffix(".db")
        return str(p)

    # ------------------------------------------------------------------
    # Load / Reload  (reload is now a no-op — SQLite is always current)
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """(Re)load configuration from database.  Creates defaults if missing."""
        # The Database constructor handles bootstrapping.
        logger.debug("Config loaded from %s", self._path)
        return True

    def reload(self) -> bool:
        """Hot-reload config (no-op — SQLite always reflects live data)."""
        logger.debug("config.reload() called — SQLite-backed; no-op")
        return True

    # ------------------------------------------------------------------
    # Read access
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:  # noqa: C901
        """Return a config value using dot-notation (e.g. ``"server.port"``).

        Simple config keys (server, hardware, automation, paths,
        smartctl_devices) are read from the ``config`` table.  Nested
        paths inside ``fan_profiles`` or ``fan_controls`` are resolved
        against those tables.
        """
        parts = key.split(".")
        root = parts[0]

        # ---- Simple top-level keys ----
        if root in _SIMPLE_CONFIG_KEYS:
            raw = self._db.get_config(root)
            if raw is None:
                return default
            # Walk into nested structure for keys like "server.port"
            node = raw
            for p in parts[1:]:
                if isinstance(node, dict):
                    node = node.get(p)
                elif isinstance(node, list):
                    try:
                        node = node[int(p)]
                    except (ValueError, IndexError):
                        return default
                else:
                    return default
            return node

        # ---- Fan profiles sub-key: fan_profiles.<name>.<field> ----
        if root == "fan_profiles":
            if len(parts) < 2:
                return self._db.get_profiles()
            profile_name = parts[1]
            profile = self._db.get_profile(profile_name)
            if profile is None:
                return default
            if len(parts) == 2:
                return profile
            # Walk into profile fields: fan_profiles.Quiet.Points.30
            node = profile
            for p in parts[2:]:
                if isinstance(node, dict):
                    node = node.get(p)
                    if node is None:
                        return default
                else:
                    return default
            return node

        # ---- Fan controls sub-key: fan_controls.<fan_id>.AssignedProfile ----
        if root == "fan_controls":
            controls = self._db.get_controls()
            if len(parts) == 1:
                return controls
            fan_id = parts[1]
            ctrl = controls.get(fan_id, {})
            if len(parts) == 2:
                return ctrl
            return ctrl.get(parts[2], default)

        # Unknown root
        return default

    def all(self) -> dict[str, Any]:
        """Return the entire config dict (profiles + controls included)."""
        return self._db.get_all_config()

    # ------------------------------------------------------------------
    # Write access (in-memory — call save() to persist)
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any) -> bool:
        """Set a config value using dot-notation and return *True* on success.

        Simple keys (server, hardware, etc.) are JSON-encoded into the
        ``config`` table.  Profile and control writes go through the
        dedicated tables.
        """
        parts = key.split(".")
        if not parts:
            return False
        root = parts[0]

        try:
            # ---- Top-level simple key ----
            if root in _SIMPLE_CONFIG_KEYS:
                if len(parts) == 1:
                    self._db.set_config(root, value)
                    return True
                # Nested set: read-modify-write the whole JSON blob
                current = self._db.get_config(root) or {}
                node = current
                for p in parts[1:-1]:
                    if p not in node or not isinstance(node[p], dict):
                        node[p] = {}
                    node = node[p]
                node[parts[-1]] = value
                self._db.set_config(root, current)
                return True

            # ---- Fan profile set ----
            if root == "fan_profiles":
                if len(parts) < 2:
                    return False
                profile_name = parts[1]

                if len(parts) == 2 and isinstance(value, dict):
                    # Full profile replace
                    self._db.save_profile(
                        name=profile_name,
                        curve_type=value.get("CurveType", "threshold"),
                        use_pwm=value.get("UsePWM", False),
                        temp_sources=value.get("TempSource", []),
                        points=value.get("Points", {}),
                        temp_group_eval=value.get("TempGroupEval", "max"),
                    )
                    return True

                # Setting a sub-field of a profile — get current, modify, save
                current = self._db.get_profile(profile_name) or {
                    "CurveType": "threshold",
                    "TempSource": [],
                    "UsePWM": False,
                    "Points": {},
                    "TempGroupEval": "max",
                }
                node = current
                for p in parts[2:-1]:
                    if p not in node or not isinstance(node[p], dict):
                        node[p] = {}
                    node = node[p]
                node[parts[-1]] = value

                self._db.save_profile(
                    name=profile_name,
                    curve_type=current.get("CurveType", "threshold"),
                    use_pwm=current.get("UsePWM", False),
                    temp_sources=current.get("TempSource", []),
                    points=current.get("Points", {}),
                    temp_group_eval=current.get("TempGroupEval", "max"),
                )
                return True

            # ---- Fan control set ----
            if root == "fan_controls":
                if len(parts) < 2:
                    return False
                fan_id = parts[1]
                if len(parts) == 2 and isinstance(value, dict):
                    # fan_controls.<fan_id> = {AssignedProfile: "..."}
                    self._db.assign_control(fan_id, value.get("AssignedProfile", ""))
                    return True
                if len(parts) == 3 and parts[2] == "AssignedProfile":
                    self._db.assign_control(fan_id, str(value))
                    return True
                return False

            return False
        except Exception:
            logger.exception("Error setting config key %s", key)
            return False

    def delete(self, key: str) -> bool:
        """Delete a config key and return *True* on success.

        For simple top-level keys this removes from the ``config`` table.
        For profile keys (``fan_profiles.<name>``) this calls delete_profile.
        For control keys (``fan_controls.<fan_id>``) this clears the assignment.
        """
        parts = key.split(".")
        if not parts:
            return False
        root = parts[0]

        try:
            if root in _SIMPLE_CONFIG_KEYS:
                if len(parts) == 1:
                    return self._db.delete_config(root)
                # Nested delete — read-modify-write
                current = self._db.get_config(root) or {}
                node = current
                for p in parts[1:-1]:
                    if not isinstance(node, dict) or p not in node:
                        return False
                    node = node[p]
                if isinstance(node, dict) and parts[-1] in node:
                    del node[parts[-1]]
                    self._db.set_config(root, current)
                    return True
                return False

            if root == "fan_profiles" and len(parts) == 2:
                return self._db.delete_profile(parts[1])

            if root == "fan_controls" and len(parts) == 2:
                self._db.clear_control(parts[1])
                return True

            return False
        except Exception:
            logger.exception("Error deleting config key %s", key)
            return False

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------

    def save(self) -> bool:
        """Persist config to disk (SQLite commits are automatic on write).

        This method exists for API backward compatibility; the database
        commits on every set/delete operation, so it always acts as
        a no-op success.
        """
        logger.debug("config.save() called — SQLite writes are auto-committed")
        return True