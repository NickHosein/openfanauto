"""SQLite database layer for OpenFanAuto — persistent configuration storage.

Uses WAL journal mode for safe concurrent reads/writes with Tornado's
async I/O loop + periodic automation ticks.  Replaces the previous
YAML-based ConfigManager with ACID-compliant storage.

Schema
------
config           — simple key → JSON-value pairs (server, hardware, etc.)
fan_profiles     — named profiles with curve settings
profile_sources  — temperature-source names for each profile (1:N)
profile_points   — (temperature, value) curve points for each profile (1:N)
fan_controls     — per-fan profile assignments
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from base_logger import logger

# ---------------------------------------------------------------------------
# Default values (replicated from the old ConfigManager for bootstrapping)
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict[str, Any] = {
    "server": {"hostname": "localhost", "port": 3211},
    "hardware": {"port": None, "debug_uart": False},
    "automation": {"enabled": False, "poll_interval": 10},
    "paths": {"disks_ini": "/var/local/emhttp/disks.ini"},
    "smartctl_devices": [],
}

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fan_profiles (
    name            TEXT PRIMARY KEY,
    curve_type      TEXT NOT NULL DEFAULT 'threshold',
    use_pwm         INTEGER NOT NULL DEFAULT 0,
    temp_group_eval TEXT NOT NULL DEFAULT 'max'
);

CREATE TABLE IF NOT EXISTS profile_sources (
    profile_name TEXT NOT NULL REFERENCES fan_profiles(name) ON DELETE CASCADE,
    source       TEXT NOT NULL,
    PRIMARY KEY (profile_name, source)
);

CREATE TABLE IF NOT EXISTS profile_points (
    profile_name TEXT NOT NULL REFERENCES fan_profiles(name) ON DELETE CASCADE,
    temperature  REAL NOT NULL,
    value        REAL NOT NULL,
    PRIMARY KEY (profile_name, temperature)
);

CREATE TABLE IF NOT EXISTS fan_controls (
    fan_id           TEXT PRIMARY KEY,
    assigned_profile TEXT NOT NULL DEFAULT ''
);
"""


