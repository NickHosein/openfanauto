"""Tests for src/temperature/disks_ini_parser.py — Unraid disks.ini parsing."""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from temperature.disks_ini_parser import DisksIniParser


def _write_ini(content: str) -> str:
    """Write a temporary disks.ini and return its path."""
    fd, path = tempfile.mkstemp(suffix=".ini")
    os.close(fd)
    with open(path, "w") as f:
        f.write(content)
    return path


class TestActiveDrives:
    def test_active_drive_has_temperature(self):
        ini = _write_ini("""["disk1"]
idx="1"
name="disk1"
device="sdf"
id="ST10000VN0004-1ZD101_ZA2C37RX"
status="DISK_OK"
temp="37"
spundown="0"
""")
        parser = DisksIniParser(ini)
        assert parser.sensors["disk1"] == 37.0
        assert parser.disk_ids["disk1"] == "37RX"
        os.unlink(ini)

    def test_multiple_active_drives(self):
        ini = _write_ini("""["parity"]
status="DISK_OK"
temp="33"
id="ST20000NM002C-3X6103_ZXA0E29M"

["disk1"]
status="DISK_OK"
temp="42"
id="ST10000VN0004-1ZD101_ZA2C37RX"

["disk2"]
status="DISK_OK"
temp="38"
id="ST10000VN0004-1ZD101_ZA2C36T8"
""")
        parser = DisksIniParser(ini)
        assert len(parser.sensors) == 3
        assert parser.sensors["parity"] == 33.0
        assert parser.sensors["disk1"] == 42.0
        assert parser.sensors["disk2"] == 38.0
        os.unlink(ini)


class TestSpundownDrives:
    def test_spundown_drive_included_with_none_temp(self):
        ini = _write_ini("""["disk4"]
status="DISK_OK"
temp="*"
spundown="1"
id="ST12000NM001G-2MV103_ZLW27CAY"
""")
        parser = DisksIniParser(ini)
        assert "disk4" in parser.sensors
        assert parser.sensors["disk4"] is None
        assert parser.disk_ids["disk4"] == "7CAY"
        os.unlink(ini)

    def test_question_mark_temp_treated_as_none(self):
        ini = _write_ini("""["flash"]
status="DISK_OK"
temp="?"
id="Cruzer_Fit"
""")
        parser = DisksIniParser(ini)
        assert "flash" in parser.sensors
        assert parser.sensors["flash"] is None
        os.unlink(ini)

    def test_empty_temp_treated_as_none(self):
        ini = _write_ini("""["drive"]
status="DISK_OK"
temp=""
id="SOMEID1234"
""")
        parser = DisksIniParser(ini)
        assert "drive" in parser.sensors
        assert parser.sensors["drive"] is None
        os.unlink(ini)


class TestEmptySlotsExcluded:
    def test_disk_np_excluded(self):
        ini = _write_ini("""["disk8"]
status="DISK_NP"
temp="*"
""")
        parser = DisksIniParser(ini)
        assert "disk8" not in parser.sensors
        os.unlink(ini)

    def test_disk_np_dsbl_excluded(self):
        ini = _write_ini("""["parity2"]
status="DISK_NP_DSBL"
temp="*"
""")
        parser = DisksIniParser(ini)
        assert "parity2" not in parser.sensors
        os.unlink(ini)

    def test_no_status_excluded(self):
        ini = _write_ini("""["mystery"]
temp="25"
""")
        parser = DisksIniParser(ini)
        assert "mystery" not in parser.sensors
        os.unlink(ini)


class TestDiskIds:
    def test_disk_ids_captured_for_spundown_drives(self):
        ini = _write_ini("""["disk1"]
status="DISK_OK"
temp="*"
id="ABCD1234EFGH"
""")
        parser = DisksIniParser(ini)
        assert "disk1" in parser.disk_ids
        assert parser.disk_ids["disk1"] == "EFGH"
        os.unlink(ini)

    def test_disk_ids_empty_when_no_id(self):
        ini = _write_ini("""["parity"]
status="DISK_OK"
temp="33"
id=""
""")
        parser = DisksIniParser(ini)
        assert "parity" not in parser.disk_ids
        os.unlink(ini)


class TestEdgeCases:
    def test_mixed_active_and_spundown(self):
        ini = _write_ini("""["parity"]
status="DISK_OK"
temp="33"
id="PARITYID001"

["disk1"]
status="DISK_OK"
temp="*"
spundown="1"
id="DISK1ID002"

["disk8"]
status="DISK_NP"
temp="*"

["disk2"]
status="DISK_OK"
temp="37"
id="DISK2ID003"
""")
        parser = DisksIniParser(ini)
        assert len(parser.sensors) == 3  # parity, disk1, disk2 (disk8 excluded)
        assert parser.sensors["parity"] == 33.0
        assert parser.sensors["disk1"] is None
        assert parser.sensors["disk2"] == 37.0
        assert "disk8" not in parser.sensors
        assert parser.disk_ids["parity"] == "D001"
        assert parser.disk_ids["disk1"] == "D002"
        assert parser.disk_ids["disk2"] == "D003"
        os.unlink(ini)

    def test_file_not_found(self):
        parser = DisksIniParser("/nonexistent/path/disks.ini")
        assert parser.sensors == {}
        assert parser.disk_ids == {}

    def test_list_sensors(self):
        ini = _write_ini("""["parity"]
status="DISK_OK"
temp="33"

["disk1"]
status="DISK_OK"
temp="*"

["disk2"]
status="DISK_OK"
temp="37"
""")
        parser = DisksIniParser(ini)
        names = parser.list_sensors()
        assert "parity" in names
        assert "disk1" in names
        assert "disk2" in names
        assert len(names) == 3
        os.unlink(ini)

    def test_get_temperature(self):
        ini = _write_ini("""["disk1"]
status="DISK_OK"
temp="42"
""")
        parser = DisksIniParser(ini)
        assert parser.get_temperature("disk1") == 42.0
        assert parser.get_temperature("nonexistent") == -1.0
        os.unlink(ini)