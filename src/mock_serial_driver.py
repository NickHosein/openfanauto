"""MockSerialHardware — simulates an OpenFAN controller for development/testing.

Activate via ``MOCK_HARDWARE=true`` environment variable.
"""

from __future__ import annotations

import time
from threading import Lock

from base_logger import logger


class MockSerialHardware:
    """Drop-in replacement for ``SerialHardware`` / ``FanCommander``.

    Simulates fan RPM responses at configured PWM speeds without requiring
    real hardware.  Used when ``MOCK_HARDWARE=true``.
    """

    # Number of emulated fan channels
    NUM_FANS = 10

    # RPM range
    RPM_MIN = 480
    RPM_MAX = 16000

    def __init__(
        self,
        port_info: str = "MOCK",
        flush_on_write: bool = True,
        serialPrefix: str = "",
        serialSuffix: str = "\r\n",
        timeout: float = 0.2,
        debug_uart: bool = False,
    ) -> None:
        _ = (port_info, flush_on_write, serialPrefix, serialSuffix, timeout, debug_uart)
        self.lock = Lock()
        self._pwm: dict[int, int] = {i: 0 for i in range(self.NUM_FANS)}
        self._rpm: dict[int, int] = {i: self.RPM_MIN for i in range(self.NUM_FANS)}
        self._hw_info = "Mock Hardware v1.0"
        self._fw_info = "Mock Firmware v1.0"
        self._buffer: list[str] = []

    # -- public API matching real driver --------------------------------

    def open(self) -> None:
        logger.debug("Mock serial port opened")

    def close(self) -> None:
        logger.debug("Mock serial port closed")

    def is_open(self) -> bool:
        return True

    def assert_open(self) -> bool:
        return True

    def get_port_info(self) -> str:
        return "MOCK"

    def description(self) -> str:
        return "Mock Serial Port"

    # -- FanCommander-level commands (mirror the real device protocol) --

    @staticmethod
    def _rpm_from_pwm(pwm_byte: int) -> int:
        """Convert 0-255 PWM byte to simulated RPM."""
        if pwm_byte == 0:
            return 0
        # Linear: 480 at min, 16000 at max
        return int(MockSerialHardware.RPM_MIN + (pwm_byte / 255) * (MockSerialHardware.RPM_MAX - MockSerialHardware.RPM_MIN))

    def _process_command(self, cmd: int, data_bytes: list[int] | None = None) -> list[str]:
        """Process a command and return response lines."""
        responses: list[str] = []

        if cmd == 0x00:  # Get all RPM
            rpm_parts = []
            for i in range(self.NUM_FANS):
                rpm_parts.append(f"{i}:{self._rpm[i]:04X}")
            responses.append(f"<|{';'.join(rpm_parts)}")

        elif cmd == 0x01:  # Get single fan RPM
            idx = data_bytes[0] if data_bytes else 0
            responses.append(f"<|{idx}:{self._rpm.get(idx, 0):04X}")

        elif cmd == 0x02:  # Set single fan PWM
            idx = data_bytes[0] if data_bytes else 0
            pwm_byte = data_bytes[1] if data_bytes and len(data_bytes) > 1 else 0
            self._pwm[idx] = pwm_byte
            self._rpm[idx] = self._rpm_from_pwm(pwm_byte)
            responses.append("<|OK")

        elif cmd == 0x03:  # Set ALL PWM
            pwm_byte = data_bytes[0] if data_bytes else 0
            for i in range(self.NUM_FANS):
                self._pwm[i] = pwm_byte
                self._rpm[i] = self._rpm_from_pwm(pwm_byte)
            responses.append("<|OK")

        elif cmd == 0x04:  # Set single fan RPM target
            idx = data_bytes[0] if data_bytes else 0
            if data_bytes and len(data_bytes) >= 3:
                rpm_val = (data_bytes[1] << 8) | data_bytes[2]
                self._rpm[idx] = rpm_val
            responses.append("<|OK")

        elif cmd == 0x05:  # HW info
            responses.append(f"<{self._hw_info}")

        elif cmd == 0x06:  # FW info
            responses.append(f"<{self._fw_info}")

        return responses

    def serial_transaction(self, payload: str, ignore_response: bool = False) -> list[str]:
        """Process a serial command and return response lines."""
        with self.lock:
            if not payload.startswith(">"):
                return []

            # Parse: ">CCxx..."
            hex_part = payload[1:]
            if len(hex_part) < 2:
                return []

            try:
                cmd = int(hex_part[0:2], 16)
            except ValueError:
                return []

            data_str = hex_part[2:]
            data_bytes: list[int] = []
            for i in range(0, len(data_str), 2):
                try:
                    data_bytes.append(int(data_str[i:i+2], 16))
                except ValueError:
                    pass

            responses = self._process_command(cmd, data_bytes)

            if ignore_response:
                return []

            return responses