class Database:
    """Thread-safe SQLite database for OpenFanAuto configuration."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)
        self._local = threading.local()
        self._lock = threading.Lock()

        # Create directory if needed
        parent = os.path.dirname(self._path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        # Initialise schema
        with self._get_conn() as conn:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()

        # Bootstrap default config if empty
        self._bootstrap_defaults()

    # ------------------------------------------------------------------
    # Connection management (thread-local + WAL)
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local connection, creating it on first access."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    @contextmanager
    def _tx(self):
        """Context manager that commits on success, rolls back on error."""
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def _bootstrap_defaults(self) -> None:
        """Write default config keys if the config table is empty."""
        with self._tx() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM config").fetchone()
            if row and row["cnt"] > 0:
                return
            for key, value in _DEFAULT_CONFIG.items():
                conn.execute(
                    "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )

    # ------------------------------------------------------------------
    # Config key-value (top-level categories)
    # ------------------------------------------------------------------

    def get_config(self, key: str, default: Any = None) -> Any:
        """Return a JSON-decoded config value, or *default* if missing."""
        conn = self._get_conn()
        row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return default

    def set_config(self, key: str, value: Any) -> None:
        """Upsert a JSON-encoded config key."""
        with self._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )

    def delete_config(self, key: str) -> bool:
        """Remove a config key.  Returns True if it existed."""
        with self._tx() as conn:
            cur = conn.execute("DELETE FROM config WHERE key = ?", (key,))
            return cur.rowcount > 0

    def get_all_config(self) -> dict[str, Any]:
        """Return the full config dict (all top-level keys + profiles + controls)."""
        conn = self._get_conn()
        result: dict[str, Any] = {}

        # Simple keys
        for row in conn.execute("SELECT key, value FROM config"):
            try:
                result[row["key"]] = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                result[row["key"]] = None

        # Fan profiles
        result["fan_profiles"] = self.get_profiles()

        # Fan controls
        result["fan_controls"] = self.get_controls()

        return result

    # ------------------------------------------------------------------
    # Fan profiles
    # ------------------------------------------------------------------

    def get_profiles(self) -> dict[str, dict[str, Any]]:
        """Return all fan profiles as {name: {CurveType, UsePWM, ...}}."""
        conn = self._get_conn()
        profiles: dict[str, dict[str, Any]] = {}

        for row in conn.execute("SELECT * FROM fan_profiles"):
            name = row["name"]
            # Load sources
            sources_rows = conn.execute(
                "SELECT source FROM profile_sources WHERE profile_name = ?", (name,)
            ).fetchall()
            # Load points
            points_rows = conn.execute(
                "SELECT temperature, value FROM profile_points WHERE profile_name = ? ORDER BY temperature",
                (name,),
            ).fetchall()

            points = {str(int(r["temperature"])): int(r["value"]) for r in points_rows}
            sources = [r["source"] for r in sources_rows]

            profiles[name] = {
                "CurveType": row["curve_type"],
                "TempSource": sources,
                "UsePWM": bool(row["use_pwm"]),
                "Points": points,
                "TempGroupEval": row["temp_group_eval"],
            }

        return profiles

    def get_profile(self, name: str) -> dict[str, Any] | None:
        """Return a single profile, or None."""
        profiles = self.get_profiles()
        return profiles.get(name)

    def save_profile(
        self,
        name: str,
        curve_type: str = "threshold",
        use_pwm: bool = False,
        temp_sources: list[str] | None = None,
        points: dict[str | int | float, int | float] | None = None,
        temp_group_eval: str = "max",
    ) -> None:
        """Insert or update a complete fan profile (replaces all associated rows)."""
        with self._tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO fan_profiles (name, curve_type, use_pwm, temp_group_eval)
                   VALUES (?, ?, ?, ?)""",
                (name, curve_type, int(use_pwm), temp_group_eval),
            )

            # Replace sources
            conn.execute("DELETE FROM profile_sources WHERE profile_name = ?", (name,))
            for src in (temp_sources or []):
                conn.execute(
                    "INSERT INTO profile_sources (profile_name, source) VALUES (?, ?)",
                    (name, src),
                )

            # Replace points
            conn.execute("DELETE FROM profile_points WHERE profile_name = ?", (name,))
            for temp, val in (points or {}).items():
                conn.execute(
                    "INSERT INTO profile_points (profile_name, temperature, value) VALUES (?, ?, ?)",
                    (name, float(temp), float(val)),
                )

    def delete_profile(self, name: str) -> bool:
        """Remove a profile and all associated rows.  Returns True if existed."""
        with self._tx() as conn:
            cur = conn.execute("DELETE FROM fan_profiles WHERE name = ?", (name,))
            if cur.rowcount == 0:
                return False
            # Clear assignments referencing this profile
            conn.execute(
                "UPDATE fan_controls SET assigned_profile = '' WHERE assigned_profile = ?",
                (name,),
            )
            return True

    # ------------------------------------------------------------------
    # Fan controls (profile assignments)
    # ------------------------------------------------------------------

    def get_controls(self) -> dict[str, dict[str, str]]:
        """Return {fan_id_str: {AssignedProfile: name}}."""
        conn = self._get_conn()
        controls: dict[str, dict[str, str]] = {}
        for row in conn.execute("SELECT fan_id, assigned_profile FROM fan_controls"):
            controls[row["fan_id"]] = {"AssignedProfile": row["assigned_profile"]}
        return controls

    def assign_control(self, fan_id: str, profile_name: str) -> None:
        """Assign a profile to a fan (empty string to clear)."""
        with self._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fan_controls (fan_id, assigned_profile) VALUES (?, ?)",
                (fan_id, profile_name),
            )

    def clear_control(self, fan_id: str) -> None:
        """Remove a fan assignment."""
        with self._tx() as conn:
            conn.execute("DELETE FROM fan_controls WHERE fan_id = ?", (fan_id,))

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close all thread-local connections."""
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None

    def vacuum(self) -> None:
        """Reclaim disk space after many writes."""
        self._get_conn().execute("VACUUM")