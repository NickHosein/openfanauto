"""Tornado request handlers for the OpenFanAuto REST API."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import tornado.web

from base_logger import logger

if TYPE_CHECKING:
    from automation.auto_controller import AutoController
    from config_manager import ConfigManager
    from fan_commander import FanCommander

# ---------------------------------------------------------------------------
# Base handler — DRY response helpers + CORS
# ---------------------------------------------------------------------------


class BaseHandler(tornado.web.RequestHandler):
    """Shared helpers for all API handlers."""

    def initialize(
        self,
        commander: FanCommander,
        config: ConfigManager,
        auto_controller: AutoController | None = None,
    ) -> None:
        self.commander = commander
        self.config = config
        self.auto_controller = auto_controller

    def set_default_headers(self) -> None:
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.set_header("Content-Type", "application/json")

    def options(self, *_args, **_kwargs) -> None:
        self.set_status(204)
        self.finish()

    def write_ok(self, message: str = "", data=None) -> None:
        self.write({"status": "ok", "message": message, "data": data})

    def write_fail(self, message: str, data=None) -> None:
        self.write({"status": "fail", "message": message, "data": data})

    @staticmethod
    def _fan_idx(raw: str) -> int | None:
        """Validate & cast fan index; returns *None* on invalid input."""
        try:
            i = int(raw)
            return i if 0 <= i <= 9 else None
        except (ValueError, TypeError):
            return None


# ---------------------------------------------------------------------------
# Fan status / control
# ---------------------------------------------------------------------------


class FanStatusHandler(BaseHandler):
    def get(self) -> None:
        rpms = self.commander.get_all_fan_rpm()
        info = self.commander.get_all_fan_info()
        self.write_ok(data={"rpm": rpms, "fans": info})


class FanSetPWMHandler(BaseHandler):
    def get(self, fan_index: str) -> None:
        idx = self._fan_idx(fan_index)
        if idx is None:
            return self.write_fail(f"Invalid fan index: {fan_index}")
        value = min(100, max(0, int(float(self.get_argument("value", 0)))))
        ok = self.commander.set_fan_pwm(idx, value)
        if ok:
            self.write_ok(f"Fan #{idx + 1} set to {value}% PWM")
        else:
            self.write_fail("Failed to set PWM")


class FanSetRPMHandler(BaseHandler):
    def get(self, fan_index: str) -> None:
        idx = self._fan_idx(fan_index)
        if idx is None:
            return self.write_fail(f"Invalid fan index: {fan_index}")
        value = int(self.get_argument("value", 0))
        ok = self.commander.set_fan_rpm(idx, value)
        if ok:
            self.write_ok(f"Fan #{idx + 1} set to {value} RPM")
        else:
            self.write_fail("Failed to set RPM")


class FanSetAllPWMHandler(BaseHandler):
    def get(self) -> None:
        value = min(100, max(0, int(float(self.get_argument("value", 0)))))
        ok = self.commander.set_all_fan_pwm(value)
        if ok:
            self.write_ok(f"All fans set to {value}% PWM")
        else:
            self.write_fail("Failed to set all fan PWM")


class FanModeHandler(BaseHandler):
    def get(self, fan_index: str) -> None:
        idx = self._fan_idx(fan_index)
        if idx is None:
            return self.write_fail(f"Invalid fan index: {fan_index}")
        mode = self.get_argument("mode", "manual")
        if mode not in ("manual", "auto"):
            return self.write_fail("Mode must be 'manual' or 'auto'")
        ok = self.commander.set_fan_mode(idx, mode)
        if ok:
            self.write_ok(f"Fan #{idx + 1} mode → {mode}")
        else:
            self.write_fail("Failed to set mode")


# ---------------------------------------------------------------------------
# Fan aliases
# ---------------------------------------------------------------------------


class FanAliasAllHandler(BaseHandler):
    def get(self) -> None:
        info = self.commander.get_all_fan_info()
        aliases = {str(f["id"]): f["alias"] for f in info}
        self.write_ok(data=aliases)


class FanAliasGetHandler(BaseHandler):
    def get(self, fan_index: str) -> None:
        idx = self._fan_idx(fan_index)
        if idx is None:
            return self.write_fail(f"Invalid fan index: {fan_index}")
        state = self.commander.get_fan_state(idx)
        self.write_ok(data={"fan_id": idx, "alias": state.get("alias", "") if state else ""})


class FanAliasSetHandler(BaseHandler):
    def get(self, fan_index: str) -> None:
        idx = self._fan_idx(fan_index)
        if idx is None:
            return self.write_fail(f"Invalid fan index: {fan_index}")
        value = self.get_argument("value", "").strip()
        if not value:
            return self.write_fail("Alias cannot be empty")
        if re.search(r"^[a-z0-9\-_\.# ]*$", value, re.IGNORECASE) is None:
            return self.write_fail("Alias contains invalid characters")
        ok = self.commander.set_fan_alias(idx, value)
        if ok:
            self.write_ok(f"Fan #{idx + 1} alias → '{value}'")
        else:
            self.write_fail("Failed to set alias")


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


class ProfileListHandler(BaseHandler):
    def get(self) -> None:
        profiles = self.config.get("fan_profiles", {})
        controls = self.config.get("fan_controls", {})
        self.write_ok(data={"profiles": profiles, "controls": controls})


class ProfileSetHandler(BaseHandler):
    def get(self) -> None:
        name = self.get_argument("name", None)
        if not name:
            return self.write_fail("Profile name required")
        profiles = self.config.get("fan_profiles", {})
        if name not in profiles:
            return self.write_fail(f"Profile '{name}' not found")
        # Apply profile values to fans
        profile = profiles[name]
        profile_type = profile.get("CurveType", "threshold")
        points = profile.get("Points", {})
        msg_parts = []
        for fan_id_str, ctrl in self.config.get("fan_controls", {}).items():
            if ctrl.get("AssignedProfile") == name:
                try:
                    idx = int(fan_id_str)
                except ValueError:
                    continue
                # Set mode to auto so this fan is managed
                self.commander.set_fan_mode(idx, "auto")
                msg_parts.append(f"Fan #{idx + 1} → auto ({name})")
        self.write_ok(f"Profile '{name}' activated. " + "; ".join(msg_parts) if msg_parts else "No fans mapped.")


class ProfileAddHandler(BaseHandler):
    def post(self) -> None:
        profile_name = self.get_argument("name", None)
        curve_type = self.get_argument("type", "threshold")
        points_raw = self.get_argument("points", "{}")
        if not profile_name:
            return self.write_fail("Profile name required")
        import json

        try:
            points = json.loads(points_raw)
        except json.JSONDecodeError:
            return self.write_fail("Points must be valid JSON (e.g. {\"30\": 20, \"50\": 80})")
        data = self.config.all()
        if "fan_profiles" not in data:
            data["fan_profiles"] = {}
        data["fan_profiles"][profile_name] = {
            "CurveType": curve_type,
            "Points": {str(k): int(v) for k, v in points.items()},
        }
        # We don't directly write — we'll use save after modifying the in-memory copy
        self.write_ok(f"Profile '{profile_name}' added (use save endpoint to persist)")


class ProfileRemoveHandler(BaseHandler):
    def get(self) -> None:
        name = self.get_argument("name", None)
        if not name:
            return self.write_fail("Profile name required")
        data = self.config.all()
        profiles = data.get("fan_profiles", {})
        if name not in profiles:
            return self.write_fail(f"Profile '{name}' not found")
        del profiles[name]
        self.write_ok(f"Profile '{name}' removed")


class ConfigSaveHandler(BaseHandler):
    def get(self) -> None:
        ok = self.config.save()
        if ok:
            self.write_ok("Configuration saved")
        else:
            self.write_fail("Failed to save configuration")


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------


class SensorsHandler(BaseHandler):
    def get(self) -> None:
        if self.auto_controller is None:
            return self.write_fail("Automation controller not available")
        temps = self.auto_controller._sensors.read_all_temperatures()  # noqa: SLF001
        self.write_ok(data={"temperatures": temps})


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------


class InfoHandler(BaseHandler):
    def get(self) -> None:
        hw = self.commander.get_hw_info()
        fw = self.commander.get_fw_info()
        automation_enabled = self.config.get("automation.enabled", False)
        self.write_ok(
            data={
                "hardware": hw,
                "firmware": fw,
                "software": "OpenFanAuto v0.1.0",
                "automation": automation_enabled,
            }
        )


# ---------------------------------------------------------------------------
# Automation control
# ---------------------------------------------------------------------------


class AutomationHandler(BaseHandler):
    def get(self) -> None:
        """Get or toggle automation state."""
        action = self.get_argument("action", "status")
        if action == "status":
            state = "running" if (self.auto_controller and self.auto_controller._running) else "stopped"  # noqa: SLF001
            self.write_ok(data={"automation": state})
        elif action == "start" and self.auto_controller:
            self.auto_controller.start()
            self.write_ok("Automation started")
        elif action == "stop" and self.auto_controller:
            self.auto_controller.stop()
            self.write_ok("Automation stopped")
        else:
            self.write_fail(f"Unknown action: {action} (use status, start, stop)")


# ---------------------------------------------------------------------------
# Default 404
# ---------------------------------------------------------------------------


class Default404Handler(tornado.web.RequestHandler):
    def prepare(self) -> None:
        self.set_status(404)
        self.write({"status": "fail", "message": "API endpoint not found"})
        self.finish()