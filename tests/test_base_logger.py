"""Unit tests for base_logger.set_logger_level()."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from base_logger import set_logger_level, logger


class TestSetLoggerLevel:
    def test_debug(self):
        set_logger_level("debug")
        assert logger.level == logging.DEBUG  # 10

    def test_info(self):
        set_logger_level("info")
        assert logger.level == logging.INFO  # 20

    def test_uppercase(self):
        set_logger_level("DEBUG")
        assert logger.level == logging.DEBUG

    def test_mixed_case(self):
        set_logger_level("Debug")
        assert logger.level == logging.DEBUG

    def test_unknown_defaults_to_info(self):
        set_logger_level("banana")
        assert logger.level == logging.INFO

    def test_no_arg_defaults_to_info(self):
        set_logger_level()
        assert logger.level == logging.INFO