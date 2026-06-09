"""Fan curve calculator — supports threshold and linear interpolation."""

from bisect import bisect_left


class FanCurveCalculator:
    """Calculates fan speed (PWM % or RPM) from a temperature value
    using a curve defined by {temperature: value} points."""

    @staticmethod
    def _numeric_points(points: dict) -> dict:
        """Convert all point keys/values to numeric, dropping unparseable entries."""
        numeric = {}
        for k, v in points.items():
            try:
                numeric[float(k)] = float(v)
            except (ValueError, TypeError):
                pass
        return numeric

    @staticmethod
    def calculate(curve_type: str, points: dict, temperature: float) -> int:
        """Return the fan value for *temperature* given a curve type and points.

        Args:
            curve_type: ``'threshold'`` or ``'linear'``.
            points: Dict of ``{temp: value}`` (values are PWM % or RPM).
            temperature: Current sensor temperature in °C.

        Returns:
            Calculated integer value, or 0 if no valid points exist.
        """
        numeric = FanCurveCalculator._numeric_points(points)
        if not numeric:
            return 0

        sorted_temps = sorted(numeric.keys())

        if curve_type == "threshold":
            return FanCurveCalculator._threshold(sorted_temps, numeric, temperature)
        elif curve_type == "linear":
            return FanCurveCalculator._linear(sorted_temps, numeric, temperature)
        else:
            return FanCurveCalculator._threshold(sorted_temps, numeric, temperature)

    @staticmethod
    def _threshold(sorted_temps: list, points: dict, temperature: float) -> int:
        """Highest threshold ≤ temperature wins; floor is 0."""
        value = 0
        for t in sorted_temps:
            if temperature >= t:
                value = int(points[t])
            else:
                break
        return value

    @staticmethod
    def _linear(sorted_temps: list, points: dict, temperature: float) -> int:
        """Linear interpolation between the two nearest points."""
        if temperature <= sorted_temps[0]:
            return int(points[sorted_temps[0]])
        if temperature >= sorted_temps[-1]:
            return int(points[sorted_temps[-1]])

        idx = bisect_left(sorted_temps, temperature)

        # bisect_left gives the insertion point; the interval is [idx-1, idx]
        t1, t2 = sorted_temps[idx - 1], sorted_temps[idx]
        v1, v2 = points[t1], points[t2]

        if t1 == t2:
            return int(v1)

        interp = v1 + ((temperature - t1) * (v2 - v1)) / (t2 - t1)
        return int(round(interp))