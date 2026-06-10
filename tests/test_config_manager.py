"""Tests for src/config_manager.py — dot-notation config access."""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from config_manager import ConfigManager


@pytest.fixture
def cm():
    """Create a ConfigManager backed by a temporary SQLite database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    mgr = ConfigManager(path)
    yield mgr
    mgr._db.close()
    os.unlink(path)
    for suffix in ("-wal", "-shm"):
        wal_path = path + suffix
        if os.path.exists(wal_path):
            os.unlink(wal_path)


class TestDotNotation:
    """Top-level simple config keys."""

    def test_get_simple_key(self, cm):
        assert cm.get("server.port") == 3211
        assert cm.get("server.hostname") == "localhost"

    def test_get_nonexistent_returns_default(self, cm):
        # Looking up a missing key inside an existing dict follows dict.get()
        # semantics — returns None, not the caller's default (matches old YAML
        # behaviour where deepcopy(node).get("nope") → None).
        assert cm.get("server.nope", 42) is None
        assert cm.get("fan_profiles.Ghost") is None

    def test_set_and_get_simple(self, cm):
        cm.set("server.port", 9999)
        assert cm.get("server.port") == 9999

    def test_set_nested_simple(self, cm):
        cm.set("automation.poll_interval", 30)
        assert cm.get("automation.poll_interval") == 30

    def test_set_top_level_replaces(self, cm):
        cm.set("smartctl_devices", ["/dev/nvme0"])
        assert cm.get("smartctl_devices") == ["/dev/nvme0"]

    def test_delete_simple_key(self, cm):
        cm.set("smartctl_devices", ["/dev/sda"])
        assert cm.delete("smartctl_devices") is True
        assert cm.get("smartctl_devices") is None

    def test_delete_nonexistent_returns_false(self, cm):
        # Delete a bootstrapped key, then verify second delete returns False.
        assert cm.delete("smartctl_devices") is True   # first time: existed
        assert cm.delete("smartctl_devices") is False   # second time: gone
        # Re-create so fixture cleanup doesn't fail
        cm.set("smartctl_devices", [])


class TestProfiles:
    def test_set_full_profile(self, cm):
        cm.set("fan_profiles.Quiet", {
            "CurveType": "linear",
            "TempSource": ["disk1"],
            "UsePWM": True,
            "Points": {"30": 20, "60": 100},
        })
        p = cm.get("fan_profiles.Quiet")
        assert p["CurveType"] == "linear"
        assert p["TempSource"] == ["disk1"]
        assert p["UsePWM"] is True
        assert p["Points"] == {"30": 20, "60": 100}

    def test_get_profile_sub_field(self, cm):
        cm.set("fan_profiles.Test", {"CurveType": "threshold", "Points": {"40": 80}})
        assert cm.get("fan_profiles.Test.CurveType") == "threshold"
        assert cm.get("fan_profiles.Test.Points.40") == 80

    def test_get_nonexistent_profile_subfield_returns_default(self, cm):
        assert cm.get("fan_profiles.X.Y.Z", "missing") == "missing"

    def test_delete_profile(self, cm):
        cm.set("fan_profiles.Del", {"Points": {"0": 0}})
        assert cm.delete("fan_profiles.Del") is True
        assert cm.get("fan_profiles.Del") is None

    def test_all_includes_profiles(self, cm):
        cm.set("fan_profiles.InAll", {"CurveType": "linear", "Points": {"10": 5}})
        all_cfg = cm.all()
        assert "InAll" in all_cfg["fan_profiles"]
        assert all_cfg["fan_profiles"]["InAll"]["CurveType"] == "linear"


class TestFanControls:
    def test_assign_and_read(self, cm):
        cm.set("fan_controls.3.AssignedProfile", "Loud")
        assert cm.get("fan_controls.3.AssignedProfile") == "Loud"

    def test_get_all_controls(self, cm):
        cm.set("fan_controls.0.AssignedProfile", "A")
        cm.set("fan_controls.1.AssignedProfile", "B")
        controls = cm.get("fan_controls")
        assert controls["0"]["AssignedProfile"] == "A"
        assert controls["1"]["AssignedProfile"] == "B"

    def test_clear_control(self, cm):
        cm.set("fan_controls.5.AssignedProfile", "X")
        assert cm.delete("fan_controls.5") is True
        assert cm.get("fan_controls.5.AssignedProfile", "") == ""


class TestPersistence:
    def test_writes_survive_new_instance(self):
        """Data written by one ConfigManager is visible to another."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        cm1 = ConfigManager(path)
        cm1.set("server.port", 5000)
        cm1.set("fan_controls.2.AssignedProfile", "Persist")
        cm1.set("fan_profiles.Persist", {"CurveType": "linear", "Points": {"20": 30}})
        from db import Database
        cm1._db.close()

        cm2 = ConfigManager(path)
        assert cm2.get("server.port") == 5000
        assert cm2.get("fan_controls.2.AssignedProfile") == "Persist"
        assert cm2.get("fan_profiles.Persist.CurveType") == "linear"
        cm2._db.close()

        os.unlink(path)
        for s in ("-wal", "-shm"):
            if os.path.exists(path + s):
                os.unlink(path + s)


class TestPathResolution:
    def test_yaml_path_converts_to_db(self):
        result = ConfigManager._resolve_db_path("/etc/config.yaml")
        assert result.endswith("config.db")
        assert "config.yaml" not in result

    def test_db_path_passes_through(self):
        result = ConfigManager._resolve_db_path("/etc/config.db")
        assert result.endswith("config.db")


class TestReloadAndSave:
    def test_reload_is_noop(self, cm):
        assert cm.reload() is True

    def test_save_is_noop(self, cm):
        assert cm.save() is True