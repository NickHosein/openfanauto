"""Tests for src/automation/auto_controller.py — None-temp filtering."""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestNoneTempFiltering:
    """Verify that auto_controller.tick() skips None temperatures."""

    @pytest.fixture
    def mock_deps(self):
        from automation.auto_controller import AutoController
        commander = MagicMock()
        config = MagicMock()
        sensors = MagicMock()
        return AutoController(commander, config, sensors), commander, config, sensors

    def test_none_temps_are_filtered_out(self, mock_deps):
        """Curve evaluation skips sources whose temp is None."""
        ctrl, commander, config, sensors = mock_deps
        ctrl._running = True

        # fan_controls: fan 0 assigned to "TestProfile"
        config.get.side_effect = lambda key, default=None: {
            "fan_controls": {"0": {"AssignedProfile": "TestProfile"}},
            "fan_profiles": {
                "TestProfile": {
                    "CurveType": "threshold",
                    "TempSource": ["disk1", "disk4"],
                    "TempGroupEval": "max",
                    "Points": {"30": 20, "50": 80},
                    "UsePWM": False,
                }
            },
        }.get(key, default)

        sensors.read_all_temperatures.return_value = {
            "disk1": 35.0,
            "disk4": None,  # spun-down
        }

        commander.get_fan_state.return_value = {"mode": "auto"}

        ctrl.tick()

        # Should have used only disk1 (35°C), not disk4 (None)
        # fan 0 in auto mode → called set_fan_rpm with the threshold value
        commander.set_fan_rpm.assert_called_once()
        # At 35°C with points {30: 20, 50: 80}, threshold curve gives 20
        commander.set_fan_rpm.assert_called_with(0, 20)

    def test_all_none_temps_skip_entirely(self, mock_deps):
        """When all relevant temps are None, the fan is skipped (no command sent)."""
        ctrl, commander, config, sensors = mock_deps
        ctrl._running = True

        config.get.side_effect = lambda key, default=None: {
            "fan_controls": {"0": {"AssignedProfile": "TestProfile"}},
            "fan_profiles": {
                "TestProfile": {
                    "CurveType": "threshold",
                    "TempSource": ["disk1"],
                    "Points": {"30": 20},
                    "UsePWM": False,
                }
            },
        }.get(key, default)

        sensors.read_all_temperatures.return_value = {"disk1": None}
        commander.get_fan_state.return_value = {"mode": "auto"}

        ctrl.tick()

        # Should NOT have sent any command — no valid temps
        commander.set_fan_rpm.assert_not_called()
        commander.set_fan_pwm.assert_not_called()

    def test_missing_temp_source_skipped(self, mock_deps):
        """Profile references a sensor not in the temps dict — skip it."""
        ctrl, commander, config, sensors = mock_deps
        ctrl._running = True

        config.get.side_effect = lambda key, default=None: {
            "fan_controls": {"0": {"AssignedProfile": "TestProfile"}},
            "fan_profiles": {
                "TestProfile": {
                    "CurveType": "threshold",
                    "TempSource": ["nonexistent_disk"],
                    "Points": {"30": 20},
                    "UsePWM": False,
                }
            },
        }.get(key, default)

        sensors.read_all_temperatures.return_value = {"disk1": 35.0}  # missing nonexistent_disk
        commander.get_fan_state.return_value = {"mode": "auto"}

        ctrl.tick()

        commander.set_fan_rpm.assert_not_called()

    def test_mixed_sources_uses_only_valid(self, mock_deps):
        """Temp sources with real + None + missing → uses only real ones."""
        ctrl, commander, config, sensors = mock_deps
        ctrl._running = True

        config.get.side_effect = lambda key, default=None: {
            "fan_controls": {"0": {"AssignedProfile": "TestProfile"}},
            "fan_profiles": {
                "TestProfile": {
                    "CurveType": "linear",
                    "TempSource": ["disk1", "disk2", "nonexistent"],
                    "TempGroupEval": "max",
                    "Points": {"30": 20, "60": 100},
                    "UsePWM": True,
                }
            },
        }.get(key, default)

        sensors.read_all_temperatures.return_value = {
            "disk1": 40.0,
            "disk2": None,
            # nonexistent absent
        }
        commander.get_fan_state.return_value = {"mode": "auto"}

        ctrl.tick()

        # Only disk1 (40°C) used; max(40) = 40
        # Linear interpolation between (30,20) and (60,100) at 40°C
        # value = 20 + (40-30)*(100-20)/(60-30) = 20 + 10*80/30 = 20 + 26.67 = 47
        commander.set_fan_pwm.assert_called_once_with(0, 47)

    def test_manual_mode_fan_skipped(self, mock_deps):
        """Fans in manual mode are not touched by auto_controller."""
        ctrl, commander, config, sensors = mock_deps
        ctrl._running = True

        config.get.side_effect = lambda key, default=None: {
            "fan_controls": {"0": {"AssignedProfile": "TestProfile"}},
            "fan_profiles": {
                "TestProfile": {
                    "CurveType": "threshold",
                    "TempSource": ["disk1"],
                    "Points": {"30": 20},
                    "UsePWM": False,
                }
            },
        }.get(key, default)

        sensors.read_all_temperatures.return_value = {"disk1": 35.0}
        commander.get_fan_state.return_value = {"mode": "manual"}

        ctrl.tick()

        commander.set_fan_rpm.assert_not_called()
        commander.set_fan_pwm.assert_not_called()

    def test_not_running_skips_tick(self, mock_deps):
        """When _running is False, tick() is a no-op."""
        ctrl, commander, config, sensors = mock_deps
        ctrl._running = False

        ctrl.tick()

        sensors.read_all_temperatures.assert_not_called()
        commander.set_fan_rpm.assert_not_called()

    def test_empty_temps_bails_early(self, mock_deps):
        """When read_all_temperatures returns empty dict, nothing happens."""
        ctrl, commander, config, sensors = mock_deps
        ctrl._running = True

        sensors.read_all_temperatures.return_value = {}

        ctrl.tick()

        commander.set_fan_rpm.assert_not_called()