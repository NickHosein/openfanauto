"""Unit tests for fan_curves.py — threshold & linear interpolation."""

import sys
from pathlib import Path

# Ensure src/ is on the import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from automation.fan_curves import FanCurveCalculator as FCC


class TestThreshold:
    def test_basic(self):
        points = {"30": "20", "50": "80", "70": "100"}
        assert FCC.calculate("threshold", points, 25) == 0
        assert FCC.calculate("threshold", points, 30) == 20
        assert FCC.calculate("threshold", points, 55) == 80
        assert FCC.calculate("threshold", points, 70) == 100
        assert FCC.calculate("threshold", points, 99) == 100

    def test_numeric_keys(self):
        points = {30: 20, 50: 80, 70: 100}
        assert FCC.calculate("threshold", points, 55) == 80

    def test_empty(self):
        assert FCC.calculate("threshold", {}, 50) == 0

    def test_float_temperature(self):
        points = {"40": "50", "60": "90"}
        assert FCC.calculate("threshold", points, 45.7) == 50


class TestLinear:
    def test_mid_interpolation(self):
        # 30→20, 70→100 → at 50 should be halfway between 20 and 100 = 60
        points = {"30": 20, "70": 100}
        result = FCC.calculate("linear", points, 50)
        # Linear: y = 20 + ((50-30)*(100-20))/(70-30) = 20 + (20*80)/40 = 20 + 40 = 60
        assert result == 60

    def test_below_range(self):
        points = {"40": 50, "60": 90}
        assert FCC.calculate("linear", points, 20) == 50

    def test_above_range(self):
        points = {"40": 50, "60": 90}
        assert FCC.calculate("linear", points, 80) == 90

    def test_string_keys_sorted_numerically(self):
        """Verify that string keys like '100' sort numerically (after '30'), not lexicographically."""
        points = {"30": 20, "50": 60, "100": 100}
        # At 75 °C, the interval is 50→100 (not 100→something, which would happen with string sort).
        # Linear interpolation: 60 + (75-50)*(100-60)/(100-50) = 60 + 25*40/50 = 60 + 20 = 80
        result = FCC.calculate("linear", points, 75)
        expected = 80
        assert result == expected

    def test_two_points_exact(self):
        points = {"40": 0, "80": 100}
        assert FCC.calculate("linear", points, 40) == 0
        assert FCC.calculate("linear", points, 80) == 100

    def test_empty(self):
        assert FCC.calculate("linear", {}, 50) == 0


class TestUnknownCurveFallsback:
    def test_fallback(self):
        points = {"40": 50, "60": 90}
        # unknown curve type should fall back to threshold
        assert FCC.calculate("bogus", points, 65) == 90