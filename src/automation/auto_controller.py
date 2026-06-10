"""AutoController — periodically reads temperatures and adjusts fans in auto mode."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from automation.fan_curves import FanCurveCalculator
from base_logger import logger

if TYPE_CHECKING:
    from config_manager import ConfigManager
    from fan_commander import FanCommander
    from temperature.sensor_reader import SensorReader


class AutoController:
    """Evaluates fan curves against current temperatures and pushes new
    speeds to fans whose mode is ``"auto"`` (per-fan control).

    Driven by a Tornado ``PeriodicCallback`` started from ``main.py``.
    """

    def __init__(
        self,
        commander: FanCommander,
        config_manager: ConfigManager,
        sensor_reader: SensorReader,
    ) -> None:
        self._commander = commander
        self._config = config_manager
        self._sensors = sensor_reader
        self._curve = FanCurveCalculator()
        self._running = False

    # ------------------------------------------------------------------
    def tick(self) -> None:
        """Single evaluation cycle — called by PeriodicCallback."""
        if not self._running:
            return

        try:
            temps = self._sensors.read_all_temperatures()
            if not temps:
                return

            fan_controls = self._config.get("fan_controls", {})
            profiles = self._config.get("fan_profiles", {})

            for fan_id_str, control in fan_controls.items():
                try:
                    fan_idx = int(fan_id_str)
                except ValueError:
                    continue

                # Skip fans not in auto mode
                state = self._commander.get_fan_state(fan_idx)
                if state and state.get("mode") != "auto":
                    continue

                profile_name = control.get("AssignedProfile", "")
                profile = profiles.get(profile_name)
                if not profile:
                    logger.debug("Fan %d: profile %r not found", fan_idx, profile_name)
                    continue

                # Temperature aggregation
                temp_sources = profile.get("TempSource", [])
                if isinstance(temp_sources, str):
                    temp_sources = [temp_sources]
                # Filter out None temps (spun-down drives) and missing keys
                relevant = [temps[s] for s in temp_sources if s in temps and temps[s] is not None]
                if not relevant:
                    continue

                temp_group_eval = profile.get("TempGroupEval", "max").lower()
                if temp_group_eval == "min":
                    current_temp = min(relevant)
                else:
                    current_temp = max(relevant)

                curve_type = profile.get("CurveType", "threshold")
                points = profile.get("Points", {})

                new_value = self._curve.calculate(curve_type, points, current_temp)

                if profile.get("UsePWM", False):
                    self._commander.set_fan_pwm(fan_idx, new_value)
                else:
                    self._commander.set_fan_rpm(fan_idx, new_value)

                logger.debug(
                    "Auto: fan %d → %d (temp=%.1f °C, profile=%s)",
                    fan_idx,
                    new_value,
                    current_temp,
                    profile_name,
                )

        except Exception:
            logger.exception("AutoController tick failed")

    # ------------------------------------------------------------------
    def start(self) -> None:
        self._running = True
        logger.info("AutoController started")

    def stop(self) -> None:
        self._running = False
        logger.info("AutoController stopped")