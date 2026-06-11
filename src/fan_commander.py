"""FanCommander — high-level fan control with state management.

Wraps either a real ``SerialHardware`` or ``MockSerialHardware`` backend.
"""

from __future__ import annotations

from typing import Protocol

from base_logger import logger


class HardwareBackend(Protocol):
    """Minimal interface a serial backend must satisfy."""

    def serial_transaction(self, payload: str, ignore_response: bool = False) -> list[str]: ...
    def open(self) -> None: ...
    def close(self) -> None: ...
    def is_open(self) -> bool: ...


class FanCommander:
    """Owns fan state (mode, alias, last value) and issues commands to hardware."""

    MAX_FANS = 10

    def __init__(self, backend: HardwareBackend) -> None:
        self._hw = backend
        self.fan_states: dict[int, dict] = {
            i: {"mode": "manual", "alias": f"Fan #{i + 1}", "profile": "", "value": 0}
            for i in range(self.MAX_FANS)
        }
        self.fan_rpm_cache: dict[int, int] = {}

    # -- hardware pass-through ---------------------------------------------

    def open(self) -> None:
        self._hw.open()

    def close(self) -> None:
        self._hw.close()

    def is_open(self) -> bool:
        return self._hw.is_open()

    # -- fan state ---------------------------------------------------------

    def set_fan_mode(self, fan_index, mode: str) -> bool:
        try:
            idx = int(fan_index)
            if 0 <= idx <= 9:
                self.fan_states[idx]["mode"] = mode
                logger.info("Fan #%d mode → %s", idx + 1, mode)
                return True
        except (ValueError, TypeError):
            pass
        return False

    def set_fan_alias(self, fan_index, alias: str) -> bool:
        try:
            idx = int(fan_index)
            if 0 <= idx <= 9:
                self.fan_states[idx]["alias"] = alias
                return True
        except (ValueError, TypeError):
            pass
        return False

    def get_fan_state(self, fan_index) -> dict | None:
        try:
            return self.fan_states[int(fan_index)]
        except (KeyError, ValueError, TypeError):
            return None

    def get_all_fan_info(self) -> list[dict]:
        return [{"id": i, **state} for i, state in self.fan_states.items()]

    # -- fan controls ------------------------------------------------------

    def set_fan_pwm(self, fan, pwm: int) -> bool:
        try:
            idx = int(fan)
            if not (0 <= idx <= 9):
                return False
            pwm_byte = int(float(pwm) * 255 / 100)
            res = self._tx(0x02, [idx, pwm_byte])
            if res:
                self.fan_states[idx]["value"] = int(float(pwm))
            return bool(res)
        except Exception:
            logger.exception("set_fan_pwm error")
            return False

    def set_fan_rpm(self, fan, rpm: int) -> bool:
        try:
            idx = int(fan)
            if not (0 <= idx <= 9):
                return False
            res = self._tx(0x04, [idx, (int(rpm) >> 8) & 0xFF, int(rpm) & 0xFF])
            if res:
                self.fan_states[idx]["value"] = int(rpm)
            return bool(res)
        except Exception:
            logger.exception("set_fan_rpm error")
            return False

    def set_all_fan_pwm(self, pwm: int) -> bool:
        try:
            pwm_byte = int(float(pwm) * 255 / 100)
            res = self._tx(0x03, pwm_byte)
            if res:
                for i in range(self.MAX_FANS):
                    self.fan_states[i]["value"] = int(float(pwm))
            return bool(res)
        except Exception:
            logger.exception("set_all_fan_pwm error")
            return False

    # -- read RPM ----------------------------------------------------------

    def get_all_fan_rpm(self) -> dict[int, int]:
        try:
            res = self._tx(0x00, None)
            return self._parse_rpm_response(res)
        except Exception:
            logger.exception("get_all_fan_rpm error")
            return {}

    def get_fan_rpm(self, fan_index: int) -> int:
        try:
            idx = int(fan_index)
            if not (0 <= idx <= 9):
                return 0
            res = self._tx(0x01, [idx])
            parsed = self._parse_rpm_response(res)
            return parsed.get(idx, 0)
        except Exception:
            logger.exception("get_fan_rpm error")
            return 0

    def _parse_rpm_response(self, response) -> dict[int, int]:
        if not response:
            return {}
        try:
            raw = str(response)
            parts = raw.split("|")
            if len(parts) < 2:
                return {}
            fans_str = parts[1].rstrip(";").split(";")
            for fan in fans_str:
                if ":" in fan:
                    cnt, rpm_hex = fan.split(":")
                    self.fan_rpm_cache[int(cnt)] = int(rpm_hex, 16)
            return self.fan_rpm_cache.copy()
        except Exception:
            logger.exception("RPM parse error")
            return {}

    # -- info --------------------------------------------------------------

    def get_hw_info(self) -> str:
        res = self._tx(0x05, None)
        return str(res) if res else "Unknown"

    def get_fw_info(self) -> str:
        res = self._tx(0x06, None)
        return str(res) if res else "Unknown"

    # -- internal ----------------------------------------------------------

    @staticmethod
    def _build_hex_data(data) -> str:
        if data is None:
            return ""
        if isinstance(data, list):
            return "".join(f"{x:02X}" for x in data)
        if isinstance(data, int):
            return f"{data:02X}"
        return ""

    def _tx(self, cmd: int, data):
        data_str = self._build_hex_data(data)
        payload = f">{cmd:02X}{data_str}"
        logger.debug("TX payload: %s", payload)
        lines = self._hw.serial_transaction(payload)
        if not lines:
            logger.debug("TX response: (empty)")
            return None
        # Find the response line that starts with '<' (firmware reply);
        # the first line is usually the command echo (starts with '>').
        for line in lines:
            if line.startswith('<'):
                logger.debug("TX response: %s", line)
                return line
        logger.debug("TX response: no '<' line in %s", lines)
        return None
