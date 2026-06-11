"""Tests for src/temperature/sensor_reader.py — cache behaviour."""

import os
import sys
import tempfile
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _write_ini(content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".ini")
    os.close(fd)
    with open(path, "w") as f:
        f.write(content)
    return path


@pytest.fixture
def ini_path():
    """Create a temporary disks.ini with two active drives."""
    path = _write_ini("""["parity"]
status="DISK_OK"
temp="33"
id="PARITY001"

["disk1"]
status="DISK_OK"
temp="42"
id="DISK1_002"
""")
    yield path
    os.unlink(path)


class TestCacheBehaviour:
    def test_first_call_populates_cache(self, ini_path):
        from temperature.sensor_reader import SensorReader
        sr = SensorReader(disks_ini_path=ini_path)
        temps = sr.read_all_temperatures()
        assert temps["parity"] == 33.0
        assert temps["disk1"] == 42.0
        assert sr._cache_time > 0

    def test_second_call_within_ttl_returns_cached(self, ini_path):
        from temperature.sensor_reader import SensorReader
        sr = SensorReader(disks_ini_path=ini_path)

        # First call
        first = sr.read_all_temperatures()
        first_time = sr._cache_time

        # Write a different disks.ini (simulate temp change)
        os.unlink(ini_path)
        with open(ini_path, "w") as f:
            f.write("""["parity"]
status="DISK_OK"
temp="99"
""")

        # Second call — should return cached stale value, not 99
        second = sr.read_all_temperatures()
        assert second == first  # same dict as cached
        assert sr._cache_time == first_time

        # Restore original ini for cleanup
        os.unlink(ini_path)
        with open(ini_path, "w") as f:
            f.write("""["parity"]
status="DISK_OK"
temp="33"
""")

    def test_cache_refreshes_after_ttl(self, ini_path, monkeypatch):
        """After TTL expires, the method re-reads from the parser (cache bypassed)."""
        from temperature.sensor_reader import SensorReader
        sr = SensorReader(disks_ini_path=ini_path)

        # First call
        first = sr.read_all_temperatures()
        old_cache_time = sr._cache_time

        # Simulate time passing (TTL + 1 second)
        monkeypatch.setattr(time, "time", lambda: old_cache_time + sr._CACHE_TTL + 1)

        # Second call — cache should be bypassed (fresh read from parser)
        second = sr.read_all_temperatures()
        # Values are the same (parser reads disks.ini only at init),
        # but cache timestamp was updated
        assert second == first
        assert sr._cache_time > old_cache_time

    def test_each_instance_has_own_cache(self):
        """Different SensorReader instances have independent caches."""
        from temperature.sensor_reader import SensorReader
        p1 = _write_ini("""["parity"]
status="DISK_OK"
temp="10"
""")
        p2 = _write_ini("""["parity"]
status="DISK_OK"
temp="90"
""")
        sr1 = SensorReader(disks_ini_path=p1)
        sr2 = SensorReader(disks_ini_path=p2)

        t1 = sr1.read_all_temperatures()
        t2 = sr2.read_all_temperatures()

        assert t1["parity"] == 10.0
        assert t2["parity"] == 90.0
        # Each instance reads from its own ini file — values differ, so caches are isolated
        assert t1 != t2

        os.unlink(p1)
        os.unlink(p2)
