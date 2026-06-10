"""Tests for src/db.py — SQLite database layer."""

import os
import sys
import tempfile
import pytest

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from db import Database


@pytest.fixture
def db():
    """Create a temporary database for each test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_inst = Database(path)
    yield db_inst
    db_inst.close()
    os.unlink(path)
    # Clean up WAL/SHM files if they exist
    for suffix in ("-wal", "-shm"):
        wal_path = path + suffix
        if os.path.exists(wal_path):
            os.unlink(wal_path)


class TestBootstrap:
    def test_default_config_keys_exist(self, db):
        """Fresh database gets default config entries."""
        assert db.get_config("server") == {"hostname": "localhost", "port": 3211}
        assert db.get_config("automation") == {"enabled": False, "poll_interval": 10}
        assert db.get_config("hardware") == {"port": None, "debug_uart": False}

    def test_bootstrap_is_idempotent(self, db):
        """Bootstrapping twice doesn't duplicate or overwrite."""
        db.set_config("server", {"hostname": "custom", "port": 9999})
        db._bootstrap_defaults()  # should not overwrite
        assert db.get_config("server") == {"hostname": "custom", "port": 9999}


class TestConfigCRUD:
    def test_set_and_get(self, db):
        db.set_config("test_key", [1, 2, 3])
        assert db.get_config("test_key") == [1, 2, 3]

    def test_get_missing_returns_default(self, db):
        assert db.get_config("nonexistent") is None
        assert db.get_config("nonexistent", "fallback") == "fallback"

    def test_delete_config(self, db):
        db.set_config("temp_key", 42)
        assert db.delete_config("temp_key") is True
        assert db.get_config("temp_key") is None

    def test_delete_missing_returns_false(self, db):
        assert db.delete_config("never_there") is False

    def test_get_all_config(self, db):
        db.set_config("custom", {"a": 1})
        all_cfg = db.get_all_config()
        assert "server" in all_cfg
        assert "fan_profiles" in all_cfg
        assert "fan_controls" in all_cfg
        assert all_cfg["custom"] == {"a": 1}


class TestProfileCRUD:
    def test_save_and_get_profiles(self, db):
        db.save_profile("Test", curve_type="linear", use_pwm=True,
                        temp_sources=["disk1", "disk2"],
                        points={30: 20, 60: 100},
                        temp_group_eval="min")
        profiles = db.get_profiles()
        assert "Test" in profiles
        p = profiles["Test"]
        assert p["CurveType"] == "linear"
        assert p["UsePWM"] is True
        assert p["TempSource"] == ["disk1", "disk2"]
        assert p["Points"] == {"30": 20, "60": 100}
        assert p["TempGroupEval"] == "min"

    def test_get_single_profile(self, db):
        db.save_profile("Solo", points={40: 50})
        p = db.get_profile("Solo")
        assert p["CurveType"] == "threshold"  # default
        assert p["Points"] == {"40": 50}
        assert db.get_profile("Ghost") is None

    def test_update_profile(self, db):
        db.save_profile("Up", points={20: 30})
        db.save_profile("Up", curve_type="linear", points={25: 40, 50: 80})
        p = db.get_profile("Up")
        assert p["CurveType"] == "linear"
        assert p["Points"] == {"25": 40, "50": 80}

    def test_delete_profile(self, db):
        db.save_profile("Gone", points={10: 0})
        assert db.delete_profile("Gone") is True
        assert "Gone" not in db.get_profiles()

    def test_delete_profile_cascades(self, db):
        """Deleting a profile removes its points, sources, and control assignments."""
        db.save_profile("Cascade", temp_sources=["s1"], points={10: 0})
        db.assign_control("0", "Cascade")

        db.delete_profile("Cascade")

        # Profile gone
        assert "Cascade" not in db.get_profiles()
        # Fan control cleared
        ctrl = db.get_controls().get("0", {})
        assert ctrl.get("AssignedProfile") == ""

    def test_delete_profile_returns_false_for_missing(self, db):
        assert db.delete_profile("Ghost") is False


class TestFanControls:
    def test_assign_and_read(self, db):
        db.assign_control("0", "Quiet")
        controls = db.get_controls()
        assert controls["0"]["AssignedProfile"] == "Quiet"

    def test_clear_control(self, db):
        db.assign_control("3", "Loud")
        db.clear_control("3")
        assert db.get_controls().get("3", {}).get("AssignedProfile", "") == ""

    def test_multiple_assignments(self, db):
        db.assign_control("0", "A")
        db.assign_control("1", "B")
        db.assign_control("2", "A")
        controls = db.get_controls()
        assert controls["0"]["AssignedProfile"] == "A"
        assert controls["1"]["AssignedProfile"] == "B"
        assert controls["2"]["AssignedProfile"] == "A"