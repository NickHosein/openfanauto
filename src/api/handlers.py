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
        """Add or update a fan profile.  Persists to in-memory config immediately."""
        profile_name = self.get_argument("name", None)
        curve_type = self.get_argument("type", "threshold")
        points_raw = self.get_argument("points", "{}")
        temp_source = self.get_argument("tempsource", "")
        use_pwm = self.get_argument("usepwm", "false").lower() == "true"

        if not profile_name:
            return self.write_fail("Profile name required")

        import json

        try:
            points = json.loads(points_raw)
        except json.JSONDecodeError:
            return self.write_fail('Points must be valid JSON (e.g. {"30": 20, "50": 80})')

        sources = [s.strip() for s in temp_source.split(",") if s.strip()]

        self.config.set(
            f"fan_profiles.{profile_name}",
            {
                "CurveType": curve_type,
                "TempSource": sources,
                "UsePWM": use_pwm,
                "Points": {str(k): int(v) for k, v in points.items()},
            },
        )
        self.write_ok(f"Profile '{profile_name}' saved.")


class ProfileRemoveHandler(BaseHandler):
    def get(self) -> None:
        name = self.get_argument("name", None)
        if not name:
            return self.write_fail("Profile name required")
        if not self.config.get(f"fan_profiles.{name}"):
            return self.write_fail(f"Profile '{name}' not found")
        # Remove the profile from fan_controls and switch affected fans to manual
        controls = self.config.get("fan_controls", {})
        fans_switched = 0
        for fan_id_str, ctrl in list(controls.items()):
            if ctrl.get("AssignedProfile") == name:
                self.config.set(f"fan_controls.{fan_id_str}.AssignedProfile", "")
                try:
                    self.commander.set_fan_mode(int(fan_id_str), "manual")
                    fans_switched += 1
                except (ValueError, TypeError):
                    pass
        self.config.delete(f"fan_profiles.{name}")
        detail = f" ({fans_switched} fan(s) switched to manual)" if fans_switched else ""
        self.write_ok(f"Profile '{name}' removed{detail}.")


class ControlAssignHandler(BaseHandler):
    """Assign a profile to a specific fan (or clear the assignment)."""

    def post(self) -> None:
        fan_id = self.get_argument("fan", None)
        profile = self.get_argument("profile", "")
        if fan_id is None:
            return self.write_fail("Fan ID required")
        idx = self._fan_idx(fan_id)
        if idx is None:
            return self.write_fail(f"Invalid fan index: {fan_id}")
        # If a profile name is provided, validate it exists
        if profile and not self.config.get(f"fan_profiles.{profile}"):
            return self.write_fail(f"Profile '{profile}' not found")
        self.config.set(f"fan_controls.{idx}.AssignedProfile", profile)
        if profile:
            self.commander.set_fan_mode(idx, "auto")
            self.write_ok(f"Fan #{idx + 1} assigned to profile '{profile}' (mode → auto)")
        else:
            self.commander.set_fan_mode(idx, "manual")
            self.write_ok(f"Fan #{idx + 1} unassigned (mode → manual)")


class ConfigUpdateHandler(BaseHandler):
    """Update arbitrary config keys via POST with JSON body."""

    def post(self) -> None:
        import json
        try:
            body = json.loads(self.request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.write_fail("Request body must be valid JSON")
        if not isinstance(body, dict):
            return self.write_fail("Request body must be a JSON object")
        for key, value in body.items():
            self.config.set(key, value)
        self.write_ok(f"{len(body)} config key(s) updated.  Click 'Save' to persist.")


class ConfigSaveHandler(BaseHandler):
    def get(self) -> None:
        ok = self.config.save()
        if ok:
            self.write_ok("Configuration saved")
        else:
            self.write_fail("Failed to save configuration")


class ConfigReloadHandler(BaseHandler):
    def get(self) -> None:
        ok = self.config.reload()
        if ok:
            self.write_ok("Configuration reloaded from disk")
        else:
            self.write_fail("Failed to reload configuration")


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------


class SensorsHandler(BaseHandler):
    def get(self) -> None:
        temps = {}
        disk_ids = {}
        if self.auto_controller is not None:
            sensors = self.auto_controller._sensors  # noqa: SLF001
            try:
                # Return cached temperatures only — never trigger a blocking
                # smartctl read from the web handler.  The automation tick
                # refreshes the cache on its own schedule.
                if sensors._cached:  # noqa: SLF001
                    temps = sensors._cached.copy()  # noqa: SLF001
            except Exception:
                logger.exception("Sensor read failed")
            # Also expose disk serial suffixes for the UI
            parser = getattr(sensors, "_disks_parser", None)  # noqa: SLF001
            if parser and hasattr(parser, "disk_ids"):
                disk_ids = parser.disk_ids
        self.write_ok(data={"temperatures": temps, "disk_ids": disk_ids})


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