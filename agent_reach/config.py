# -*- coding: utf-8 -*-
"""Configuration management for Agent Reach.

Stores settings in ~/.agent-reach/config.yaml.
Auto-creates directory on first use.
"""

import os
import time
from pathlib import Path
from typing import Any, Optional

import yaml


class ConfigError(RuntimeError):
    """Raised when persisting config would risk clobbering unread credentials."""


class Config:
    """Manages Agent Reach configuration."""

    CONFIG_DIR = Path.home() / ".agent-reach"
    CONFIG_FILE = CONFIG_DIR / "config.yaml"

    #: Set when load() hit a transient read error — save() then refuses to
    #: overwrite the on-disk file (which still holds the real credentials).
    _load_unsafe: bool = False

    # Feature → required config keys
    FEATURE_REQUIREMENTS = {
        "exa_search": ["exa_api_key"],
        "twitter_xreach": ["twitter_auth_token", "twitter_ct0"],  # legacy key name; used by twitter-cli
        "groq_whisper": ["groq_api_key"],
        "openai_whisper": ["openai_api_key"],
        "github_token": ["github_token"],
    }

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = Path(config_path) if config_path else self.CONFIG_FILE
        self.config_dir = self.config_path.parent
        self.data: dict = {}
        self._ensure_dir()
        self.load()

    def _ensure_dir(self):
        """Create config directory if it doesn't exist."""
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load(self):
        """Load config from YAML file.

        A torn or hand-corrupted config must never brick the CLI: Config() is
        constructed on every command, so an unguarded YAMLError here would take
        down the whole tool.

        Only a *parse* error (YAMLError) means the file is genuinely bad — then
        we quarantine it (timestamped, never clobbering an existing backup) and
        start empty. A *transient* OSError (EACCES/EIO, an AV lock, a busy file)
        must NOT quarantine a valid credentials file — we warn and continue with
        empty data, leaving the file untouched so the next read recovers it
        (CR-005: a rename+empty-save cycle would otherwise lose all cookies/keys).
        """
        import sys

        if not self.config_path.exists():
            self.data = {}
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
        except yaml.YAMLError as e:
            self._quarantine_corrupt(f"unparseable: {e}")
            return
        except OSError as e:
            # Transient I/O (EACCES/EIO/AV-lock): the file exists but we couldn't
            # read it. Proceed with empty data for read-only commands, but mark the
            # instance unsafe-to-save so a later set()/configure can't os.replace()
            # an empty config over the credentials we simply failed to read (REG-4).
            print(
                f"[!] 暂时无法读取配置（未改动文件）/ config temporarily unreadable "
                f"(file left intact): {e}",
                file=sys.stderr,
            )
            self.data = {}
            self._load_unsafe = True
            return
        # Valid YAML but not a mapping (a bare string / list) would make set() and
        # to_dict() raise on every later call — treat it like a corrupt file (CR-001).
        if loaded is None:
            self.data = {}
        elif isinstance(loaded, dict):
            self.data = loaded
        else:
            self._quarantine_corrupt(f"not a mapping (got {type(loaded).__name__})")

    def _quarantine_corrupt(self, why: str):
        """Move a genuinely-bad config aside (uniquely named, never clobbering an
        existing backup) and start from empty data."""
        import sys

        # time + pid so a PID reused after reboot/container restart can't overwrite
        # a prior quarantined credentials file (CR-002).
        stamp = f"{int(time.time())}.{os.getpid()}"
        corrupt = self.config_path.with_suffix(
            self.config_path.suffix + f".corrupt.{stamp}"
        )
        try:
            os.replace(self.config_path, corrupt)
            where = f"（已备份到 {corrupt}）"
        except OSError:
            where = ""
        print(
            f"[!] 配置文件无效，已忽略并从空配置开始{where} / "
            f"config invalid ({why}), quarantined and starting empty",
            file=sys.stderr,
        )
        self.data = {}

    def save(self):
        """Save config to YAML file atomically.

        Write to a temp file in the same directory (0o600 from creation, so
        credentials are never briefly world-readable) then os.replace() onto
        the target — an interrupted write leaves the previous config intact
        instead of a half-truncated file that would fail to parse next load.

        Refuses if this run couldn't read the existing config (transient I/O):
        overwriting then would replace real credentials with our empty/partial
        in-memory data (REG-4). The caller should surface the error and retry.
        """
        if self._load_unsafe:
            raise ConfigError(
                "拒绝写入：本次运行无法读取现有配置，覆盖会丢失已保存的凭据。"
                "请确认 ~/.agent-reach/config.yaml 可读后重试 / refusing to save: this "
                "run could not read the existing config; overwriting would lose "
                "stored credentials — fix file access and retry."
            )
        self._ensure_dir()
        import stat
        import tempfile

        fd, tmp = tempfile.mkstemp(
            dir=str(self.config_dir), prefix=".config.", suffix=".tmp"
        )
        try:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.dump(self.data, f, default_flow_style=False, allow_unicode=True)
                # Durability: flush + fsync before the atomic replace so a power
                # loss can't leave an empty/torn target that the next load would
                # then (correctly) treat as needing recovery (CR-006).
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(self.config_path))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value. Also checks environment variables (uppercase)."""
        # Config file first
        if key in self.data:
            return self.data[key]
        # Then env var (uppercase)
        env_val = os.environ.get(key.upper())
        if env_val:
            return env_val
        return default

    def set(self, key: str, value: Any):
        """Set a config value and save."""
        self.data[key] = value
        self.save()

    def delete(self, key: str):
        """Delete a config key and save."""
        self.data.pop(key, None)
        self.save()

    def is_configured(self, feature: str) -> bool:
        """Check if a feature has all required config."""
        required = self.FEATURE_REQUIREMENTS.get(feature, [])
        return all(self.get(k) for k in required)

    def get_configured_features(self) -> dict:
        """Return status of all optional features."""
        return {
            feature: self.is_configured(feature)
            for feature in self.FEATURE_REQUIREMENTS
        }

    def to_dict(self) -> dict:
        """Return config as dict (masks sensitive values)."""
        masked = {}
        for k, v in self.data.items():
            if any(s in k.lower() for s in ("key", "token", "password", "proxy")):
                masked[k] = f"{str(v)[:8]}..." if v else None
            else:
                masked[k] = v
        return masked
