# -*- coding: utf-8 -*-
"""Tests for Agent Reach config module."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from agent_reach.config import Config


@pytest.fixture
def tmp_config(tmp_path):
    """Create a Config with a temporary directory."""
    config_file = tmp_path / "config.yaml"
    return Config(config_path=config_file)


class TestConfig:
    def test_init_creates_dir(self, tmp_path):
        config_file = tmp_path / "subdir" / "config.yaml"
        config = Config(config_path=config_file)
        assert config_file.parent.exists()

    def test_set_and_get(self, tmp_config):
        tmp_config.set("test_key", "test_value")
        assert tmp_config.get("test_key") == "test_value"

    def test_get_default(self, tmp_config):
        assert tmp_config.get("nonexistent") is None
        assert tmp_config.get("nonexistent", "default") == "default"

    def test_get_from_env(self, tmp_config, monkeypatch):
        monkeypatch.setenv("TEST_ENV_KEY", "env_value")
        assert tmp_config.get("test_env_key") == "env_value"

    def test_config_file_priority_over_env(self, tmp_config, monkeypatch):
        monkeypatch.setenv("MY_KEY", "from_env")
        tmp_config.set("my_key", "from_config")
        assert tmp_config.get("my_key") == "from_config"

    def test_save_and_load(self, tmp_config):
        tmp_config.set("key1", "value1")
        tmp_config.set("key2", 42)

        # Create new config from same file
        config2 = Config(config_path=tmp_config.config_path)
        assert config2.get("key1") == "value1"
        assert config2.get("key2") == 42

    def test_corrupt_yaml_does_not_brick_cli(self, tmp_path, capsys):
        """FX-201: a torn/corrupt config must load to {} (never raise), and the
        bad file is quarantined (timestamped) so the next save starts clean."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("key: [unterminated\n:::not yaml", encoding="utf-8")

        config = Config(config_path=config_file)  # must not raise

        assert config.data == {}
        # Original quarantined; a uniquely-suffixed .corrupt.<ts>.<pid> backup exists.
        assert not config_file.exists()
        assert list(tmp_path.glob("config.yaml.corrupt.*"))

    @pytest.mark.parametrize("content", ["just some text", "- a\n- b\n", "42"])
    def test_non_dict_yaml_is_quarantined(self, tmp_path, content):
        """CR-001: valid YAML that isn't a mapping (str/list/scalar) must be
        quarantined too, or set()/to_dict() raise on every later call."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(content, encoding="utf-8")

        config = Config(config_path=config_file)  # must not raise

        assert config.data == {}
        assert not config_file.exists()
        assert list(tmp_path.glob("config.yaml.corrupt.*"))
        # And the CLI is usable afterward:
        config.set("k", "v")
        assert config.get("k") == "v"
        assert isinstance(config.to_dict(), dict)

    def test_transient_oserror_leaves_config_intact(self, tmp_path, monkeypatch):
        """CR-005: a transient OSError on read must NOT quarantine a valid config
        (a rename + empty-save cycle would permanently lose all credentials)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("groq_api_key: gsk_secret\n", encoding="utf-8")

        real_open = open

        def flaky_open(path, *a, **k):
            if str(path) == str(config_file):
                raise OSError("temporarily unavailable (AV lock)")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", flaky_open)
        config = Config(config_path=config_file)  # must not raise

        assert config.data == {}
        # File left untouched — no quarantine, original still present & readable.
        assert config_file.exists()
        assert not list(tmp_path.glob("config.yaml.corrupt*"))
        assert config_file.read_text(encoding="utf-8") == "groq_api_key: gsk_secret\n"

    def test_save_is_atomic_preserves_perms(self, tmp_config):
        """FX-201: save writes 0o600 and leaves no stray temp files."""
        tmp_config.set("secret_token", "abc123")
        mode = oct(os.stat(tmp_config.config_path).st_mode & 0o777)
        assert mode == "0o600"
        # No leftover .config.*.tmp files in the dir.
        leftovers = list(tmp_config.config_dir.glob(".config.*.tmp"))
        assert leftovers == []

    def test_delete(self, tmp_config):
        tmp_config.set("to_delete", "value")
        assert tmp_config.get("to_delete") == "value"
        tmp_config.delete("to_delete")
        assert tmp_config.get("to_delete") is None

    def test_is_configured(self, tmp_config):
        assert not tmp_config.is_configured("exa_search")
        tmp_config.set("exa_api_key", "test-key")
        assert tmp_config.is_configured("exa_search")

    def test_get_configured_features(self, tmp_config):
        features = tmp_config.get_configured_features()
        assert isinstance(features, dict)
        assert "exa_search" in features
        assert all(v is False for v in features.values())

    def test_to_dict_masks_sensitive(self, tmp_config):
        tmp_config.set("exa_api_key", "super-secret-key-12345")
        tmp_config.set("normal_setting", "visible")
        masked = tmp_config.to_dict()
        assert masked["exa_api_key"] == "super-se..."
        assert masked["normal_setting"] == "visible"

    def test_save_creates_file_with_restricted_permissions(self, tmp_path):
        import stat
        import sys
        config_file = tmp_path / "secure_config.yaml"
        config = Config(config_path=config_file)
        config.set("secret_key", "my-secret")

        if sys.platform != "win32":
            mode = config_file.stat().st_mode
            # File should be owner-only read/write (0o600)
            assert not (mode & stat.S_IRGRP), "group read should not be set"
            assert not (mode & stat.S_IROTH), "other read should not be set"
